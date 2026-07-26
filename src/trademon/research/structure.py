"""Test B2 — structure-placed barriers and an expected-value entry gate.

The shipped strategy puts TP at tp*ATR and SL at sl*ATR, so R:R is a constant
of the config (1.5/2.0 -> 0.75) and identical for every setup. There is nothing
to filter on: `prob_threshold` gates on P(win) alone. That is the one idea worth
taking from the "wait until risk-to-reward clears the bar" school — but it only
means anything once R:R actually varies per setup.

So here the barriers come from price structure known at the signal bar:
  long : SL under the k-bar swing low, TP at the j-bar high (resistance)
  short: SL over the k-bar swing high, TP at the j-bar low (support)
with both distances clamped to a sane ATR band, and an ATR fallback when the
entry has already broken through the structural target. R = TP_dist / SL_dist
then varies bar to bar, and entries can be gated on expected value in R units:

    EV = p*R - (1-p) - cost_R        cost_R = round-trip cost / SL distance

Labels are recomputed against these same per-bar barriers, so p means "TP before
SL for THIS setup" rather than for a fixed ATR bracket.

Fill simulation and metrics are imported from the production modules, so the
cost model is identical to the shipped backtester and paper executor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trademon.backtest.metrics import periods_per_year, summarize
from trademon.config import Config
from trademon.execution.fills import buy_fill, check_bracket_exit, sell_fill
from trademon.features.engineering import compute_atr


def structure_barriers(
    df: pd.DataFrame,
    atr: pd.Series,
    swing_bars: int = 12,
    level_bars: int = 60,
    sl_atr_band: tuple[float, float] = (0.5, 4.0),
    tp_atr_band: tuple[float, float] = (0.5, 8.0),
    tp_fallback_atr: float = 2.0,
) -> pd.DataFrame:
    """Per-bar TP/SL prices for both directions, using only bars up to t.

    Entry is the open of t+1 (matching the execution model), while the swing and
    level lookbacks end at t — nothing here sees the future.
    """
    entry = df["open"].shift(-1).to_numpy(float)
    a = atr.to_numpy(float)
    swing_low = df["low"].rolling(swing_bars).min().to_numpy(float)
    swing_high = df["high"].rolling(swing_bars).max().to_numpy(float)
    level_high = df["high"].rolling(level_bars).max().to_numpy(float)
    level_low = df["low"].rolling(level_bars).min().to_numpy(float)

    def clamp(dist: np.ndarray, band: tuple[float, float]) -> np.ndarray:
        return np.clip(dist, band[0] * a, band[1] * a)

    # long: risk to the swing low, reward up to the recent high
    sl_d_long = clamp(entry - swing_low, sl_atr_band)
    tp_d_long = level_high - entry
    tp_d_long = np.where(tp_d_long <= 0.5 * a, tp_fallback_atr * a, tp_d_long)
    tp_d_long = clamp(tp_d_long, tp_atr_band)

    # short: mirror image
    sl_d_short = clamp(swing_high - entry, sl_atr_band)
    tp_d_short = entry - level_low
    tp_d_short = np.where(tp_d_short <= 0.5 * a, tp_fallback_atr * a, tp_d_short)
    tp_d_short = clamp(tp_d_short, tp_atr_band)

    return pd.DataFrame({
        "entry": entry,
        "atr": a,
        "long_tp": entry + tp_d_long,
        "long_sl": entry - sl_d_long,
        "long_r": tp_d_long / sl_d_long,
        "long_sl_pct": sl_d_long / entry,
        "short_tp": entry - tp_d_short,
        "short_sl": entry + sl_d_short,
        "short_r": tp_d_short / sl_d_short,
        "short_sl_pct": sl_d_short / entry,
    }, index=df.index)


def barrier_labels(
    df: pd.DataFrame,
    tp_price: np.ndarray,
    sl_price: np.ndarray,
    horizon: int,
    direction: str,
) -> np.ndarray:
    """triple_barrier_labels generalised to explicit per-bar barrier prices.

    Same conventions as trademon.labeling.triple_barrier: scan t+1..t+H, label 1
    iff TP is touched strictly before SL, a bar touching both counts as SL.
    """
    n = len(df)
    high, low = df["high"].to_numpy(float), df["low"].to_numpy(float)
    first_tp = np.full(n, np.inf)
    first_sl = np.full(n, np.inf)
    for k in range(horizon):
        shift = k + 1
        h_k = np.full(n, -np.inf)
        l_k = np.full(n, np.inf)
        if shift < n:
            h_k[: n - shift] = high[shift:]
            l_k[: n - shift] = low[shift:]
        if direction == "long":
            tp_hit, sl_hit = h_k >= tp_price, l_k <= sl_price
        else:
            tp_hit, sl_hit = l_k <= tp_price, h_k >= sl_price
        first_tp = np.where(np.isinf(first_tp) & tp_hit, k, first_tp)
        first_sl = np.where(np.isinf(first_sl) & sl_hit, k, first_sl)

    label = (first_tp < first_sl).astype(float)
    valid = np.ones(n, dtype=bool)
    valid[max(0, n - horizon - 1):] = False
    valid &= np.isfinite(tp_price) & np.isfinite(sl_price)
    return np.where(valid, label, np.nan)


def run_structure_backtest(
    df: pd.DataFrame,
    bundles: dict,
    cfg: Config,
    symbol: str,
    barriers: pd.DataFrame,
    p_long: np.ndarray,
    p_short: np.ndarray,
    min_ev: float | None = None,
    min_r: float = 0.0,
    prob_threshold: float | None = None,
    size_by_risk: bool = False,
    risk_pct: float = 0.01,
    trade_from: int = 0,
) -> dict:
    """Taker-only event backtest with per-bar barriers and an optional EV gate.

    `min_ev` is in R units (1 R = the trade's own stop distance). None disables
    the gate, leaving the plain probability threshold — that is the control this
    prototype has to beat.

    `size_by_risk` sizes each trade to lose `risk_pct` of equity at its stop
    instead of allocating a fixed notional — the natural companion to variable
    stop distances. Note it changes *exposure*, not edge: since stops here are
    ~1-3% of price, equalising risk means notionals several times larger than
    the fixed-fraction default. Read Sharpe, not return, when comparing it.
    """
    strat, costs, risk = cfg.strategy, cfg.costs, cfg.risk
    thr = strat.prob_threshold if prob_threshold is None else prob_threshold
    allow_short = strat.direction == "long_short"

    open_ = df["open"].to_numpy(float)
    high, low = df["high"].to_numpy(float), df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    ts = df["timestamp"].to_numpy()
    rt_cost = 2.0 * (costs.taker_fee + costs.slippage)

    b = {c: barriers[c].to_numpy(float) for c in barriers.columns}
    initial = cfg.paper.initial_capital
    cash = initial
    trades: list[dict] = []
    equity_curve = np.full(len(df), np.nan)

    pos_qty = side = 0
    pos_entry = tp = sl = margin = entry_fees = 0.0
    entry_bar = deadline = -1
    entry_ts = entry_r = entry_ev = None

    def ev_of(p: float, r: float, sl_pct: float) -> float:
        return p * r - (1.0 - p) - rt_cost / max(sl_pct, 1e-9)

    for t in range(len(df)):
        if pos_qty > 0 and t >= entry_bar:
            direction = "long" if side == 1 else "short"
            reason = check_bracket_exit(high[t], low[t], tp, sl, direction)
            price = None
            if reason == "tp":
                price = tp
            elif reason == "sl":
                price = sl
            elif t >= deadline:
                reason, price = "timeout", close[t]
            if price is not None:
                fill = (sell_fill if side == 1 else buy_fill)(price, pos_qty, costs)
                pnl = side * pos_qty * (fill.price - pos_entry) - entry_fees - fill.fee
                cash += margin + side * pos_qty * (fill.price - pos_entry) - fill.fee
                trades.append({
                    "symbol": symbol, "side": direction,
                    "entry_time": entry_ts, "exit_time": ts[t],
                    "qty": pos_qty, "entry_price": pos_entry, "exit_price": fill.price,
                    "exit_reason": reason, "fees": entry_fees + fill.fee, "pnl": pnl,
                    "r_planned": entry_r, "ev_planned": entry_ev,
                })
                pos_qty, margin = 0, 0.0

        if pos_qty == 0 and t >= trade_from and t + 1 < len(df) and np.isfinite(b["atr"][t]):
            best = None  # (score, side)
            for s, p_arr, pre in ((1, p_long, "long"), (-1, p_short, "short")):
                if s == -1 and not allow_short:
                    continue
                p = p_arr[t]
                if not np.isfinite(p) or p < thr:
                    continue
                r, sl_pct = b[f"{pre}_r"][t], b[f"{pre}_sl_pct"][t]
                if not np.isfinite(r) or r < min_r:
                    continue
                ev = ev_of(p, r, sl_pct)
                if min_ev is not None and ev < min_ev:
                    continue
                score = ev if min_ev is not None else p
                if best is None or score > best[0]:
                    best = (score, s, p, r, ev, sl_pct)

            if best is not None:
                _, s, p, r, ev, sl_pct = best
                pre = "long" if s == 1 else "short"
                price = open_[t + 1]
                notional = (
                    min(cash * risk_pct / max(sl_pct, 1e-9), cash * 0.95)
                    if size_by_risk
                    else cash * risk.position_pct
                )
                qty = notional / price
                fill = (buy_fill if s == 1 else sell_fill)(price, qty, costs)
                if fill.notional + fill.fee <= cash:
                    cash -= fill.notional + fill.fee
                    margin = fill.notional
                    pos_qty, side, pos_entry, entry_fees = qty, s, fill.price, fill.fee
                    tp, sl = b[f"{pre}_tp"][t], b[f"{pre}_sl"][t]
                    entry_bar, deadline, entry_ts = t + 1, t + 1 + strat.horizon_bars, ts[t]
                    entry_r, entry_ev = float(r), float(ev)

        if t >= trade_from:
            equity_curve[t] = cash + margin + side * pos_qty * (close[t] - pos_entry)

    trades_df = pd.DataFrame(trades)
    equity = pd.Series(equity_curve, index=df["timestamp"]).dropna()
    out = summarize(trades_df, equity, initial, periods_per_year(cfg.exchange.timeframe))
    out["symbol"] = symbol
    return {"summary": out, "trades": trades_df, "equity": equity}


def prepare(df: pd.DataFrame, cfg: Config, **barrier_kwargs) -> pd.DataFrame:
    return structure_barriers(df, compute_atr(df, cfg.strategy.atr_period), **barrier_kwargs)
