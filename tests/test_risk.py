from datetime import UTC, datetime, timedelta

import pytest

from trademon.config import RiskConfig
from trademon.risk.manager import RiskManager

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def make_rm() -> RiskManager:
    return RiskManager(RiskConfig(position_pct=0.1, max_open_positions=2,
                                  daily_loss_limit_pct=0.03))


def test_position_qty():
    rm = make_rm()
    assert rm.position_qty(equity=1000.0, price=50.0) == pytest.approx(2.0)


def test_max_open_positions():
    rm = make_rm()
    ok, _ = rm.can_open(open_positions=1, equity=1000.0, now=NOW)
    assert ok
    ok, reason = rm.can_open(open_positions=2, equity=1000.0, now=NOW)
    assert not ok and "max_open_positions" in reason


def test_kill_switch_after_daily_loss_and_reset_next_day():
    rm = make_rm()
    rm.record_realized_pnl(-10.0, NOW, equity=990.0)  # day start equity = 990
    assert not rm.kill_switch_active(NOW, 990.0)  # -10 > -3% * 990
    rm.record_realized_pnl(-25.0, NOW, equity=965.0)  # total -35 vs 3% of day start
    assert rm.kill_switch_active(NOW, 965.0)
    ok, reason = rm.can_open(0, 965.0, NOW)
    assert not ok and "kill-switch" in reason

    next_day = NOW + timedelta(days=1)
    assert not rm.kill_switch_active(next_day, 965.0)
    ok, _ = rm.can_open(0, 965.0, next_day)
    assert ok


def test_snapshot_restore_round_trip():
    rm = make_rm()
    rm.record_realized_pnl(-5.0, NOW, equity=1000.0)
    snap = rm.snapshot()
    rm2 = make_rm()
    rm2.restore(snap)
    assert rm2.snapshot() == snap
