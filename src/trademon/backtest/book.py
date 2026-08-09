"""Backtest of the whole book, not of one pair at a time.

[`runner.run_backtest`](runner.py) answers "how would this pair have traded on its
own account". It is the right question for judging a model, and the promotion gate
in scripts/refresh.py asks it. It is the wrong question for judging a *universe*:
every pair there gets its own capital and its own unlimited slots, so widening the
board can only ever add returns to the average. The live engine has one wallet and
`risk.max_open_positions` slots that the pairs compete for.

This module runs the competition. One cash balance, one RiskManager (the same class
the engine uses, so the cap and the daily kill-switch are not re-implemented here),
and an explicit rule for who gets a free slot when more pairs signal than there are
slots:

* `fcfs` — the order the pairs appear in `cfg.exchange.symbols`. This is what the
  engine does today, because it checks the cap before it computes a probability,
  so the slot goes to whichever candle was dispatched first.
* `best_first` — highest model probability wins.

Two deliberate differences from `runner.py`, both in the direction of the engine,
because the engine is what this is a model of:

* position size is `equity * position_pct`, not `cash * position_pct`. On a
  single-position book the two agree; on a shared wallet the cash version quietly
  shrinks every position after the first one.
* `maker` execution is not supported. The resting-limit path has per-symbol pending
  state that interacts with slot allocation (does an unfilled limit hold a slot?)
  and there is no answer in the engine to copy, because the engine trades taker.

Everything else — the fill model, the barrier logic, the rollover cost test — is
the same code or the same rule as the per-symbol backtest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np
import pandas as pd

from trademon.backtest.metrics import periods_per_year, summarize
from trademon.config import Config
from trademon.data import storage
from trademon.execution.fills import buy_fill, check_bracket_exit, sell_fill
from trademon.features.engineering import compute_atr, compute_features
from trademon.models.train import ModelBundle
from trademon.risk.manager import RiskManager

log = logging.getLogger(__name__)

Allocation = Literal["fcfs", "best_first"]


@dataclass
class _Series:
    """Everything the loop needs about one pair, precomputed once."""

    index: dict[pd.Timestamp, int]
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    atr: np.ndarray
    p_long: np.ndarray
    p_short: np.ndarray
    n: int


@dataclass
class _Position:
    symbol: str
    qty: float
    side: int  # +1 long, -1 short
    entry_price: float
    entry_fees: float
    tp: float
    sl: float
    margin: float
    deadline_i: int  # index in *this pair's* frame, mirroring runner.py
    entry_ts: pd.Timestamp


def _prepare(
    df: pd.DataFrame, bundles: dict[str, ModelBundle], cfg: Config, allow_short: bool
) -> _Series:
    """Features and probabilities for one pair, vectorised ahead of the loop.

    Doing this per bar inside the joint loop would re-fit the feature frame once per
    pair per bar — eighteen pairs over 12000 bars is 216000 calls, and the loop is
    already the slow part."""
    strat = cfg.strategy
    features = compute_features(df, strat.atr_period)
    atr = compute_atr(df, strat.atr_period).to_numpy(float)
    cols = bundles["long"].feature_columns
    valid = features[cols].notna().all(axis=1).to_numpy()
    p_long = np.full(len(df), np.nan)
    p_short = np.full(len(df), np.nan)
    if valid.any():
        p_long[valid] = bundles["long"].predict_proba(features[valid])
        if allow_short:
            p_short[valid] = bundles["short"].predict_proba(features[valid])
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return _Series(
        index={t: i for i, t in enumerate(ts)},
        ts=ts.to_numpy(),
        open=df["open"].to_numpy(float),
        high=df["high"].to_numpy(float),
        low=df["low"].to_numpy(float),
        close=df["close"].to_numpy(float),
        atr=atr,
        p_long=p_long,
        p_short=p_short,
        n=len(df),
    )


def _signal(s: _Series, i: int, threshold: float, allow_short: bool) -> tuple[int, float]:
    """(+1/-1/0, probability) for this pair on bar i — the stronger side wins,
    matching runner.py:204-207 and the engine's _maybe_enter."""
    side, best = 0, threshold
    if not np.isnan(s.p_long[i]) and s.p_long[i] >= best:
        side, best = 1, float(s.p_long[i])
    if allow_short and not np.isnan(s.p_short[i]) and s.p_short[i] > best:
        side, best = -1, float(s.p_short[i])
    return side, best


