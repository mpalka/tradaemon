"""Live/paper portfolio book: one rebalanced portfolio with its own runtime files.

Mirrors the crypto `Book` pattern (cash + holdings + RuntimeStore) but on a daily
clock and with rebalancing instead of entries/exits. Fully synchronous and unit-
testable: feed it days via `on_day` and inspect holdings/cash/equity. Decisions use
only closed daily candles and the same fill model as the backtest (`settle_orders`),
so paper trading exercises exactly the code the backtest measured.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd

from trademon.engine.notify import send_webhook
from trademon.engine.state import RuntimeStore
from trademon.portfolio import allocator
from trademon.portfolio.config import PortfolioConfig
from trademon.portfolio.rebalance import settle_orders

log = logging.getLogger(__name__)

DRAWDOWN_ALERT_PCT = 20.0  # one-shot alert when equity falls this far below its peak


class PortfolioBook:
    def __init__(self, name: str, cfg: PortfolioConfig, store: RuntimeStore):
        self.name = name
        self.cfg = cfg
        self.store = store
        self.symbols = cfg.symbols
        self.base_weights = cfg.base_weights
        self.safe_asset = cfg.resolved_safe_asset()
        self.holdings: dict[str, float] = {s: 0.0 for s in self.symbols}
        self.cash = cfg.initial_capital
        self.last_close: dict[str, float] = {}
        self.last_candle_ts: dict[str, str] = {}
        self.target_weights: dict[str, float] = dict(self.base_weights)
        self.last_rebalance: datetime | None = None
        self._peak_equity = cfg.initial_capital
        self._initialized = False
        self._dd_alerted = False

    # ---------- state ----------

    def equity(self) -> float:
        return allocator.portfolio_value(self.holdings, self.cash, self.last_close)

    def drawdown_pct(self) -> float:
        eq = self.equity()
        self._peak_equity = max(self._peak_equity, eq)
        return (eq / self._peak_equity - 1.0) * 100.0 if self._peak_equity else 0.0

    def weights(self) -> dict[str, float]:
        return allocator.current_weights(self.holdings, self.cash, self.last_close)

    def alert(self, kind: str, message: str, now: datetime, **extra) -> None:
        self.store.append_alert({"timestamp": now.isoformat(), "kind": kind,
                                 "message": message, "book": self.name, **extra})
        log.info("[%s] ALERT [%s] %s", self.name, kind, message)
        send_webhook(self.cfg.alert_webhook_url, f"[{self.name}][{kind}] {message}")

    def restore(self) -> None:
        state = self.store.load_state()
        if not state:
            return
        self.cash = float(state["cash"])
        self.holdings = {s: float(q) for s, q in state.get("holdings", {}).items()}
        self.last_close = {s: float(p) for s, p in state.get("last_close", {}).items()}
        self._peak_equity = float(state.get("peak_equity", self.cash))
        if state.get("last_rebalance"):
            self.last_rebalance = datetime.fromisoformat(state["last_rebalance"])
        self._initialized = bool(state.get("initialized", bool(self.last_rebalance)))
        log.info("[%s] restored: cash=%.2f, holdings=%s",
                 self.name, self.cash, {s: round(q, 4) for s, q in self.holdings.items()})

    def persist(self, now: datetime) -> None:
        self.store.save_state({
            "updated_at": now.isoformat(),
            "book": self.name,
            "module": "portfolio",
            "mode": "paper",
            "timeframe": "1d",
            "symbols": self.symbols,
            "cash": self.cash,
            "equity": self.equity(),
            "peak_equity": self._peak_equity,
            "drawdown_pct": self.drawdown_pct(),
            "holdings": self.holdings,
            "last_close": self.last_close,
            "weights": self.weights(),
            "target_weights": self.target_weights,
            "initialized": self._initialized,
            "last_rebalance": self.last_rebalance.isoformat() if self.last_rebalance else None,
            "last_candle_ts": self.last_candle_ts,
        })

    # ---------- core logic ----------

    def on_day(self, date: datetime, prices: dict[str, float], history: pd.DataFrame) -> None:
        """Process one closed daily candle: rebalance if due, then persist."""
        self.last_close.update({s: float(p) for s, p in prices.items()})
        for s in prices:
            self.last_candle_ts[s] = date.isoformat()
        self.target_weights = allocator.effective_weights(
            history, self.base_weights, self.cfg.trend, self.safe_asset)

        if not self._initialized:
            self._rebalance(date, prices, "initial_allocation",
                            "pierwsza alokacja koszyka")
            self._initialized = True
        else:
            drift = allocator.max_drift_pct(
                self.holdings, self.cash, prices, self.target_weights)
            days_since = (date - self.last_rebalance).days if self.last_rebalance else 10**9
            if allocator.should_rebalance(days_since, drift, self.cfg.rebalance):
                self._rebalance(date, prices, "rebalance",
                                f"rebalans do wag docelowych (drift {drift:.1f} pkt)")

        self.store.append_equity({
            "timestamp": date.isoformat(), "equity": self.equity(), "cash": self.cash})
        self._check_drawdown(date)
        self.persist(datetime.now(UTC))

    def _rebalance(self, date: datetime, prices: dict[str, float],
                   kind: str, message: str) -> None:
        orders = allocator.rebalance_orders(
            self.holdings, self.cash, prices, self.target_weights)
        if not orders and self._initialized:
            return
        self.cash, trades = settle_orders(
            orders, self.holdings, self.cash, prices, self.cfg.costs, date)
        for t in trades:
            self.store.append_trade({**t, "timestamp": date.isoformat(), "kind": kind})
        self.last_rebalance = date
        log.info("[%s] %s: %d transakcji, kapitał=%.2f",
                 self.name, kind, len(trades), self.equity())
        self.alert(kind, message, date, n_transactions=len(trades))

    def _check_drawdown(self, date: datetime) -> None:
        dd = self.drawdown_pct()
        if dd <= -DRAWDOWN_ALERT_PCT and not self._dd_alerted:
            self.alert("drawdown", f"obsunięcie {dd:.1f}% od szczytu wartości portfela", date)
            self._dd_alerted = True
        elif dd > -DRAWDOWN_ALERT_PCT * 0.5:
            self._dd_alerted = False
