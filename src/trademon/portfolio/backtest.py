"""Cost-aware daily backtest of the portfolio rebalancer.

Walks the aligned price panel day by day. On day 0 it allocates to the target
weights; afterwards it rebalances only when the schedule is due OR a weight drifts
past the band (`allocator.should_rebalance`). The **benchmark** buys the same
basket once and holds it forever — so the gap between the two curves *is* the value
of disciplined rebalancing (and the drag of its costs).

Reuses the crypto module's fill model (fee+slippage via `settle_orders`) and metric
primitives (`max_drawdown`, `sharpe_ratio`). Because the value here is discipline
and cost control — not per-trade alpha — the summary is portfolio-appropriate
(CAGR, volatility, drawdown, vs benchmark), not the win-rate stats used for scalping.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trademon.backtest.metrics import max_drawdown, sharpe_ratio
from trademon.portfolio import allocator
from trademon.portfolio.config import PortfolioConfig
from trademon.portfolio.rebalance import settle_orders


def _annual_metrics(equity: pd.Series, bars_per_year: int) -> tuple[float, float]:
    """(CAGR %, annualized volatility %) from a daily equity series."""
    rets = equity.pct_change().dropna()
    years = len(equity) / bars_per_year if bars_per_year else 0.0
    cagr = (
        ((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0) * 100.0
        if years > 0 and equity.iloc[0] > 0 else 0.0
    )
    vol = float(rets.std() * np.sqrt(bars_per_year) * 100.0) if len(rets) > 1 else 0.0
    return cagr, vol


def run_portfolio_backtest(
    panel: pd.DataFrame, cfg: PortfolioConfig, annual_ter_pct: float = 0.0
) -> dict:
    if panel.empty or len(panel) < 2:
        raise ValueError("need at least 2 days of aligned price data")
    symbols = list(panel.columns)
    base = cfg.base_weights
    safe = cfg.resolved_safe_asset()
    costs = cfg.costs
    initial = cfg.initial_capital
    daily_ter = annual_ter_pct / 100.0 / cfg.bars_per_year if annual_ter_pct else 0.0

    holdings = {s: 0.0 for s in symbols}
    cash = initial
    last_rebalance_i = 0
    bench_holdings = {s: 0.0 for s in symbols}
    bench_cash = initial

    dates = panel.index
    strat_curve, bench_curve, alloc_rows, trades = [], [], [], []

    for i, date in enumerate(dates):
        prices = {s: float(panel.iloc[i][s]) for s in symbols}
        history = panel.iloc[: i + 1]
        target = allocator.effective_weights(history, base, cfg.trend, safe)

        if i == 0:
            cash, tr = settle_orders(
                allocator.rebalance_orders(holdings, cash, prices, target),
                holdings, cash, prices, costs, date)
            trades += tr
            bench_cash, _ = settle_orders(
                allocator.rebalance_orders(bench_holdings, bench_cash, prices, base),
                bench_holdings, bench_cash, prices, costs, date)
        else:
            drift = allocator.max_drift_pct(holdings, cash, prices, target)
            if allocator.should_rebalance(i - last_rebalance_i, drift, cfg.rebalance):
                cash, tr = settle_orders(
                    allocator.rebalance_orders(holdings, cash, prices, target),
                    holdings, cash, prices, costs, date)
                trades += tr
                last_rebalance_i = i

        if daily_ter:
            cash -= sum(holdings[s] * prices[s] for s in symbols) * daily_ter
            bench_cash -= sum(bench_holdings[s] * prices[s] for s in symbols) * daily_ter

        strat_curve.append(allocator.portfolio_value(holdings, cash, prices))
        bench_curve.append(allocator.portfolio_value(bench_holdings, bench_cash, prices))
        w = allocator.current_weights(holdings, cash, prices)
        alloc_rows.append({"timestamp": date, **{s: w.get(s, 0.0) for s in symbols}})

    equity = pd.Series(strat_curve, index=dates)
    benchmark = pd.Series(bench_curve, index=dates)
    trades_df = pd.DataFrame(trades)
    allocations = pd.DataFrame(alloc_rows).set_index("timestamp")

    cagr, vol = _annual_metrics(equity, cfg.bars_per_year)
    summary = {
        "initial_capital": initial,
        "final_equity": float(equity.iloc[-1]),
        "total_return_pct": (equity.iloc[-1] / initial - 1.0) * 100.0,
        "benchmark_return_pct": (benchmark.iloc[-1] / initial - 1.0) * 100.0,
        "cagr_pct": cagr,
        "volatility_pct": vol,
        "sharpe": sharpe_ratio(equity, cfg.bars_per_year),
        "benchmark_sharpe": sharpe_ratio(benchmark, cfg.bars_per_year),
        "max_drawdown_pct": max_drawdown(equity) * 100.0,
        "benchmark_max_drawdown_pct": max_drawdown(benchmark) * 100.0,
        "n_rebalances": int(trades_df["timestamp"].nunique()) if len(trades_df) else 0,
        "n_transactions": len(trades_df),
        "fees_paid": float(trades_df["fee"].sum()) if len(trades_df) else 0.0,
        "trend_enabled": cfg.trend.enabled,
        "target_weights": base,
        "symbols": symbols,
        "period": {"start": str(dates[0].date()), "end": str(dates[-1].date()),
                   "bars": len(dates)},
    }
    summary["excess_return_pct"] = (
        summary["total_return_pct"] - summary["benchmark_return_pct"])
    return {"summary": summary, "equity": equity, "benchmark": benchmark,
            "trades": trades_df, "allocations": allocations}


def render_portfolio_report(result: dict) -> str:
    """Plain-text summary: the rebalanced portfolio vs. buy & hold, after costs."""
    s = result["summary"]
    beat = s["excess_return_pct"] > 0
    basket = ", ".join(f"{k} {v:.0%}" for k, v in s["target_weights"].items())
    trend = "WŁĄCZONY" if s["trend_enabled"] else "wyłączony"
    lines = [
        "=" * 64, "TRADEMON — RAPORT PORTFELA (rebalanser)", "=" * 64,
        (f"Okres: {s['period']['start']} .. {s['period']['end']} "
         f"({s['period']['bars']} dni handlowych)"),
        f"Koszyk: {basket}   filtr trendu: {trend}",
        "-" * 64,
        (f"  Strategia (rebalans):  {s['total_return_pct']:+.2f}%   "
         f"CAGR {s['cagr_pct']:+.2f}%/rok   Sharpe {s['sharpe']:.2f}   "
         f"max DD {s['max_drawdown_pct']:.2f}%"),
        (f"  Benchmark (kup i trzymaj): {s['benchmark_return_pct']:+.2f}%   "
         f"Sharpe {s['benchmark_sharpe']:.2f}   "
         f"max DD {s['benchmark_max_drawdown_pct']:.2f}%"),
        f"  Przewaga nad benchmarkiem: {s['excess_return_pct']:+.2f} pkt proc.",
        f"  Zmienność (roczna): {s['volatility_pct']:.2f}%",
        (f"  Rebalansów: {s['n_rebalances']}   transakcji: {s['n_transactions']}   "
         f"prowizje: {s['fees_paid']:.2f}"),
        "-" * 64,
        (f"WNIOSEK: rebalans {'POBIŁ' if beat else 'NIE pobił'} prostego trzymania "
         "koszyka po kosztach."),
        ("Uwaga: wartość rebalansu to dyscyplina i kontrola ryzyka, nie 'alfa'. "
         "Wynik zależy od okresu; to narzędzie edukacyjne, nie porada inwestycyjna."),
        "=" * 64,
    ]
    return "\n".join(lines)