def run_book_backtest(
    frames: dict[str, pd.DataFrame],
    bundles: dict[str, ModelBundle] | ModelBundle,
    cfg: Config,
    allocation: Allocation = "best_first",
    trade_from: pd.Timestamp | None = None,
    cache: dict[str, _Series] | None = None,
) -> dict:
    """Trade every pair in `frames` out of one wallet, under one position cap.

    `trade_from`: bars before it feed feature computation but may not open a
    position, so a short test window can carry the warmup history it needs — the
    same contract as runner.py's integer `trade_from`, expressed as a timestamp
    because the pairs do not share a row index.

    `cache`: pass the same dict across a grid of runs. Features and probabilities
    depend only on the frames and the model, never on the cap or the allocation
    rule, so a 2x2x2 grid would otherwise recompute them eight times.
    """
    if cfg.execution.order_style == "maker":
        raise NotImplementedError(
            "book backtest is taker-only; see the module docstring for why"
        )
    if not isinstance(bundles, dict):
        bundles = {"long": bundles}
    strat, costs = cfg.strategy, cfg.costs
    allow_short = strat.direction == "long_short" and "short" in bundles

    # Config order decides fcfs, and breaks ties under best_first — so the order the
    # pairs are iterated in has to be the configured one, not the dict's.
    symbols = [s for s in cfg.exchange.symbols if s in frames] + [
        s for s in frames if s not in cfg.exchange.symbols
    ]
    rank = {s: i for i, s in enumerate(symbols)}
    if cache is None:
        cache = {}
    for s in symbols:
        if s not in cache:
            cache[s] = _prepare(frames[s], bundles, cfg, allow_short)
    series = {s: cache[s] for s in symbols}

    timeline = sorted({t for s in series.values() for t in s.index})
    if trade_from is not None:
        trade_from = pd.Timestamp(trade_from).tz_convert("UTC")

    bar_delta = timedelta(milliseconds=storage.TIMEFRAME_MS[cfg.exchange.timeframe])
    initial = cfg.paper.initial_capital
    cash = initial
    risk = RiskManager(cfg.risk)
    positions: dict[str, _Position] = {}
    last_close: dict[str, float] = {}
    trades: list[dict] = []
    equity_curve: list[float] = []
    cash_curve: list[float] = []
    curve_index: list[pd.Timestamp] = []
    n_signals = n_fills = n_rollovers = 0
    n_slot_blocked = n_kill_blocked = n_cash_blocked = 0
    max_concurrent = 0

    def equity() -> float:
        total = cash
        for p in positions.values():
            total += p.margin + p.side * p.qty * (last_close[p.symbol] - p.entry_price)
        return total

    def close_position(p: _Position, price: float, reason: str, now: pd.Timestamp) -> None:
        nonlocal cash
        fill = (sell_fill if p.side == 1 else buy_fill)(price, p.qty, costs)
        pnl = p.side * p.qty * (fill.price - p.entry_price) - p.entry_fees - fill.fee
        cash += p.margin + p.side * p.qty * (fill.price - p.entry_price) - fill.fee
        del positions[p.symbol]
        trades.append({
            "symbol": p.symbol, "side": "long" if p.side == 1 else "short",
            "entry_time": p.entry_ts, "exit_time": now, "qty": p.qty,
            "entry_price": p.entry_price, "exit_price": fill.price,
            "exit_reason": reason, "fees": p.entry_fees + fill.fee, "pnl": pnl,
        })
        risk.record_realized_pnl(pnl, now.to_pydatetime(), equity())

    for t in timeline:
        now = t + bar_delta  # decisions are stamped with the close, like the engine
        now_dt: datetime = now.to_pydatetime()

        # Refresh marks first, so equity() is right for everything that follows.
        for symbol, s in series.items():
            i = s.index.get(t)
            if i is not None:
                last_close[symbol] = float(s.close[i])

        # 1) manage open positions. Exits never compete for anything, so they all
        #    happen before any entry — and a slot freed here is available below.
        for symbol in list(positions):
            s = series[symbol]
            i = s.index.get(t)
            if i is None:
                continue  # this pair has no bar at t; the position simply carries
            p = positions[symbol]
            direction = "long" if p.side == 1 else "short"
            reason = check_bracket_exit(s.high[i], s.low[i], p.tp, p.sl, direction)
            exit_price = None
            if reason == "tp":
                exit_price = p.tp
            elif reason == "sl":
                exit_price = p.sl
            elif i >= p.deadline_i:
                reason, exit_price = "timeout", float(s.close[i])
            if exit_price is None:
                continue
            # Rollover, same cost test as runner.py:137-148 and the engine's
            # _maybe_rollover: extend only when leaving does not pay for the two
            # fills it costs. Only a timeout qualifies — a TP/SL is an intra-bar
            # touch already filled, and declining it after seeing the close reads
            # the future.
            close_px = float(s.close[i])
            if reason == "timeout" and strat.rollover:
                p_now = s.p_long[i] if p.side == 1 else s.p_short[i]
                round_trip = 2.0 * (costs.taker_fee + costs.slippage) * close_px
                edge = p.side * (exit_price - close_px)
                if (edge <= round_trip and not np.isnan(p_now)
                        and p_now >= strat.prob_threshold and s.atr[i] > 0):
                    p.tp = close_px + p.side * strat.tp_atr_mult * s.atr[i]
                    p.sl = close_px - p.side * strat.sl_atr_mult * s.atr[i]
                    p.deadline_i = i + int(strat.horizon_bars)
                    n_rollovers += 1
                    exit_price = None
            if exit_price is not None:
                close_position(p, exit_price, reason, now)

        # 2) who wants a slot on this bar
        candidates: list[tuple[str, int, float, int]] = []  # symbol, side, prob, i
        for symbol in symbols:
            if symbol in positions:
                continue
            s = series[symbol]
            i = s.index.get(t)
            if i is None or i + 1 >= s.n or not s.atr[i] > 0:
                continue
            if trade_from is not None and t < trade_from:
                continue
            side, prob = _signal(s, i, strat.prob_threshold, allow_short)
            if side != 0:
                candidates.append((symbol, side, prob, i))
        n_signals += len(candidates)

        # 3) hand out the free slots
        if allocation == "best_first":
            candidates.sort(key=lambda c: (-c[2], rank[c[0]]))
        else:
            candidates.sort(key=lambda c: rank[c[0]])
        for symbol, side, prob, i in candidates:
            ok, why = risk.can_open(len(positions), equity(), now_dt)
            if not ok:
                if why.startswith("kill-switch"):
                    n_kill_blocked += 1
                else:
                    n_slot_blocked += 1
                continue
            s = series[symbol]
            price = float(s.open[i + 1])
            qty = risk.position_qty(equity(), price)
            fill = (buy_fill if side == 1 else sell_fill)(price, qty, costs)
            if fill.notional + fill.fee > cash:
                n_cash_blocked += 1
                continue
            cash -= fill.notional + fill.fee
            positions[symbol] = _Position(
                symbol=symbol, qty=fill.notional / fill.price, side=side,
                entry_price=fill.price, entry_fees=fill.fee,
                tp=fill.price + side * strat.tp_atr_mult * s.atr[i],
                sl=fill.price - side * strat.sl_atr_mult * s.atr[i],
                margin=fill.notional, deadline_i=i + 1 + int(strat.horizon_bars),
                # the signal is bar i, the fill is bar i+1 — stamp the fill, the
                # same way runner.py does, or the journal backdates every entry
                entry_ts=pd.Timestamp(s.ts[i + 1]),
            )
            n_fills += 1
            max_concurrent = max(max_concurrent, len(positions))

        if trade_from is None or t >= trade_from:
            curve_index.append(t)
            equity_curve.append(equity())
            cash_curve.append(cash)

    trades_df = pd.DataFrame(trades)
    equity_s = pd.Series(equity_curve, index=pd.DatetimeIndex(curve_index, name="timestamp"))
    cash_s = pd.Series(cash_curve, index=equity_s.index)
    result = summarize(trades_df, equity_s, initial,
                       periods_per_year(cfg.exchange.timeframe), cash=cash_s)
    result["allocation"] = allocation
    result["symbols"] = symbols
    result["n_symbols"] = len(symbols)
    result["max_open_positions"] = cfg.risk.max_open_positions
    result["prob_threshold"] = strat.prob_threshold
    result["period"] = {
        "start": str(curve_index[0]) if curve_index else "",
        "end": str(curve_index[-1]) if curve_index else "",
        "bars": len(curve_index),
    }
    result["signals"] = n_signals
    result["fills"] = n_fills
    result["max_concurrent"] = max_concurrent
    result["rollovers"] = n_rollovers
    # The number the per-symbol backtest cannot produce: how much of the signal the
    # book had to throw away because every slot was taken.
    result["slot_blocked"] = n_slot_blocked
    result["kill_blocked"] = n_kill_blocked
    result["cash_blocked"] = n_cash_blocked
    result["fill_rate_pct"] = (n_fills / n_signals * 100.0) if n_signals else 0.0
    if len(trades_df):
        result["by_symbol"] = {
            sym: {"trades": int(g["pnl"].count()), "pnl": float(g["pnl"].sum())}
            for sym, g in trades_df.groupby("symbol")
        }
    return {"summary": result, "trades": trades_df, "equity": equity_s}


