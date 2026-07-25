"""Order executors. PaperExecutor simulates fills locally; LiveExecutor sends
real market orders through CCXT. Both expose the same interface, so the engine
code path is identical in paper and live mode."""

from __future__ import annotations

import logging
from typing import Protocol

import ccxt

from trademon.config import Config
from trademon.execution.fills import Fill, buy_fill, sell_fill

log = logging.getLogger(__name__)


class Executor(Protocol):
    def market_buy(self, symbol: str, qty: float, price_hint: float) -> Fill: ...
    def market_sell(self, symbol: str, qty: float, price_hint: float) -> Fill: ...


class PaperExecutor:
    """Simulated fills at price_hint adjusted for slippage + taker fee."""

    def __init__(self, cfg: Config):
        self.costs = cfg.costs

    def market_buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return buy_fill(price_hint, qty, self.costs)

    def market_sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        return sell_fill(price_hint, qty, self.costs)


class LiveExecutor:
    """Real market orders via CCXT. Requires mode: live and API keys with
    trade-only permission. Instantiating it in paper mode is a hard error."""

    def __init__(self, cfg: Config, exchange: ccxt.Exchange):
        if cfg.mode != "live":
            raise RuntimeError("LiveExecutor requires mode: live in config.yaml")
        self.exchange = exchange
        self.costs = cfg.costs

    def _fill_from_order(self, order: dict, side: str, qty: float, price_hint: float) -> Fill:
        price = order.get("average") or order.get("price") or price_hint
        notional = price * (order.get("filled") or qty)
        fee_info = order.get("fee") or {}
        fee = fee_info.get("cost") or notional * self.costs.taker_fee
        return Fill(price=price, fee=fee, notional=notional)

    def market_buy(self, symbol: str, qty: float, price_hint: float) -> Fill:
        order = self.exchange.create_order(symbol, "market", "buy", qty)
        log.info("LIVE buy %s qty=%.8f -> %s", symbol, qty, order.get("id"))
        return self._fill_from_order(order, "buy", qty, price_hint)

    def market_sell(self, symbol: str, qty: float, price_hint: float) -> Fill:
        order = self.exchange.create_order(symbol, "market", "sell", qty)
        log.info("LIVE sell %s qty=%.8f -> %s", symbol, qty, order.get("id"))
        return self._fill_from_order(order, "sell", qty, price_hint)
