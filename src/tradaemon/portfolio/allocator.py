"""Pure, testable rebalancing logic — the portfolio manager's 'signal'.

No look-ahead: every function uses only prices up to the decision day. The
allocator decides target weights (optionally trend-filtered) and the orders that
move current holdings toward them. Cadence/threshold policy is decided by the
caller (backtest/book) via `should_rebalance`.
"""

from __future__ import annotations

import pandas as pd

from tradaemon.portfolio.config import RebalanceConfig, TrendConfig


def effective_weights(
    price_history: pd.DataFrame,
    base_weights: dict[str, float],
    trend: TrendConfig,
    safe_asset: str | None = None,
) -> dict[str, float]:
    """Target weights after the optional trend filter.

    With trend off (or not enough history to judge), returns the base weights.
    With trend on, an asset trading below its `ma_days` average hands its weight
    to `safe_asset` (or to cash if none). Uses only rows up to the last one, so
    it never peeks at the future. The remainder (1 - sum) is held as cash.
    """
    weights = {s: float(w) for s, w in base_weights.items()}
    if not trend.enabled or len(price_history) < trend.ma_days:
        return weights
    eff = {s: 0.0 for s in base_weights}
    for s, w in weights.items():
        if s not in price_history.columns:
            eff[s] += w  # cannot judge -> keep as-is
            continue
        col = price_history[s]
        ma = float(col.tail(trend.ma_days).mean())
        if float(col.iloc[-1]) >= ma:
            eff[s] += w
        elif safe_asset and safe_asset in eff:
            eff[safe_asset] += w
        # else: parked in cash (weight left unallocated)
    return eff


def portfolio_value(holdings: dict[str, float], cash: float, prices: dict[str, float]) -> float:
    return float(cash) + sum(qty * prices.get(s, 0.0) for s, qty in holdings.items())


def current_weights(
    holdings: dict[str, float], cash: float, prices: dict[str, float]
) -> dict[str, float]:
    total = portfolio_value(holdings, cash, prices)
    if total <= 0:
        return {}
    return {s: qty * prices.get(s, 0.0) / total for s, qty in holdings.items()}


def max_drift_pct(
    holdings: dict[str, float], cash: float, prices: dict[str, float],
    target_weights: dict[str, float],
) -> float:
    """Largest gap (in percentage points) between a current and target weight."""
    total = portfolio_value(holdings, cash, prices)
    if total <= 0:
        return 0.0
    drift = 0.0
    for s in set(holdings) | set(target_weights):
        cur = holdings.get(s, 0.0) * prices.get(s, 0.0) / total
        drift = max(drift, abs(cur - target_weights.get(s, 0.0)))
    return drift * 100.0


def should_rebalance(days_since_last: int, max_drift: float, rebalance: RebalanceConfig) -> bool:
    """Rebalance if the schedule is due OR a weight has drifted past the band."""
    return (days_since_last >= rebalance.cadence_days
            or max_drift >= rebalance.drift_threshold_pct)


def rebalance_orders(
    holdings: dict[str, float], cash: float, prices: dict[str, float],
    target_weights: dict[str, float], min_trade_value: float = 1.0,
) -> list[dict]:
    """Orders that move holdings toward target weights (costs applied by caller).

    Sells are ordered before buys so freed cash funds the buys.
    """
    total = portfolio_value(holdings, cash, prices)
    orders: list[dict] = []
    for s in sorted(set(holdings) | set(target_weights)):
        price = prices.get(s, 0.0)
        if price <= 0:
            continue
        delta_value = target_weights.get(s, 0.0) * total - holdings.get(s, 0.0) * price
        if abs(delta_value) < min_trade_value:
            continue
        orders.append({"symbol": s, "side": "buy" if delta_value > 0 else "sell",
                       "qty": abs(delta_value) / price})
    orders.sort(key=lambda o: 0 if o["side"] == "sell" else 1)
    return orders
