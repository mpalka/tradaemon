"""Fill simulation shared by the backtester and the paper executor, so the
backtest exercises exactly the execution path that paper trading uses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trademon.config import CostsConfig

ExitReason = Literal["tp", "sl", "timeout"]


@dataclass(frozen=True)
class Fill:
    price: float  # effective price after slippage
    fee: float    # fee in quote currency
    notional: float


def buy_fill(price: float, qty: float, costs: CostsConfig) -> Fill:
    """Taker market buy: pays slippage + taker fee."""
    eff = price * (1.0 + costs.slippage)
    notional = eff * qty
    return Fill(price=eff, fee=notional * costs.taker_fee, notional=notional)


def sell_fill(price: float, qty: float, costs: CostsConfig) -> Fill:
    """Taker market sell: pays slippage + taker fee."""
    eff = price * (1.0 - costs.slippage)
    notional = eff * qty
    return Fill(price=eff, fee=notional * costs.taker_fee, notional=notional)


def maker_buy_fill(limit_price: float, qty: float, costs: CostsConfig) -> Fill:
    """Maker limit buy: fills at the limit price, no slippage, maker fee."""
    notional = limit_price * qty
    return Fill(price=limit_price, fee=notional * costs.maker_fee, notional=notional)


def maker_sell_fill(limit_price: float, qty: float, costs: CostsConfig) -> Fill:
    """Maker limit sell: fills at the limit price, no slippage, maker fee."""
    notional = limit_price * qty
    return Fill(price=limit_price, fee=notional * costs.maker_fee, notional=notional)


def limit_buy_fills(bar_low: float, limit_price: float) -> bool:
    """A resting buy limit fills once the bar trades at or below its price."""
    return bar_low <= limit_price


def limit_sell_fills(bar_high: float, limit_price: float) -> bool:
    """A resting sell limit fills once the bar trades at or above its price."""
    return bar_high >= limit_price


def check_bracket_exit(
    bar_high: float, bar_low: float, tp: float, sl: float, direction: str = "long"
) -> ExitReason | None:
    """Which barrier does this bar touch?

    Long: take-profit is above entry (bar_high >= tp), stop below (bar_low <= sl).
    Short: mirror — take-profit below entry (bar_low <= tp), stop above
    (bar_high >= sl). If a single bar touches both barriers we cannot know the
    intra-bar order, so we assume the worse outcome (stop-loss). This
    conservative bias is shared with the labeling module.
    """
    if direction == "long":
        hit_sl, hit_tp = bar_low <= sl, bar_high >= tp
    else:
        hit_sl, hit_tp = bar_high >= sl, bar_low <= tp
    if hit_sl:
        return "sl"
    if hit_tp:
        return "tp"
    return None
