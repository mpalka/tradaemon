"""Daily backtest of the ranking study, for one market and one direction.

Positions are signed unit counts plus cash, so equity = cash + sum(qty * price) is
correct for both legs (shorting raises cash and carries a negative position value —
the same futures-style accounting module 1 uses for its short side). Weights drift
with prices between rebalances instead of being magically reset every day, which is
what makes the turnover — and therefore the cost — realistic.

Costs use the shared CostsConfig rates (fee + slippage on traded notional), so the
cost assumptions are identical to the other two modules even though this module
prices a whole rebalance rather than individual orders.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradaemon.backtest.metrics import max_drawdown, sharpe_ratio
from tradaemon.crosssec.config import CrossSecConfig
from tradaemon.crosssec.signal import weights_at

MIN_TRADE_VALUE = 1e-6


def equal_weight_benchmark(panel: pd.DataFrame, initial: float) -> pd.Series:
    """Buy the whole universe equally on day one and hold — the yardstick a ranking
    strategy has to beat. Names that are not trading yet on day one are left out
    rather than back-filled in."""
    if panel.empty:
        return pd.Series(dtype="float64")
    first = panel.iloc[0]
    live = [c for c in panel.columns if pd.notna(first[c]) and first[c] > 0]
    if not live:
        return pd.Series(dtype="float64")
    return initial * panel[live].div(first[live]).mean(axis=1)


def _mark(qty: dict[str, float], px: pd.Series) -> float:
    return sum(q * px[s] for s, q in qty.items() if s in px and pd.notna(px[s]))


def gross_of_noise(returns: pd.Series) -> float:
    """How many standard errors the mean return sits from zero.

    The single most useful number in this project: below ~2 the result is
    indistinguishable from luck, whatever the headline percentage says.
    """
    r = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(r) < 3 or r.std() == 0:
        return 0.0
    return float(r.mean() / (r.std() / np.sqrt(len(r))))


def run_crosssec_backtest(panel: pd.DataFrame, cfg: CrossSecConfig, direction: str,
                          bars_per_year: int = 365) -> dict:
    """Walk the panel day by day, re-ranking every `rebalance_days`.

    The ranking for a given day is computed from prices that end the *previous* day
    and executed at the current close, so no decision can see the bar it trades on.
    """
    sig, rank = cfg.signal, cfg.rank
    warmup = sig.lookback_days + sig.skip_days + 1
    if len(panel) <= warmup + 1:
        return {"summary": {"error": "not enough history", "bars": len(panel)},
                "equity": pd.Series(dtype="float64"), "trades": pd.DataFrame()}

    cash = cfg.initial_capital
    qty: dict[str, float] = {}
    rows, trades = [], []
    fees_paid = turnover_total = 0.0
    n_rebalances = 0

    for i in range(warmup, len(panel)):
        date, px = panel.index[i], panel.iloc[i]
        equity = cash + _mark(qty, px)

        if (i - warmup) % rank.rebalance_days == 0 and equity > 0:
            # history ends yesterday -> the signal cannot see today's close
            weights = weights_at(panel.iloc[:i], sig.lookback_days, sig.skip_days,
                                 rank.n_long, rank.n_short, direction)
            tradable = {s: w for s, w in weights.items()
                        if s in px and pd.notna(px[s]) and px[s] > 0}
            if tradable:
                cost = 0.0
                for sym in set(tradable) | set(qty):
                    if sym not in px or pd.isna(px[sym]) or px[sym] <= 0:
                        continue
                    target = tradable.get(sym, 0.0) * equity / px[sym]
                    delta = target - qty.get(sym, 0.0)
                    value = abs(delta) * px[sym]
                    if value < MIN_TRADE_VALUE:
                        continue
                    cash -= delta * px[sym]
                    cost += value * cfg.turnover_cost
                    turnover_total += value
                    qty[sym] = target
                    trades.append({"timestamp": date, "symbol": sym,
                                   "side": "buy" if delta > 0 else "sell",
                                   "qty": abs(float(delta)), "price": float(px[sym]),
                                   "value": float(value)})
                qty = {s: q for s, q in qty.items() if abs(q) > 0}
                cash -= cost
                fees_paid += cost
                n_rebalances += 1

        marked = _mark(qty, px)
        gross = sum(abs(q * px[s]) for s, q in qty.items() if s in px and pd.notna(px[s]))
        equity = cash + marked
        rows.append({"timestamp": date, "equity": equity,
                     "gross_pct": 100.0 * gross / equity if equity else 0.0,
                     "net_pct": 100.0 * marked / equity if equity else 0.0})

    curve = pd.DataFrame(rows).set_index("timestamp")
    equity = curve["equity"]
    bench = equal_weight_benchmark(panel.loc[equity.index], cfg.initial_capital)

    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    total = (equity.iloc[-1] / cfg.initial_capital - 1.0) * 100.0
    bench_total = ((bench.iloc[-1] / cfg.initial_capital - 1.0) * 100.0
                   if len(bench) else float("nan"))
    # Which yardstick is fair depends on how much market exposure the book carries.
    # long_only runs ~100% net long, so the equal-weight basket is a like-for-like
    # comparison. long_short runs ~0% net, so it must clear *cash*, not the basket:
    # scoring a market-neutral book against a fully invested one is the same
    # exposure-mismatch error that flattered module 1.
    hurdle = bench_total if direction == "long_only" else 0.0
    summary = {
        "direction": direction,
        "start": str(equity.index[0].date()), "end": str(equity.index[-1].date()),
        "bars": len(equity), "n_rebalances": n_rebalances,
        "total_return_pct": total,
        "cagr_pct": ((equity.iloc[-1] / cfg.initial_capital) ** (1 / years) - 1.0) * 100.0,
        "sharpe": sharpe_ratio(equity, bars_per_year),
        "max_drawdown_pct": max_drawdown(equity) * 100.0,
        "benchmark_return_pct": bench_total,
        "hurdle_pct": hurdle,
        "excess_vs_hurdle_pp": total - hurdle,
        "excess_vs_benchmark_pp": total - bench_total,
        # How many standard errors the mean daily return sits from zero. Below ~2 the
        # headline percentage, however large, is indistinguishable from luck.
        "sigmas_from_zero": gross_of_noise(equity.pct_change()),
        "avg_gross_exposure_pct": float(curve["gross_pct"].mean()),
        "avg_net_exposure_pct": float(curve["net_pct"].mean()),
        "turnover_x_capital": turnover_total / cfg.initial_capital,
        "fees_paid": fees_paid,
        "fees_pct_of_capital": 100.0 * fees_paid / cfg.initial_capital,
    }
    return {"summary": summary, "equity": equity, "benchmark": bench,
            "trades": pd.DataFrame(trades), "exposure": curve}
