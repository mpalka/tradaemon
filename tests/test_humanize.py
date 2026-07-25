"""Tests for the beginner-dashboard translation layer (dashboard/humanize.py)."""

from datetime import UTC, datetime

import pytest

from trademon.dashboard import humanize


def test_reason_and_exit_maps():
    assert humanize.REASON_PL["below_threshold"] == "nie widzi wystarczającej okazji"
    assert humanize.REASON_PL["enter_long"].startswith("otwiera")
    assert "zysk" in humanize.EXIT_PL["tp"]
    assert "strat" in humanize.EXIT_PL["sl"]


def test_event_line_uses_friendly_message():
    rec = {"kind": "trade_open", "timestamp": "2026-07-25T14:00:00+00:00",
           "message": "BTC/USDT otwarto long @ 60000.00 (p=0.62)"}
    e = humanize.event_line(rec)
    assert e["emoji"] == "🟢"
    assert e["text"] == rec["message"]
    assert e["time"] == "25.07 14:00"


def test_event_line_close_emoji_by_pnl():
    win = humanize.event_line({"kind": "trade_close", "pnl": 5.0, "message": "zysk"})
    loss = humanize.event_line({"kind": "trade_close", "pnl": -5.0, "message": "strata"})
    assert win["emoji"] == "💰"
    assert loss["emoji"] == "🔻"


def test_event_line_fallback_without_message():
    e = humanize.event_line({"symbol": "ETH/USDT", "exit_reason": "sl",
                             "timestamp": "2026-07-25T10:00:00+00:00"})
    assert "ETH/USDT" in e["text"]
    assert "strat" in e["text"]


def test_position_card_profit_and_loss():
    win = humanize.position_card(
        {"symbol": "ETH/USDT", "qty": 1.0, "entry_price": 100.0, "side": "long"}, 102.0)
    assert win["pnl"] == pytest.approx(2.0)
    assert win["pct"] == pytest.approx(2.0)
    assert win["emoji"] == "🟢"
    assert win["color"] == humanize.GOOD
    assert "ETH" in win["title"]

    loss = humanize.position_card(
        {"symbol": "ETH/USDT", "qty": 1.0, "entry_price": 100.0, "side": "long"}, 95.0)
    assert loss["pnl"] == pytest.approx(-5.0)
    assert loss["emoji"] == "🔴"
    assert loss["color"] == humanize.BAD


def test_holding_card_drift_flag():
    on_target = humanize.holding_card("SPY", 5000.0, 0.50, 0.50)
    off = humanize.holding_card("SPY", 6000.0, 0.60, 0.50)
    assert on_target["emoji"] == "✅"
    assert off["emoji"] == "⚖️"
    assert "cel 50%" in off["detail"]


def test_bot_status_fresh_and_stale():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    fresh = humanize.bot_status(
        {"BTC/USDT": "2026-07-25T11:30:00+00:00"}, 4 * 3_600_000, now)
    assert fresh["ok"] and fresh["emoji"] == "🟢"
    stale = humanize.bot_status(
        {"BTC/USDT": "2026-07-20T11:30:00+00:00"}, 4 * 3_600_000, now)
    assert not stale["ok"] and stale["emoji"] == "🔴"


def test_bot_status_empty():
    assert not humanize.bot_status({}, 1000, datetime.now(UTC))["ok"]
