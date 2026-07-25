"""Risk management: position sizing, exposure limits and a daily kill-switch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from trademon.config import RiskConfig


@dataclass
class DayState:
    day: date
    start_equity: float
    realized_pnl: float = 0.0


@dataclass
class RiskManager:
    cfg: RiskConfig
    _day: DayState | None = field(default=None)

    def _roll_day(self, now: datetime, equity: float) -> DayState:
        today = now.astimezone(UTC).date()
        if self._day is None or self._day.day != today:
            self._day = DayState(day=today, start_equity=equity)
        return self._day

    def record_realized_pnl(self, pnl: float, now: datetime, equity: float) -> None:
        self._roll_day(now, equity).realized_pnl += pnl

    def kill_switch_active(self, now: datetime, equity: float) -> bool:
        day = self._roll_day(now, equity)
        return day.realized_pnl <= -self.cfg.daily_loss_limit_pct * day.start_equity

    def can_open(
        self, open_positions: int, equity: float, now: datetime
    ) -> tuple[bool, str]:
        if open_positions >= self.cfg.max_open_positions:
            return False, f"max_open_positions ({self.cfg.max_open_positions}) reached"
        if self.kill_switch_active(now, equity):
            return False, (
                f"kill-switch: daily loss limit "
                f"({self.cfg.daily_loss_limit_pct:.1%}) hit, no new entries today"
            )
        return True, "ok"

    def position_qty(self, equity: float, price: float) -> float:
        return (equity * self.cfg.position_pct) / price

    def snapshot(self) -> dict:
        if self._day is None:
            return {}
        return {
            "day": self._day.day.isoformat(),
            "day_start_equity": self._day.start_equity,
            "day_realized_pnl": self._day.realized_pnl,
        }

    def restore(self, snap: dict) -> None:
        if snap.get("day"):
            self._day = DayState(
                day=date.fromisoformat(snap["day"]),
                start_equity=float(snap["day_start_equity"]),
                realized_pnl=float(snap.get("day_realized_pnl", 0.0)),
            )
