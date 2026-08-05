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
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd

from trademon.config import Config, config_path, load_config, overrides_path
from trademon.config_store import restart_requested_at
from trademon.data import storage
from trademon.engine.notify import send_webhook
from trademon.engine.state import RuntimeStore
from trademon.execution.executors import Executor
from trademon.execution.fills import check_bracket_exit
from trademon.features.engineering import compute_atr, compute_features
from trademon.models.train import ModelBundle, load_bundles
from trademon.risk.manager import RiskManager

log = logging.getLogger(__name__)

POLL_SECONDS = 5.0
TICKER_SECONDS = 60.0
RESTART_POLL_SECONDS = 10.0

# Config fields a running book can adopt on its next candle, because they are read
# fresh out of self.cfg inside _maybe_enter / _manage_position. Everything else
# (symbols, timeframe, warmup, the variant list) is baked into __init__ or the feed
# and needs the restart handshake instead — see config_store.RESTART_FIELDS.
HOT_STRATEGY_FIELDS = ("prob_threshold", "tp_atr_mult", "sl_atr_mult",
                       "horizon_bars", "atr_period", "direction")
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
        self._overrides_path = overrides_path(config_path())
        self._overrides_mtime = self._current_overrides_mtime()

    # ---------- models ----------

    def _current_model_mtime(self) -> float:
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

    def _current_overrides_mtime(self) -> float:
        return self._overrides_path.stat().st_mtime if self._overrides_path.exists() else 0.0

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
        """Adopt hot config fields written by the dashboard. Mirrors the model
        hot-reload above: watch an mtime, reload, never let a bad file stop trading."""
        mtime = self._current_overrides_mtime()
        if mtime <= self._overrides_mtime:
            return
        self._overrides_mtime = mtime
        try:
            fresh = self._fresh_variant_config()
        except Exception:
            log.exception("[%s] config reload failed, keeping current config", self.name)
            return
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
        self.alert("config", "zmieniono ustawienia: " + ", ".join(changes), now)

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

    def alert(self, kind: str, message: str, now: datetime, **extra) -> None:
        self.store.append_alert({"timestamp": now.isoformat(), "kind": kind,
                                 "message": message, "variant": self.name, **extra})
        log.info("[%s] ALERT [%s] %s", self.name, kind, message)
        send_webhook(self.cfg.alert_webhook_url, f"[{self.name}][{kind}] {message}")

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
        log.info("[%s] restored: cash=%.2f, open positions: %s",
                 self.name, self.cash, list(self.positions) or "none")

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
            "kill_switch": self.risk.kill_switch_active(now, eq),
        })

    def seed_buffer(self, symbol: str, df: pd.DataFrame) -> None:
        self.buffers[symbol] = df
        if len(df):
            self.last_close[symbol] = float(df["close"].iloc[-1])

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
        self.last_candle_ts[symbol] = bar["timestamp"].isoformat()
        now: datetime = bar["timestamp"].to_pydatetime()

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
                self.alert("kill_switch", "dzienny limit straty osiągnięty — "
                           "nowe wejścia zablokowane", now)
                self._kill_alerted = True
        else:
            self._kill_alerted = False
        dd = self.drawdown_pct()
        if dd <= -self.cfg.risk.drawdown_alert_pct * 100.0:
            if not self._dd_alerted:
                self.alert("drawdown", f"obsunięcie {dd:.1f}% od szczytu kapitału", now)
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
        })
        log.info("[%s] %s: closed %s %s pnl=%.4f", self.name, symbol, pos.side, reason, pnl)
        self.alert("trade_close", f"{symbol} zamknięto {pos.side} ({reason}) "
                   f"PnL {pnl:+.2f} USDT", now, symbol=symbol, pnl=pnl, reason=reason)

    def _record_signal(self, symbol: str, reason: str, **extra) -> None:
        self.signals[symbol] = {"reason": reason,
                                "threshold": self.cfg.strategy.prob_threshold, **extra}

    def _maybe_enter(self, symbol: str, buf: pd.DataFrame, bar: dict, now: datetime) -> None:
        strat = self.cfg.strategy
        if symbol in self.positions:
            self._record_signal(symbol, "in_position")
            return
        if len(buf) < strat.warmup_bars:
            self._record_signal(symbol, "warmup")
            return
        ok, why = self.risk.can_open(len(self.positions), self.equity(), now)
        if not ok:
            self._record_signal(symbol, "risk_blocked", detail=why)
            return

        features = compute_features(buf, strat.atr_period)
        last = features.iloc[[-1]]
        if last[self.bundles["long"].feature_columns].isna().any(axis=1).iloc[0]:
            self._record_signal(symbol, "features_nan")
            return
        atr_now = float(compute_atr(buf, strat.atr_period).iloc[-1])
        if not atr_now > 0:
            self._record_signal(symbol, "no_atr")
            return

        p_long = float(self.bundles["long"].predict_proba(last)[0])
        allow_short = strat.direction == "long_short" and "short" in self.bundles
        p_short = float(self.bundles["short"].predict_proba(last)[0]) if allow_short else None
        side, prob = None, strat.prob_threshold
        if p_long >= prob:
            side, prob = "long", p_long
        if allow_short and p_short is not None and p_short > prob:
            side, prob = "short", p_short
        if side is None:
            self._record_signal(symbol, "below_threshold", p_long=p_long, p_short=p_short)
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
            side=side, margin=fill.notional,
        )
        log.info("[%s] %s: opened %s qty=%.6f @ %.2f (p=%.3f)",
                 self.name, symbol, side, qty, fill.price, prob)
        self.alert("trade_open", f"{symbol} otwarto {side} @ {fill.price:.2f} (p={prob:.2f})",
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

    async def _poll_feed(self, rest_exchange, symbol: str, last_seen) -> None:
        timeframe = self.cfg.exchange.timeframe
        while True:
            try:
                raw = await rest_exchange.fetch_ohlcv(symbol, timeframe, limit=3)
                for _, row in storage.to_dataframe(raw[:-1]).iterrows():
                    if last_seen[symbol] is None or row["timestamp"] > last_seen[symbol]:
                        last_seen[symbol] = row["timestamp"]
                        self.dispatch(symbol, row.to_dict())
            except Exception:
                log.exception("%s: poll feed error, retrying", symbol)
            await asyncio.sleep(POLL_SECONDS)

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
                log.exception("ticker refresh failed, retrying")

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
            last_seen = await self._bootstrap(rest_exchange)
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
        finally:
            for book in self.books:
                book.persist(datetime.now(UTC))
            await rest_exchange.close()
            if ws_exchange is not None:
                await ws_exchange.close()
