"""Settle rebalance orders through the shared fill model (fee + slippage), so the
backtest and the live paper book move money identically. Mutates `holdings` in
place and returns the updated cash plus a list of transaction records."""

from __future__ import annotations

from datetime import datetime

from tradaemon.config import CostsConfig
from tradaemon.execution.fills import buy_fill, sell_fill

MIN_QTY = 1e-9


def settle_orders(
    orders: list[dict],
    holdings: dict[str, float],
    cash: float,
    prices: dict[str, float],
    costs: CostsConfig,
    when: datetime | object,
) -> tuple[float, list[dict]]:
    """Apply `orders` (sells first) against current holdings/cash at `prices`.

    Buys are capped to available cash (so fees can never overdraw); a sell is
    capped to the quantity actually held. Returns (new_cash, trades)."""
    trades: list[dict] = []
    for o in orders:
        symbol = o["symbol"]
        price = prices.get(symbol, 0.0)
        if price <= 0:
            continue
        if o["side"] == "sell":
            qty = min(o["qty"], holdings.get(symbol, 0.0))
            if qty <= MIN_QTY:
                continue
            fill = sell_fill(price, qty, costs)
            cash += fill.notional - fill.fee
            holdings[symbol] = holdings.get(symbol, 0.0) - qty
        else:
            eff = price * (1.0 + costs.slippage)
            affordable = cash / (eff * (1.0 + costs.taker_fee)) if eff > 0 else 0.0
            qty = min(o["qty"], affordable)
            if qty <= MIN_QTY:
                continue
            fill = buy_fill(price, qty, costs)
            cash -= fill.notional + fill.fee
            holdings[symbol] = holdings.get(symbol, 0.0) + qty
        trades.append({
            "timestamp": when, "symbol": symbol, "side": o["side"],
            "qty": float(qty), "price": float(fill.price),
            "fee": float(fill.fee), "value": float(fill.notional),
        })
    return cash, trades
