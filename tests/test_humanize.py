"""Tests for the beginner-dashboard plain-language layer (dashboard/humanize.py)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from trademon import i18n
from trademon.dashboard import humanize

WARSAW = ZoneInfo("Europe/Warsaw")
H4_MS = 4 * 3_600_000


@pytest.fixture(autouse=True)
def _polish(monkeypatch):
    """Assert against Polish, the source language, whatever else the suite has set.

    Importing the dashboard elsewhere leaves a language in `st.session_state`, and
    these tests are about the wording, not about which catalogue is active.
    """
    monkeypatch.setattr(i18n, "_session_lang", lambda: None)
    monkeypatch.setattr(i18n, "_default_lang", "pl")


def test_reason_and_exit_sentences():
    assert humanize.reason("below_threshold") == "nie widzi wystarczającej okazji"
    assert humanize.reason("enter_long").startswith("otwiera")
    assert "zysk" in humanize.exit_reason("tp")
    assert "strat" in humanize.exit_reason("sl")
    # An unknown code passes through rather than rendering as a bare catalogue key.
    assert humanize.reason("something_new") == "something_new"


def test_the_same_reason_reads_in_english_too(monkeypatch):
    monkeypatch.setattr(i18n, "_default_lang", "en")
    assert humanize.reason("below_threshold") == "does not see a good enough opportunity"
    assert humanize.exit_reason("tp").startswith("at a profit")


def test_an_alert_written_with_params_is_rendered_in_the_active_language(monkeypatch):
    """The 0.2.0 journal format: `msg_key` + `params`, composed at display time."""
    rec = {"kind": "drawdown", "timestamp": "2026-08-09T20:00:00+00:00",
           "msg_key": "alert.drawdown", "params": {"dd": "-4.2"},
           "message": "obsunięcie -4.2% od szczytu kapitału"}
    assert humanize.event_line(rec)["text"] == "obsunięcie -4.2% od szczytu kapitału"
    monkeypatch.setattr(i18n, "_default_lang", "en")
    assert humanize.event_line(rec)["text"] == "down -4.2% from the equity peak"


def test_a_journal_line_from_before_0_2_0_still_reads():
    """Months of history on a running deployment carry only a rendered sentence."""
    rec = {"kind": "drawdown", "timestamp": "2026-08-09T20:00:00+00:00",
           "message": "obsunięcie -4.2% od szczytu kapitału"}
    assert humanize.event_line(rec)["text"] == "obsunięcie -4.2% od szczytu kapitału"


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


def test_connection_status_beats_the_candle_clock():
    """The case that sent us looking: on 4h bars `bot_status` still reads green
    an hour after the exchange went silent, so the panel needs a faster signal."""
    now = datetime(2026, 8, 7, 22, 0, tzinfo=UTC)
    candles = {"BTC/USDT": "2026-08-07T17:00:00+00:00"}
    assert humanize.bot_status(candles, 4 * 3_600_000, now)["ok"]      # still green
    dead = humanize.connection_status("2026-08-07T21:00:00+00:00", now)
    assert not dead["ok"] and "brak kontaktu" in dead["text"]


def test_connection_status_fresh_and_stale():
    now = datetime(2026, 8, 7, 22, 0, tzinfo=UTC)
    live = humanize.connection_status("2026-08-07T21:59:51+00:00", now)
    assert live["ok"] and "przed chwilą" in live["text"]
    # exactly at the threshold still counts as alive; one second past it does not
    edge = humanize.connection_status("2026-08-07T21:55:00+00:00", now)
    assert edge["ok"]
    assert not humanize.connection_status("2026-08-07T21:54:59+00:00", now)["ok"]


def test_event_line_separates_an_open_outage_from_the_all_clear():
    lost = humanize.event_line({"kind": "connection", "message": "brak połączenia",
                                "ok": False, "timestamp": "2026-08-07T21:00:00+00:00"})
    back = humanize.event_line({"kind": "connection", "message": "połączenie wróciło",
                                "ok": True, "timestamp": "2026-08-07T21:45:00+00:00"})
    assert lost["emoji"] == "📡" and back["emoji"] == "✅"
    # rows written before `ok` existed are outages; reading one as an all-clear
    # would be the worst way to be wrong
    legacy = humanize.event_line({"kind": "connection", "message": "brak połączenia",
                                  "timestamp": "2026-08-07T21:00:00+00:00"})
    assert legacy["emoji"] == "📡"


def test_connection_status_without_a_heartbeat():
    now = datetime(2026, 8, 7, 22, 0, tzinfo=UTC)
    assert not humanize.connection_status(None, now)["ok"]
    assert not humanize.connection_status("nie-data", now)["ok"]


def test_bot_status_healthy_mid_window_stays_green():
    # A 4h candle opened 04:00 closes 08:00. Just before the next close (12:00)
    # its open time is ~8h old — but the bot is healthy and must read 🟢.
    lct = {"BTC/USDT": "2026-07-27T04:00:00+00:00"}
    just_closed = humanize.bot_status(lct, H4_MS, datetime(2026, 7, 27, 8, 32, tzinfo=UTC))
    near_next = humanize.bot_status(lct, H4_MS, datetime(2026, 7, 27, 11, 45, tzinfo=UTC))
    assert just_closed["ok"] and near_next["ok"]


def test_bot_status_reports_close_and_next_candle_local():
    lct = {"BTC/USDT": "2026-07-27T04:00:00+00:00"}
    s = humanize.bot_status(lct, H4_MS, datetime(2026, 7, 27, 8, 32, tzinfo=UTC), WARSAW)
    # closed 08:00 UTC -> 10:00 Warsaw; next due 12:00 UTC -> 14:00 Warsaw
    assert "10:00" in s["text"] and "14:00" in s["text"]


def test_bot_status_truly_stale_is_red():
    lct = {"BTC/USDT": "2026-07-27T04:00:00+00:00"}
    s = humanize.bot_status(lct, H4_MS, datetime(2026, 7, 28, 0, 0, tzinfo=UTC))
    assert not s["ok"] and s["emoji"] == "🔴"


def test_event_line_local_timezone():
    rec = {"kind": "trade_open", "timestamp": "2026-07-25T14:00:00+00:00", "message": "x"}
    assert humanize.event_line(rec, WARSAW)["time"] == "25.07 16:00"
