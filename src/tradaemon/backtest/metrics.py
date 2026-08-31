"""Performance metrics for backtest and paper-trading results."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradaemon.data.storage import TIMEFRAME_MS

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


def exposure_series(equity: pd.Series, cash: pd.Series) -> pd.Series:
    """Fraction of capital actually at risk per bar: (equity - cash) / equity.

    Returns and drawdown are computed on *total* equity, but a strategy capped at
    `position_pct * max_open_positions` leaves most of the account idle — so those
    numbers describe the account, not the quality of the signal.
    """
    aligned = pd.DataFrame({"equity": equity, "cash": cash}).dropna()
    if aligned.empty:
        return pd.Series(dtype="float64")
    invested = (aligned["equity"] - aligned["cash"]).clip(lower=0.0)
    frac = invested.div(aligned["equity"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return frac.clip(0.0, 1.0)


def avg_exposure_pct(equity: pd.Series, cash: pd.Series) -> float:
    """Average share of the account that was in the market, in percent."""
    s = exposure_series(equity, cash)
    return float(s.mean() * 100.0) if len(s) else 0.0


def time_in_market_pct(equity: pd.Series, cash: pd.Series) -> float:
    """Share of bars with any position open. Explains a low average exposure: a book
    that risks 10% but only trades on 6% of bars averages 0.6%, which says nothing
    about position sizing."""
    s = exposure_series(equity, cash)
    return float((s > 0.0).mean() * 100.0) if len(s) else 0.0


# Below this average exposure the rescale below extrapolates more than 10x, which
# says more about how rarely the book traded than about the quality of the signal.
MIN_EXPOSURE_TO_RESCALE_PCT = 10.0


def return_on_risked_pct(total_return_pct: float, avg_exposure: float) -> float | None:
    """Total return rescaled to the capital that was actually deployed, or None when
    the account sat idle so much that the rescale would be an extrapolation.

    Approximation — it assumes P&L scales linearly with the amount at risk. Enough
    to stop idle cash from flattering the result; not a precise measure, so don't
    present it as one.
    """
    if avg_exposure < MIN_EXPOSURE_TO_RESCALE_PCT:
        return None
    return total_return_pct / (avg_exposure / 100.0)


def summarize(
    trades: pd.DataFrame,
    equity: pd.Series,
    initial_capital: float,
    bars_per_year: float = MINUTES_PER_YEAR,
    cash: pd.Series | None = None,
) -> dict:
    out: dict = {
        "initial_capital": initial_capital,
        "final_equity": float(equity.iloc[-1]) if len(equity) else initial_capital,
        "n_trades": len(trades),
    }
    out["total_return_pct"] = (out["final_equity"] / initial_capital - 1.0) * 100.0
    out["max_drawdown_pct"] = max_drawdown(equity) * 100.0 if len(equity) else 0.0
    out["sharpe"] = sharpe_ratio(equity, bars_per_year)

    if cash is not None and len(equity):
        out["avg_exposure_pct"] = avg_exposure_pct(equity, cash)
        out["time_in_market_pct"] = time_in_market_pct(equity, cash)
        out["return_on_risked_pct"] = return_on_risked_pct(
            out["total_return_pct"], out["avg_exposure_pct"]
        )

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
