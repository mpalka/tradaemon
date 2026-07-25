"""Performance metrics for backtest and paper-trading results."""

from __future__ import annotations

import numpy as np
import pandas as pd

from trademon.data.storage import TIMEFRAME_MS

MINUTES_PER_YEAR = 365 * 24 * 60
MS_PER_YEAR = 365 * 24 * 60 * 60 * 1000


def periods_per_year(timeframe: str) -> float:
    """How many bars of `timeframe` fit in a year (for Sharpe annualization).

    The equity series is sampled once per bar, so the annualization factor must
    match the bar length — e.g. 4h -> 2190/year, not the 525600 that assuming
    minute bars would give.
    """
    return MS_PER_YEAR / TIMEFRAME_MS[timeframe]


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def sharpe_ratio(equity: pd.Series, bars_per_year: float = MINUTES_PER_YEAR) -> float:
    rets = equity.pct_change().dropna()
    if len(rets) < 2 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(bars_per_year))


def summarize(
    trades: pd.DataFrame,
    equity: pd.Series,
    initial_capital: float,
    bars_per_year: float = MINUTES_PER_YEAR,
) -> dict:
    out: dict = {
        "initial_capital": initial_capital,
        "final_equity": float(equity.iloc[-1]) if len(equity) else initial_capital,
        "n_trades": len(trades),
    }
    out["total_return_pct"] = (out["final_equity"] / initial_capital - 1.0) * 100.0
    out["max_drawdown_pct"] = max_drawdown(equity) * 100.0 if len(equity) else 0.0
    out["sharpe"] = sharpe_ratio(equity, bars_per_year)

    if len(trades):
        pnl = trades["pnl"]
        wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
        out.update(
            win_rate_pct=float((pnl > 0).mean() * 100.0),
            profit_factor=(
                float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
            ),
            avg_trade_pnl=float(pnl.mean()),
            fees_paid=float(trades["fees"].sum()),
            gross_pnl=float(pnl.sum() + trades["fees"].sum()),
            net_pnl=float(pnl.sum()),
            exits=trades["exit_reason"].value_counts().to_dict(),
        )
    return out