def render_book_report(results: list[dict], cfg: Config) -> str:
    """One line per configuration, so the comparison fits on a screen."""
    lines = ["=" * 78, "TRADEMON BOOK BACKTEST (one wallet, shared position cap)", "=" * 78]
    period = results[0]["summary"]["period"] if results else {"start": "", "end": ""}
    lines.append(f"okres: {period['start']} .. {period['end']}  "
                 f"timeframe {cfg.exchange.timeframe}")
    lines.append("")
    header = (f"{'plansza':>8} {'przydział':>11} {'limit':>6} {'wynik':>9} {'sharpe':>7} "
              f"{'maxDD':>8} {'trans.':>7} {'sygnały':>8} {'bez slotu':>10} {'w rynku':>8}")
    lines += [header, "-" * len(header)]
    for r in results:
        s = r["summary"]
        lines.append(
            f"{s['n_symbols']:>6} par {s['allocation']:>11} {s['max_open_positions']:>6} "
            f"{s['total_return_pct']:>+8.2f}% {s['sharpe']:>7.2f} "
            f"{s['max_drawdown_pct']:>7.2f}% {s['n_trades']:>7} {s['signals']:>8} "
            f"{s['slot_blocked']:>10} {s.get('time_in_market_pct', 0):>7.0f}%"
        )
    lines.append("=" * 78)
    return "\n".join(lines)
