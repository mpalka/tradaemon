"""Live/paper trading engine.

A `Book` is one self-contained portfolio (cash, positions, risk, models) with
its own runtime files. `TradingEngine` streams candles once and dispatches each
closed candle to every book, so several strategy variants can trade the same
market in parallel (live A/B) without multiplying API calls.

Each book mirrors the backtester exactly: on a closed candle it manages the open
position (TP/SL/timeout) and then considers a new entry from the model signal.
Decisions happen only on closed candles; the ticker loop updates valuations for
display without ever trading.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd

from tradaemon import i18n
from tradaemon.config import Config, config_path, load_config, overrides_path
from tradaemon.config_store import restart_requested_at
from tradaemon.data import storage
from tradaemon.engine.notify import send_webhook
from tradaemon.engine.state import RuntimeStore
from tradaemon.execution.executors import Executor
from tradaemon.execution.fills import check_bracket_exit
from tradaemon.features.engineering import compute_atr, compute_features
from tradaemon.i18n import t_in
from tradaemon.models.train import ModelBundle, load_bundles
from tradaemon.risk.manager import RiskManager

log = logging.getLogger(__name__)

POLL_SECONDS = 5.0
TICKER_SECONDS = 60.0
RESTART_POLL_SECONDS = 10.0

# Backoff for every network retry here. The first waits are short because the
# common failure is a NAS that came up before its router did; the ceiling is five
# minutes because on 4h candles noticing recovery five minutes late costs 2% of one
# bar, while retrying every five seconds through a six-hour outage buries the
# container log — which on Synology is not rotated.
RETRY_SECONDS = 5.0
MAX_RETRY_SECONDS = 300.0
CONNECTION_ALERT_AFTER = 3   # failed attempts before the journals are told

# Config fields a running book can adopt on its next candle, because they are read
# fresh out of self.cfg inside _maybe_enter / _manage_position. Everything else
# (symbols, timeframe, warmup, the variant list) is baked into __init__ or the feed
# and needs the restart handshake instead — see config_store.RESTART_FIELDS.
HOT_STRATEGY_FIELDS = ("prob_threshold", "tp_atr_mult", "sl_atr_mult",
                       "horizon_bars", "atr_period", "direction", "rollover")
HOT_RISK_FIELDS = ("position_pct", "max_open_positions",
                   "daily_loss_limit_pct", "drawdown_alert_pct")
HOT_COST_FIELDS = ("taker_fee", "maker_fee", "slippage_bps")


class RestartRequested(Exception):
    """The dashboard asked the engine to come back with a fresh config."""


@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float
    entry_fees: float
    tp: float
    sl: float
    entry_time: datetime
    deadline: datetime
    side: str = "long"     # "long" | "short"
    margin: float = 0.0    # cash set aside at entry (futures-style accounting)
    # What the model said when this position was opened. Defaulted rather than
    # required: books running on the NAS have open positions serialized in
    # state.json from before this field existed, and a restart must not trip over
    # its own saved state. Those positions close with prob=None, which is the
    # truth about them — there is no way to recover a probability after the fact.
    entry_prob: float | None = None

    def to_json(self) -> dict:
        d = asdict(self)
        d["entry_time"] = self.entry_time.isoformat()
        d["deadline"] = self.deadline.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict) -> Position:
        d = dict(d)
        d["entry_time"] = datetime.fromisoformat(d["entry_time"])
        d["deadline"] = datetime.fromisoformat(d["deadline"])
        d.setdefault("side", "long")
        d.setdefault("margin", d["qty"] * d["entry_price"])
        return cls(**d)

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1


class Book:
    """One portfolio/variant. Fully synchronous and unit-testable: feed it
    closed candles via on_candle and inspect positions/cash/equity."""

    def __init__(
        self,
        name: str,
        cfg: Config,
        bundles: dict[str, ModelBundle] | ModelBundle,
        executor: Executor,
        store: RuntimeStore,
        risk: RiskManager | None = None,
    ):
        self.name = name
        self.cfg = cfg
        self.bundles = bundles if isinstance(bundles, dict) else {"long": bundles}
        self.executor = executor
        self.store = store
        self.risk = risk or RiskManager(cfg.risk)
        self.buffers: dict[str, pd.DataFrame] = {}
        self.positions: dict[str, Position] = {}
        self.last_close: dict[str, float] = {}
        self.signals: dict[str, dict] = {}
        self.last_candle_ts: dict[str, str] = {}
        self.cash = cfg.paper.initial_capital
        self._peak_equity = cfg.paper.initial_capital
        self._dd_alerted = False
        self._kill_alerted = False
        self._buffer_len = cfg.strategy.warmup_bars + int(cfg.strategy.horizon_bars) + 50
        self._bar_delta = timedelta(milliseconds=storage.TIMEFRAME_MS[cfg.exchange.timeframe])
        self._model_path = cfg.paths.models_dir / "model_long.joblib"
        self._model_mtime = self._current_model_mtime()
        self._config_path = config_path()
        self._overrides_path = overrides_path(self._config_path)
        self._config_digest = self._config_fingerprint()
        self._config_error_digest: str | None = None

    # ---------- models ----------

    def _current_model_mtime(self) -> float:
        """An mtime is enough here, unlike for the config below: the model file is
        megabytes (hashing it every candle would not be free), only refresh.py ever
        replaces it, and nothing deletes it. The config file is tiny and "delete it"
        is a documented user action — restoring a default."""
        return self._model_path.stat().st_mtime if self._model_path.exists() else 0.0

    def _maybe_reload_models(self) -> None:
        mtime = self._current_model_mtime()
        if mtime > self._model_mtime:
            try:
                self.bundles = load_bundles(self.cfg.paths.models_dir)
                self._model_mtime = mtime
                log.info("[%s] reloaded models (updated on disk)", self.name)
            except Exception:
                log.exception("[%s] model reload failed, keeping current models", self.name)

    # ---------- config ----------

    def _config_fingerprint(self) -> str:
        """Content hash of every file _fresh_variant_config() reads.

        A watch is only sound when it covers all the inputs of the reload it gates.
        The previous one watched an mtime on one of the two files and compared it
        with `>`, which was blind in three ways that all end the same — the book
        keeps trading on parameters the disk no longer holds, until someone
        restarts the container:

        * "restore default" on the last remaining override *deletes* the file, so
          the mtime dropped to 0.0. Never greater than what we had, so the watch
          went silent for good — for every field, not just the reverted one;
        * two saves inside one mtime tick collapsed into one;
        * any rewrite carrying an older or equal mtime (rsync, an editor, a
          deploy) was ignored.

        Hashing sidesteps the clock entirely. Both files are a few kB and this runs
        a few dozen times per candle, so the read is free next to the YAML parse it
        saves. config.yaml is in here too because it is the other half of what gets
        merged: a hand edit to the baseline was previously unadoptable by design.
        """
        h = hashlib.sha256()
        for path in (self._config_path, self._overrides_path):
            h.update(path.read_bytes() if path.exists() else b"")
            h.update(b"\0")   # separator, so two files cannot smear into one digest
        return h.hexdigest()

    def _fresh_variant_config(self) -> Config | None:
        """Reload config.yaml + overrides and re-apply this book's variant overrides.

        Returns None when the book can no longer be identified in the fresh config —
        that means the `variants:` list itself changed, which is a restart-only edit,
        so the safe move is to keep running on the parameters we started with rather
        than silently adopting the base config's.
        """
        fresh = load_config()
        if not fresh.variants:
            return fresh if self.name == "default" else None
        match = next((v for v in fresh.variants if v.name == self.name), None)
        if match is None:
            log.warning("[%s] not in the reloaded variants list — keeping current config "
                        "(restart the engine to pick up variant changes)", self.name)
            return None
        return fresh.for_variant(match)

    def _maybe_reload_config(self, now: datetime) -> None:
        """Adopt hot config fields written by the dashboard (or by hand). Reload on a
        content change, never let a bad file stop trading, and never let a reload that
        failed look like one that finished."""
        digest = self._config_fingerprint()
        if digest == self._config_digest:
            return
        try:
            fresh = self._fresh_variant_config()
        except Exception:
            # The digest is deliberately not recorded here. A reload that raised
            # adopted nothing, and marking its content as handled would freeze the
            # book on the old parameters until a restart — which is exactly what the
            # old watch did by recording before it tried. So: retry next candle, but
            # complain only once per distinct broken file. Ten symbols x four books
            # would otherwise put forty tracebacks per bar into a log that Synology
            # does not rotate.
            if digest != self._config_error_digest:
                self._config_error_digest = digest
                log.exception("[%s] config reload failed, keeping current config", self.name)
            return
        self._config_error_digest = None
        # Recorded here rather than after the field diff below: a reload that read the
        # files and found nothing hot to change is *done* with that content. Recording
        # only on an adopted change would re-parse both YAMLs on every candle forever
        # after a save that touched restart-only fields.
        self._config_digest = digest
        if fresh is None:
            return

        changes: list[str] = []
        strat = self.cfg.strategy.model_dump()
        for f in HOT_STRATEGY_FIELDS:
            new = getattr(fresh.strategy, f)
            if strat[f] != new:
                changes.append(f"{f}: {strat[f]} → {new}")
                strat[f] = new
        risk = self.cfg.risk.model_dump()
        for f in HOT_RISK_FIELDS:
            new = getattr(fresh.risk, f)
            if risk[f] != new:
                changes.append(f"{f}: {risk[f]} → {new}")
                risk[f] = new
        costs = self.cfg.costs.model_dump()
        for f in HOT_COST_FIELDS:
            new = getattr(fresh.costs, f)
            if costs[f] != new:
                changes.append(f"{f}: {costs[f]} → {new}")
                costs[f] = new
        if not changes:
            return

        self.cfg = self.cfg.model_copy(update={
            "strategy": type(self.cfg.strategy)(**strat),
            "risk": type(self.cfg.risk)(**risk),
            "costs": type(self.cfg.costs)(**costs),
        })
        self.risk.cfg = self.cfg.risk
        # horizon_bars feeds the buffer length; keeping more history is harmless and
        # keeping too little would starve the features, so recompute it here.
        self._buffer_len = (self.cfg.strategy.warmup_bars
                            + int(self.cfg.strategy.horizon_bars) + 50)
        # The executor is shared across books and prices paper fills from its own
        # reference to CostsConfig; costs are not variant-overridable, so every book
        # writes the same value and the repeat is idempotent.
        if hasattr(self.executor, "costs"):
            self.executor.costs = self.cfg.costs
        self.alert("config", "alert.config", {"changes": ", ".join(changes)}, now)

    # ---------- state ----------

    def equity(self) -> float:
        held = sum(
            p.margin + p.sign * p.qty * (self.last_close.get(sym, p.entry_price) - p.entry_price)
            for sym, p in self.positions.items()
        )
        return self.cash + held

    def drawdown_pct(self) -> float:
        eq = self.equity()
        self._peak_equity = max(self._peak_equity, eq)
        return (eq / self._peak_equity - 1.0) * 100.0 if self._peak_equity else 0.0

    def alert(self, kind: str, msg_key: str, params: dict, now: datetime,
              **extra) -> None:
        """Journal one event, in a form the panel can re-render in any language.

        The record carries `msg_key` + `params` **and** a rendered `message`. The key
        is what the dashboard uses, so the same outage reads in Polish or English
        depending on who is looking. The rendered sentence is kept for two reasons:
        the webhook and the log have no viewer to ask, and every line already written
        by an earlier version has only that field — `humanize.event_line` falls back
        to it, so a running deployment's history stays readable instead of turning
        into a column of bare keys.
        """
        message = t_in(self._lang, msg_key, **params)
        self.store.append_alert({"timestamp": now.isoformat(), "kind": kind,
                                 "msg_key": msg_key, "params": params,
                                 "message": message, "variant": self.name, **extra})
        log.info("[%s] ALERT [%s] %s", self.name, kind, message)
        send_webhook(self.cfg.alert_webhook_url, f"[{self.name}][{kind}] {message}")

    @property
    def _lang(self) -> str:
        """The engine has no viewer, so the config decides what the webhook says."""
        return i18n.normalize(self.cfg.display_language) or i18n.DEFAULT_LANG

    def restore(self) -> None:
        state = self.store.load_state()
        if not state:
            return
        self.cash = float(state["cash"])
        self.positions = {
            sym: Position.from_json(p) for sym, p in state.get("positions", {}).items()
        }
        self._peak_equity = float(state.get("peak_equity", self.cash))
        self.risk.restore(state.get("risk", {}))
        # persist() writes five facts about the market; this used to read three. That
        # asymmetry was the bug: a start that died before seed_buffer ran still
        # reached the persist on the way out and wrote back the empty dicts __init__
        # had left, while equity() — having no prices — valued every position at its
        # entry. The file looked plausible instead of empty, and the panel drew a
        # live point the benchmarks could not match.
        self.last_close = {s: float(v) for s, v in state.get("last_close", {}).items()}
        self.last_candle_ts = dict(state.get("last_candle_ts", {}))
        log.info("[%s] restored: cash=%.2f, open positions: %s",
                 self.name, self.cash, list(self.positions) or "none")

    def live_config(self) -> dict:
        """The hot parameters this book is enforcing right now, keyed by dotted path.

        The panel reads config off disk; until this existed there was nothing to check
        that against, so a book stuck on old parameters looked exactly like one that
        had adopted them. Keys match config_store.HOT_FIELDS so the comparison is a
        plain dict diff with no translation table in between — a test welds the two
        lists together, because a field added to one and not the other would quietly
        stop being checked.
        """
        return ({f"strategy.{f}": getattr(self.cfg.strategy, f) for f in HOT_STRATEGY_FIELDS}
                | {f"risk.{f}": getattr(self.cfg.risk, f) for f in HOT_RISK_FIELDS}
                | {f"costs.{f}": getattr(self.cfg.costs, f) for f in HOT_COST_FIELDS})

    def persist(self, now: datetime) -> None:
        eq = self.equity()
        self.store.save_state({
            "updated_at": now.isoformat(),
            "variant": self.name,
            "mode": self.cfg.mode,
            "timeframe": self.cfg.exchange.timeframe,
            "symbols": self.cfg.exchange.symbols,
            "cash": self.cash,
            "equity": eq,
            "peak_equity": self._peak_equity,
            "drawdown_pct": self.drawdown_pct(),
            "last_close": self.last_close,
            "last_candle_ts": self.last_candle_ts,
            "signals": self.signals,
            "positions": {s: p.to_json() for s, p in self.positions.items()},
            "risk": self.risk.snapshot(),
            "live_config": self.live_config(),
            "kill_switch": self.risk.kill_switch_active(now, eq),
        })

    def seed_buffer(self, symbol: str, df: pd.DataFrame) -> None:
        self.buffers[symbol] = df
        if len(df):
            self.last_close[symbol] = float(df["close"].iloc[-1])
            # The preload drops the still-open candle, so this row *is* the last
            # closed one, by its open time — exactly what bot_status reasons about.
            # Without it the panel calls a freshly restarted, perfectly healthy bot
            # "has not read the market yet" until the next candle closes: four hours
            # of red light for nothing.
            self.last_candle_ts[symbol] = df["timestamp"].iloc[-1].isoformat()

    def mark_to_market(self, prices: dict[str, float], now: datetime) -> None:
        """Display-only valuation refresh (ticker); never trades."""
        self.last_close.update(prices)
        self.persist(now)

    # ---------- core logic (sync) ----------

    def on_candle(self, symbol: str, bar: dict) -> None:
        buf = self.buffers.get(symbol, pd.DataFrame(columns=storage.OHLCV_COLUMNS))
        buf = pd.concat([buf, pd.DataFrame([bar])], ignore_index=True).tail(self._buffer_len)
        buf = buf.reset_index(drop=True)
        num_cols = ["open", "high", "low", "close", "volume"]
        buf[num_cols] = buf[num_cols].astype(float)
        buf["timestamp"] = pd.to_datetime(buf["timestamp"], utc=True)
        self.buffers[symbol] = buf
        self.last_close[symbol] = float(bar["close"])
        # Two clocks in two neighbouring lines, on purpose. `last_candle_ts` keeps
        # the candle's OPEN time, because that is the OHLCV convention and both
        # readers of it — humanize.bot_status and config_store.live_drift — add the
        # timeframe back themselves. Everything the engine *does* is stamped with
        # the CLOSE, because a candle only reaches this method once it has closed
        # and that is when the decision is taken. Stamping decisions with the open
        # backdated the whole event journal by a full timeframe: on 4h bars the
        # trades from the candle that closed at 22:00 were filed under 18:00, so
        # the newest candle read as missing.
        self.last_candle_ts[symbol] = bar["timestamp"].isoformat()
        now: datetime = bar["timestamp"].to_pydatetime() + self._bar_delta

        self._maybe_reload_models()
        self._maybe_reload_config(now)
        self._manage_position(symbol, bar, now)
        self._maybe_enter(symbol, buf, bar, now)

        self.store.append_equity({"timestamp": now.isoformat(), "symbol": symbol,
                                  "close": float(bar["close"]), "equity": self.equity(),
                                  "cash": self.cash})
        self._check_risk_alerts(now)
        self.persist(now)

    def _check_risk_alerts(self, now: datetime) -> None:
        if self.risk.kill_switch_active(now, self.equity()):
            if not self._kill_alerted:
                self.alert("kill_switch", "alert.kill_switch", {}, now)
                self._kill_alerted = True
        else:
            self._kill_alerted = False
        dd = self.drawdown_pct()
        if dd <= -self.cfg.risk.drawdown_alert_pct * 100.0:
            if not self._dd_alerted:
                self.alert("drawdown", "alert.drawdown", {"dd": f"{dd:.1f}"}, now)
                self._dd_alerted = True
        elif dd > -self.cfg.risk.drawdown_alert_pct * 50.0:
            self._dd_alerted = False

    def _manage_position(self, symbol: str, bar: dict, now: datetime) -> None:
        pos = self.positions.get(symbol)
        if pos is None:
            return
        reason = check_bracket_exit(bar["high"], bar["low"], pos.tp, pos.sl, pos.side)
        price_hint = None
        if reason == "tp":
            price_hint = pos.tp
        elif reason == "sl":
            price_hint = pos.sl
        elif now >= pos.deadline:
            reason, price_hint = "timeout", float(bar["close"])
        if price_hint is None:
            return
        # Only a timeout may roll over, and the reason is subtle enough to be worth
        # stating: it is the one exit this engine actually decides at the close.
        # TP and SL are detected from the bar's high/low — an intra-bar touch — and
        # filled at the barrier, which models an order that already went through
        # before the bar ended. Declining that fill after seeing where the bar
        # closed would be reading the future, and it measures like it: extending
        # take-profits this way scored +146.6% -> +182.8% mean return across
        # 5.5 years and ten pairs, thirty times the honest timeout-only effect.
        # A stop-loss would not qualify anyway — extending it abandons the risk
        # limit rather than saving a fee.
        if reason == "timeout" and self._maybe_rollover(symbol, pos, bar, now,
                                                        price_hint, reason):
            return

        if pos.side == "long":
            fill = self.executor.market_sell(symbol, pos.qty, price_hint)
        else:
            fill = self.executor.market_buy(symbol, pos.qty, price_hint)
        pnl = pos.sign * pos.qty * (fill.price - pos.entry_price) - pos.entry_fees - fill.fee
        self.cash += pos.margin + pos.sign * pos.qty * (fill.price - pos.entry_price) - fill.fee
        del self.positions[symbol]
        self.risk.record_realized_pnl(pnl, now, self.equity())
        self.store.append_trade({
            "mode": self.cfg.mode, "symbol": symbol, "side": pos.side,
            "entry_time": pos.entry_time.isoformat(), "exit_time": now.isoformat(),
            "qty": pos.qty, "entry_price": pos.entry_price, "exit_price": fill.price,
            "exit_reason": reason, "fees": pos.entry_fees + fill.fee, "pnl": pnl,
            # see the note in backtest/book.py's close_position. On live books this
            # is the version that will eventually answer the question on real
            # trades rather than on a backtest.
            "prob": pos.entry_prob,
        })
        log.info("[%s] %s: closed %s %s pnl=%.4f", self.name, symbol, pos.side, reason, pnl)
        self.alert("trade_close", "alert.trade_close",
                   {"symbol": symbol, "side": pos.side, "reason": reason,
                    "pnl": f"{pnl:+.2f}"},
                   now, symbol=symbol, pnl=pnl, reason=reason)

    def _round_trip_cost(self, price: float) -> float:
        """What closing here and reopening on this same bar costs, in price units."""
        costs = self.cfg.costs
        return 2.0 * (costs.taker_fee + costs.slippage) * price

    def _maybe_rollover(self, symbol: str, pos: Position, bar: dict, now: datetime,
                        exit_price: float, reason: str) -> bool:
        """Extend a position instead of closing it, when the close would only be
        undone by an immediate re-entry that costs more than it gains.

        The engine exits at `exit_price` and re-enters at this bar's close, and it
        knows both numbers at the moment it decides — so the comparison is a
        measurement, not a forecast. Exiting is worth its two fills only when it
        banks more than they cost:

            edge = sign * (exit_price - close)   # what leaving here is worth
            roll over  ⟺  edge <= round-trip cost

        The rule reads the same for both exits it covers. A timeout fills at the
        bar close, so `edge` is exactly zero and it always extends — the behaviour
        this method already had. A take-profit fills at the target, so it depends
        on where the bar ended: closing above the target (the case that prompted
        this — SOL sold at 76.11 and bought back at 76.42, 0.63 USDT down) leaves a
        negative edge and extends, while a bar that fell back below the target
        leaves a positive one and the profit is taken, because there the round trip
        really does buy back cheaper than it sold.

        On a kill-switch day the position still closes: the reopen this stands in
        for would have been blocked too.
        """
        strat = self.cfg.strategy
        if not strat.rollover:
            return False
        if self.risk.kill_switch_active(now, self.equity()):
            return False
        close = float(bar["close"])
        if pos.sign * (exit_price - close) > self._round_trip_cost(close):
            return False   # the round trip pays for itself — take it
        view, _ = self._model_view(self.buffers.get(symbol, pd.DataFrame()))
        if view is None:
            return False
        prob = view["p_long"] if pos.side == "long" else view["p_short"]
        if prob is None or prob < strat.prob_threshold:
            return False
        pos.tp = close + pos.sign * strat.tp_atr_mult * view["atr"]
        pos.sl = close - pos.sign * strat.sl_atr_mult * view["atr"]
        pos.deadline = now + self._bar_delta * strat.horizon_bars
        log.info("[%s] %s: rolled over %s instead of %s (p=%.3f)",
                 self.name, symbol, pos.side, reason, prob)
        self.alert("trade_rollover", "alert.trade_rollover",
                   {"symbol": symbol, "side": pos.side, "price": f"{close:.2f}",
                    "prob": f"{prob:.2f}", "reason": reason},
                   now, symbol=symbol, side=pos.side, prob=prob, reason=reason)
        return True

    def _record_signal(self, symbol: str, reason: str, **extra) -> None:
        self.signals[symbol] = {"reason": reason,
                                "threshold": self.cfg.strategy.prob_threshold, **extra}

    def _model_view(self, buf: pd.DataFrame) -> tuple[dict | None, str]:
        """The models' opinion of the last closed bar: probabilities and ATR,
        or (None, why-not) while the features cannot be computed yet."""
        strat = self.cfg.strategy
        if len(buf) < strat.warmup_bars:
            return None, "warmup"
        features = compute_features(buf, strat.atr_period)
        last = features.iloc[[-1]]
        if last[self.bundles["long"].feature_columns].isna().any(axis=1).iloc[0]:
            return None, "features_nan"
        atr_now = float(compute_atr(buf, strat.atr_period).iloc[-1])
        if not atr_now > 0:
            return None, "no_atr"
        p_long = float(self.bundles["long"].predict_proba(last)[0])
        allow_short = strat.direction == "long_short" and "short" in self.bundles
        p_short = float(self.bundles["short"].predict_proba(last)[0]) if allow_short else None
        return {"p_long": p_long, "p_short": p_short, "atr": atr_now}, "ok"

    def _maybe_enter(self, symbol: str, buf: pd.DataFrame, bar: dict, now: datetime) -> None:
        strat = self.cfg.strategy
        if symbol in self.positions:
            self._record_signal(symbol, "in_position")
            return
        if len(buf) < strat.warmup_bars:
            self._record_signal(symbol, "warmup")
            return
        # The risk check comes after the model, not before it, even though checking
        # a counter is cheaper than a prediction. Asking the model first is what lets
        # the panel say what the limit actually cost: with the old order a pair that
        # was blocked had no probability to show, so "wstrzymany limitem ryzyka"
        # appeared next to an empty p(long) and could equally have meant a 0.92
        # opportunity turned away or a 0.31 non-event. It also stops the reason from
        # lying — a full book used to be reported as the cause even for pairs that
        # were nowhere near the threshold and would not have opened anyway.
        # No trade changes: `can_open` still gates every entry, one call later.
        view, why = self._model_view(buf)
        if view is None:
            self._record_signal(symbol, why)
            return
        p_long, p_short, atr_now = view["p_long"], view["p_short"], view["atr"]
        allow_short = p_short is not None
        side, prob = None, strat.prob_threshold
        if p_long >= prob:
            side, prob = "long", p_long
        if allow_short and p_short is not None and p_short > prob:
            side, prob = "short", p_short
        if side is None:
            self._record_signal(symbol, "below_threshold", p_long=p_long, p_short=p_short)
            return

        ok, why = self.risk.can_open(len(self.positions), self.equity(), now)
        if not ok:
            self._record_signal(symbol, "risk_blocked", detail=why, side=side,
                                p_long=p_long, p_short=p_short)
            return
        self._record_signal(symbol, f"enter_{side}", p_long=p_long, p_short=p_short)

        price_hint = float(bar["close"])
        qty = self.risk.position_qty(self.equity(), price_hint)
        if side == "long":
            fill = self.executor.market_buy(symbol, qty, price_hint)
        else:
            fill = self.executor.market_sell(symbol, qty, price_hint)
        cost = fill.notional + fill.fee
        if cost > self.cash:
            log.warning("[%s] %s: insufficient cash (%.2f > %.2f)",
                        self.name, symbol, cost, self.cash)
            return
        self.cash -= cost
        sign = 1 if side == "long" else -1
        self.positions[symbol] = Position(
            symbol=symbol, qty=qty, entry_price=fill.price, entry_fees=fill.fee,
            tp=fill.price + sign * strat.tp_atr_mult * atr_now,
            sl=fill.price - sign * strat.sl_atr_mult * atr_now,
            entry_time=now, deadline=now + self._bar_delta * strat.horizon_bars,
            side=side, margin=fill.notional, entry_prob=prob,
        )
        log.info("[%s] %s: opened %s qty=%.6f @ %.2f (p=%.3f)",
                 self.name, symbol, side, qty, fill.price, prob)
        self.alert("trade_open", "alert.trade_open",
                   {"symbol": symbol, "side": side, "price": f"{fill.price:.2f}",
                    "prob": f"{prob:.2f}"},
                   now, symbol=symbol, side=side, prob=prob)


def build_books(cfg: Config, bundles, executor) -> list[Book]:
    """One book per configured variant, or a single 'default' book."""
    if not cfg.variants:
        return [Book("default", cfg, bundles, executor, RuntimeStore(cfg.paths.runtime_dir))]
    books = []
    for v in cfg.variants:
        vcfg = cfg.for_variant(v)
        store = RuntimeStore(cfg.paths.runtime_dir / v.name)
        books.append(Book(v.name, vcfg, bundles, executor, store))
    return books


class TradingEngine:
    """Thin async layer: stream candles once, dispatch to every book."""

    def __init__(self, cfg: Config, bundles, executor: Executor, books: list[Book] | None = None):
        self.cfg = cfg
        self.books = books if books is not None else build_books(cfg, bundles, executor)
        self.buffer_len = max(b._buffer_len for b in self.books)

    def dispatch(self, symbol: str, bar: dict) -> None:
        for book in self.books:
            book.on_candle(symbol, bar)

    async def _bootstrap(self, rest_exchange) -> dict[str, pd.Timestamp | None]:
        last_seen: dict[str, pd.Timestamp | None] = {}
        for symbol in self.cfg.exchange.symbols:
            raw = await rest_exchange.fetch_ohlcv(
                symbol, self.cfg.exchange.timeframe, limit=self.buffer_len)
            df = storage.to_dataframe(raw[:-1])  # drop the still-open candle
            for book in self.books:
                book.seed_buffer(symbol, df.copy())
            last_seen[symbol] = df["timestamp"].iloc[-1] if len(df) else None
            log.info("%s: preloaded %d candles", symbol, len(df))
        return last_seen

    def _alert_books(self, kind: str, msg_key: str, params: dict, **extra) -> None:
        """Tell every book the same thing. Per book rather than to the shared journal
        because the beginner screen reads only the primary book's events, and a book
        whose journal never mentions an outage reads as a book that had nothing to say."""
        now = datetime.now(UTC)
        for book in self.books:
            book.alert(kind, msg_key, params, now, **extra)

    def _clear_connection_alert(self) -> None:
        """Close an outage the journal still has open — including one opened by a
        previous process.

        Without this the newest line in the event log stays "no contact with the
        exchange" until something unrelated happens, and on 4h candles that can be
        hours away. The reader is then left to infer from silence whether the bot
        recovered or is still down — and silence looks far more like the latter.
        A container restart makes it worse, because the process that would have
        written the all-clear no longer exists.

        `ok` is what makes an outage closeable: two alerts of the same kind, one
        opening the state and one ending it, instead of a message a human has to
        interpret.
        """
        now = datetime.now(UTC)
        for book in self.books:
            last = book.store.last_alert("connection")
            if last is not None and not last.get("ok", True):
                book.alert("connection", "alert.connection.back", {}, now, ok=True)

    async def _bootstrap_with_retry(self, rest_exchange) -> dict[str, pd.Timestamp | None]:
        """Preload candles, waiting the network out instead of dying on it.

        Retrying here rather than letting the process exit is the difference between
        an engine that is quiet for an hour and a container that restarts 826 times in
        five hours: `restart: unless-stopped` brings the process straight back into
        the same failed lookup, with no backoff and no memory of having tried.

        Never gives up on purpose — there is nothing a caller could do that this loop
        is not already doing, and a 4h bot loses nothing by waiting. A partial attempt
        is safe to repeat: seed_buffer overwrites per symbol, so a failure on the
        seventh pair simply re-seeds the first six on the next pass. The exchange
        object is reused across attempts because ccxt caches markets only on success,
        and a fresh one would leak an aiohttp session per try.
        """
        delay, fails = RETRY_SECONDS, 0
        while True:
            try:
                last_seen = await self._bootstrap(rest_exchange)
            except Exception:   # not BaseException: CancelledError must still pass
                fails += 1
                if fails == 1:
                    log.exception("startup: could not reach the exchange, retrying")
                else:
                    # One traceback names the cause; 826 copies of it name nothing.
                    log.warning("startup: exchange still unreachable (attempt %d), "
                                "retrying in %.0fs", fails, delay)
                if fails == CONNECTION_ALERT_AFTER:
                    self._alert_books("connection", "alert.connection.lost", {}, ok=False)
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_SECONDS)
                continue
            # Unconditional, not `if fails`: the outage worth closing is usually the
            # one a previous container opened, and this process never saw it.
            self._clear_connection_alert()
            return last_seen

    async def _poll_feed(self, rest_exchange, symbol: str, last_seen) -> None:
        timeframe = self.cfg.exchange.timeframe
        fails = 0
        while True:
            try:
                raw = await rest_exchange.fetch_ohlcv(symbol, timeframe, limit=3)
                for _, row in storage.to_dataframe(raw[:-1]).iterrows():
                    if last_seen[symbol] is None or row["timestamp"] > last_seen[symbol]:
                        last_seen[symbol] = row["timestamp"]
                        self.dispatch(symbol, row.to_dict())
                fails = 0
            except Exception:
                fails += 1
                if fails == 1:
                    log.exception("%s: poll feed error, retrying", symbol)
                else:
                    log.warning("%s: poll feed still failing (%d in a row)", symbol, fails)
            # Backing off matters more than it looks: ten pairs polling every 5s
            # through an outage is 7200 failures an hour into an unrotated log.
            await asyncio.sleep(POLL_SECONDS if not fails else
                                min(POLL_SECONDS * 2 ** fails, MAX_RETRY_SECONDS))

    async def _ws_feed(self, ws_exchange, symbol: str) -> None:
        timeframe = self.cfg.exchange.timeframe
        current_ts = current_bar = None
        while True:
            for c in await ws_exchange.watch_ohlcv(symbol, timeframe):
                ts = pd.Timestamp(c[0], unit="ms", tz="UTC")
                bar = {"timestamp": ts, "open": float(c[1]), "high": float(c[2]),
                       "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
                if current_ts is not None and ts > current_ts:
                    self.dispatch(symbol, current_bar)  # previous candle closed
                current_ts, current_bar = ts, bar

    async def _ws_feed_with_fallback(self, ws_exchange, rest_exchange, symbol, last_seen) -> None:
        try:
            await self._ws_feed(ws_exchange, symbol)
        except Exception:
            log.exception("%s: WebSocket feed failed, falling back to REST polling", symbol)
            await self._poll_feed(rest_exchange, symbol, last_seen)

    async def _restart_watcher(self) -> None:
        """Exit cleanly when the dashboard asks for a restart.

        Structural config (symbols, timeframe, the variant list) is read once at
        startup, so the only honest way to change it is to come back up. The
        dashboard has no Docker socket — it writes a flag, and this decides when to
        go down. run()'s finally block persists every book first, Book.restore()
        reads cash and open positions back, and `restart: unless-stopped` supplies
        the actual restart.
        """
        started = datetime.now(UTC)
        runtime_dir = self.cfg.paths.runtime_dir
        while True:
            await asyncio.sleep(RESTART_POLL_SECONDS)
            requested = restart_requested_at(runtime_dir)
            if requested is not None and requested > started:
                log.info("restart requested at %s — persisting books and exiting", requested)
                raise RestartRequested

    async def _ticker_loop(self, rest_exchange) -> None:
        """Mark-to-market valuation for the dashboard; never trades."""
        symbols = self.cfg.exchange.symbols
        fails = 0
        while True:
            await asyncio.sleep(TICKER_SECONDS)
            try:
                tickers = await rest_exchange.fetch_tickers(symbols)
                prices = {s: float(t["last"]) for s, t in tickers.items()
                          if s in symbols and t.get("last")}
                now = datetime.now(UTC)
                for book in self.books:
                    book.mark_to_market(prices, now)
            except Exception:
                if not fails:
                    log.exception("ticker refresh failed, retrying")
                else:
                    log.warning("ticker refresh still failing (%d in a row)", fails + 1)
                fails += 1
            else:
                fails = 0

    async def run(self) -> None:
        import ccxt.async_support as ccxt_async

        rest_exchange = getattr(ccxt_async, self.cfg.exchange.id)({"enableRateLimit": True})
        ws_exchange = None
        try:
            import ccxt.pro as ccxtpro
            ws_exchange = getattr(ccxtpro, self.cfg.exchange.id)({"enableRateLimit": True})
        except (ImportError, AttributeError):
            log.warning("ccxt.pro unavailable, using REST polling only")

        try:
            for book in self.books:
                book.restore()
            last_seen = await self._bootstrap_with_retry(rest_exchange)
            now = datetime.now(UTC)
            for book in self.books:
                book.persist(now)
            coros = []
            for symbol in self.cfg.exchange.symbols:
                if ws_exchange is not None:
                    coros.append(self._ws_feed_with_fallback(
                        ws_exchange, rest_exchange, symbol, last_seen))
                else:
                    coros.append(self._poll_feed(rest_exchange, symbol, last_seen))
            coros.append(self._ticker_loop(rest_exchange))
            coros.append(self._restart_watcher())
            log.info("engine running in %s mode: %d book(s) on %s",
                     self.cfg.mode, len(self.books), self.cfg.exchange.symbols)
            # gather() propagates the first exception but leaves the siblings running,
            # so cancel them explicitly — otherwise a restart request would persist
            # state while the feeds kept trading underneath it.
            tasks = [asyncio.create_task(c) for c in coros]
            try:
                await asyncio.gather(*tasks)
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                # Persist here rather than in the outer finally: this is the only
                # branch where a book can differ from what restore() read. A startup
                # that never got past the preload has nothing to save, and saving
                # anyway stamps a fresh updated_at on a state nobody refreshed — the
                # panel reads that field as "the engine knew this much at this
                # moment". It also means a state.json too corrupt to parse is no
                # longer overwritten with a virgin 1000 USDT book.
                for book in self.books:
                    book.persist(datetime.now(UTC))
        finally:
            await rest_exchange.close()
            if ws_exchange is not None:
                await ws_exchange.close()
