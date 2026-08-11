"""Tests for the instrument price preview (dashboard/price_view.py).

Streamlit rendering is not exercised here; what is worth pinning is the data
plumbing behind the click — which slice of history is shown, what the hover
tooltip says, and how the two trade journals map onto the same chart marks.
"""

import pandas as pd
import pytest

from trademon.dashboard import price_view as pv


@pytest.fixture
def prices():
    """90 days of daily closes ending 2026-08-05, rising 100 -> 190."""
    ts = pd.date_range("2026-05-08", "2026-08-05", freq="D", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "close": [100.0 + i for i in range(len(ts))]})


# ---------- selection ----------

def test_clicking_a_second_instrument_swaps_the_preview():
    first = pv.next_selection(None, "BTC/USDT", "crypto_pos")
    assert first == {"symbol": "BTC/USDT", "section": "crypto_pos", "at": None,
                     "item": None}
    assert pv.next_selection(first, "ETH/USDT", "crypto_pos")["symbol"] == "ETH/USDT"


def test_clicking_the_open_instrument_again_closes_it():
    sel = pv.next_selection(None, "BTC/USDT", "crypto_pos")
    assert pv.next_selection(sel, "BTC/USDT", "crypto_pos") is None


def test_the_same_pair_in_another_row_moves_the_preview():
    """Two LTC events in the log are two places to draw the chart, not a toggle."""
    first = pv.next_selection(None, "LTC/USDT", "crypto_ev", at="2026-08-04T22:00:00",
                              item="ev_3_LTC/USDT")
    second = pv.next_selection(first, "LTC/USDT", "crypto_ev", at="2026-08-04T02:00:00",
                               item="ev_7_LTC/USDT")
    assert second is not None
    assert second["item"] == "ev_7_LTC/USDT"
    assert second["at"] == "2026-08-04T02:00:00"


def test_clicking_the_same_row_twice_closes_it():
    sel = pv.next_selection(None, "LTC/USDT", "crypto_ev", item="ev_3_LTC/USDT")
    assert pv.next_selection(sel, "LTC/USDT", "crypto_ev", item="ev_3_LTC/USDT") is None


def test_selected_answers_only_the_row_that_was_clicked(monkeypatch):
    """Each row asks "is it me?" — exactly one may say yes, or the chart would be
    drawn under every event of that instrument."""
    sel = {"symbol": "LTC/USDT", "section": "crypto_ev", "at": None,
           "item": "ev_3_LTC/USDT"}
    monkeypatch.setattr(pv.st, "session_state", {pv._KEY: sel})
    assert pv.selected("crypto_ev", "ev_3_LTC/USDT") == sel
    assert pv.selected("crypto_ev", "ev_7_LTC/USDT") is None
    assert pv.selected("crypto_pos", "ev_3_LTC/USDT") is None
    assert pv.selected("crypto_ev") == sel   # the section owner, e.g. position tiles


def test_the_same_pair_in_another_section_is_a_different_selection():
    sel = pv.next_selection(None, "BTC/USDT", "crypto_pos")
    other = pv.next_selection(sel, "BTC/USDT", "crypto_ev", at="2026-08-01T00:00:00+00:00")
    assert other["section"] == "crypto_ev"
    assert other["at"] == "2026-08-01T00:00:00+00:00"


# ---------- window ----------

def test_window_keeps_only_the_requested_days(prices):
    win = pv.window(prices, 7)
    assert len(win) == 8  # 7 days back, inclusive of both ends
    assert win["timestamp"].min() == pd.Timestamp("2026-07-29", tz="UTC")


def test_window_widens_to_reach_an_older_event(prices):
    """An event from six weeks ago must not open on a chart that starts last week."""
    win = pv.window(prices, 7, at="2026-06-20T12:00:00+00:00")
    assert win["timestamp"].min() <= pd.Timestamp("2026-06-20T12:00:00", tz="UTC")
    assert len(win) > 40


def test_window_survives_an_empty_frame():
    assert pv.window(pd.DataFrame(), 7).empty


# ---------- tooltip numbers ----------

def test_pct_change_measures_the_last_hours(prices):
    assert pv.pct_change(prices, 24) == pytest.approx((189 / 188 - 1) * 100)


def test_pct_change_is_none_when_history_is_too_short(prices):
    assert pv.pct_change(prices.tail(2), 24 * 7) is None
    assert pv.pct_change(prices.tail(1), 24) is None


def test_summary_reads_as_a_sentence(prices):
    text = pv.summary(prices)
    assert "teraz" in text and "24 h +" in text and "7 dni +" in text
    assert "Kliknij" in text


def test_summary_without_data_says_so():
    assert "Brak" in pv.summary(pd.DataFrame(columns=["timestamp", "close"]))


def test_summary_marks_unknown_changes_with_a_dash(prices):
    assert "7 dni —" in pv.summary(prices.tail(2))


def test_pct_change_accepts_a_prepared_timestamp_column(prices):
    """`summary` parses once and passes the column to both horizons; the answer must
    not depend on who did the parsing."""
    ts = pd.to_datetime(prices["timestamp"], utc=True)
    assert pv.pct_change(prices, 24, ts=ts) == pv.pct_change(prices, 24)
    assert pv.pct_change(prices, 24 * 7, ts=ts) == pv.pct_change(prices, 24 * 7)


def test_summary_ignores_history_older_than_its_lookback():
    """The tooltip runs on a tail slice to keep `pd.to_datetime` off years of stored
    candles. On a history longer than that tail it must still read the same numbers
    the full frame gives — the slice bounds the lookback, not the answer."""
    ts = pd.date_range(end="2026-08-05", periods=pv.SUMMARY_TAIL * 3, freq="D", tz="UTC")
    long = pd.DataFrame({"timestamp": ts,
                         "close": [100.0 + i for i in range(len(ts))]})
    assert len(long) > pv.SUMMARY_TAIL

    text = pv.summary(long)
    for hours in (24, 24 * 7):
        # the reference: the same question asked of every row there is
        expected = pv.pct_change(long, hours)
        assert f"{expected:+.1f}%" in text


def test_summary_survives_a_history_shorter_than_the_tail(prices):
    """A young pair has fewer rows than the slice asks for; tail() must not invent any."""
    assert pv.summary(prices.tail(3)).startswith("teraz")


# ---------- per-render caches ----------

def test_tooltips_builds_one_summary_per_instrument():
    """The event journal repeats a handful of pairs across sixty rows. Sixty lookups
    of eleven instruments must cost eleven derivations, not sixty."""
    calls = []

    def prices_for(symbol):
        calls.append(symbol)
        return pd.DataFrame({"timestamp": pd.date_range("2026-08-01", periods=10,
                                                        freq="4h", tz="UTC"),
                             "close": [100.0] * 10})

    tooltip = pv.tooltips(prices_for)
    rows = ["BTC/USDT", "ETH/USDT", "BTC/USDT", "LTC/USDT", "BTC/USDT", "ETH/USDT"]
    texts = [tooltip(sym) for sym in rows]

    assert calls == ["BTC/USDT", "ETH/USDT", "LTC/USDT"]
    assert texts[0] == texts[2] == texts[4]   # same pair, same sentence


def test_memoized_reads_each_instrument_once():
    calls = []

    def prices_for(symbol):
        calls.append(symbol)
        return pd.DataFrame({"timestamp": [], "close": []})

    cached = pv.memoized(prices_for)
    cached("SPY"), cached("TLT"), cached("SPY"), cached("SPY")
    assert calls == ["SPY", "TLT"]


# ---------- trade marks ----------

def test_trade_points_splits_a_crypto_round_trip_into_two_marks():
    trades = pd.DataFrame([{
        "symbol": "BTC/USDT", "entry_time": "2026-07-01T00:00:00+00:00",
        "exit_time": "2026-07-03T00:00:00+00:00",
        "entry_price": 60000.0, "exit_price": 61000.0,
    }])
    pts = pv.trade_points(trades, "BTC/USDT")
    assert list(pts["typ"]) == [pv.ENTRY, pv.EXIT]
    assert list(pts["price"]) == [60000.0, 61000.0]


def test_trade_points_keeps_a_still_open_crypto_position():
    trades = pd.DataFrame([{
        "symbol": "BTC/USDT", "entry_time": "2026-07-01T00:00:00+00:00",
        "exit_time": None, "entry_price": 60000.0, "exit_price": None,
    }])
    pts = pv.trade_points(trades, "BTC/USDT")
    assert list(pts["typ"]) == [pv.ENTRY]


def test_trade_points_maps_the_portfolio_journal():
    trades = pd.DataFrame([
        {"symbol": "GLD", "timestamp": "2026-05-26T00:00:00+00:00", "side": "buy",
         "price": 414.0},
        {"symbol": "GLD", "timestamp": "2026-06-26T00:00:00+00:00", "side": "sell",
         "price": 420.0},
        {"symbol": "TLT", "timestamp": "2026-05-26T00:00:00+00:00", "side": "buy",
         "price": 85.0},
    ])
    pts = pv.trade_points(trades, "GLD")
    assert list(pts["typ"]) == [pv.ENTRY, pv.EXIT]
    assert list(pts["price"]) == [414.0, 420.0]  # TLT filtered out


def test_trade_points_clips_to_the_visible_window():
    trades = pd.DataFrame([
        {"symbol": "BTC/USDT", "entry_time": "2026-01-01T00:00:00+00:00",
         "exit_time": "2026-01-02T00:00:00+00:00",
         "entry_price": 40000.0, "exit_price": 41000.0},
        {"symbol": "BTC/USDT", "entry_time": "2026-07-01T00:00:00+00:00",
         "exit_time": "2026-07-03T00:00:00+00:00",
         "entry_price": 60000.0, "exit_price": 61000.0},
    ])
    pts = pv.trade_points(trades, "BTC/USDT", start="2026-06-01T00:00:00+00:00",
                          end="2026-08-01T00:00:00+00:00")
    assert len(pts) == 2
    assert pts["timestamp"].min() >= pd.Timestamp("2026-06-01", tz="UTC")


def test_trade_points_without_a_journal():
    assert pv.trade_points(None, "BTC/USDT").empty
    assert pv.trade_points(pd.DataFrame(), "BTC/USDT").empty


# ---------- the position still open ----------
#
# The scalper journals a round trip only when it closes, so what the bot is
# holding right now lives in state.json and nowhere else. Drawing the journal
# alone made the chart contradict the card above it.

def test_a_held_position_with_no_closed_trades_still_gets_a_mark():
    """The LINK case: bought and never sold, so the journal has nothing at all
    and the chart came out completely bare."""
    pos = {"entry_time": "2026-08-08T00:00:00+00:00", "entry_price": 8.26}
    pts = pv.open_position_point(pos)
    assert list(pts["typ"]) == [pv.HELD]
    assert list(pts["price"]) == [8.26]


def test_a_held_position_follows_the_exit_it_was_reopened_after():
    """The LTC case: the timeout closed and reopened on one candle, so the last
    thing drawn was a red exit triangle for a pair the bot was still holding."""
    trades = pd.DataFrame([{
        "symbol": "LTC/USDT", "entry_time": "2026-08-04T20:00:00+00:00",
        "exit_time": "2026-08-06T20:00:00+00:00",
        "entry_price": 44.86, "exit_price": 45.55,
    }])
    pos = {"entry_time": "2026-08-06T20:00:00+00:00", "entry_price": 45.46}
    marks = pd.concat([pv.trade_points(trades, "LTC/USDT"),
                       pv.open_position_point(pos)], ignore_index=True)
    marks = marks.sort_values("timestamp")
    assert list(marks["typ"]) == [pv.ENTRY, pv.EXIT, pv.HELD]
    assert marks["typ"].iloc[-1] == pv.HELD   # the story no longer ends on an exit


def test_the_newest_fills_survive_a_price_history_that_stopped_earlier():
    """Why the chart "did not show the last entries".

    The candle downloader runs weekly and the bot trades every candle, so fills
    routinely land after the last stored price. Marks used to be clipped to the
    price window's right edge, which dropped exactly those.
    """
    trades = pd.DataFrame([{
        "symbol": "BTC/USDT", "entry_time": "2026-08-09T04:00:00+00:00",
        "exit_time": None, "entry_price": 65000.0, "exit_price": None,
    }])
    pos = {"entry_time": "2026-08-09T04:00:00+00:00", "entry_price": 65000.0}
    # the stored candles end two days before both
    marks = pv.chart_marks(trades, "BTC/USDT", pos, start="2026-08-02T00:00:00+00:00")
    assert list(marks["typ"]) == [pv.ENTRY, pv.HELD]


def test_chart_marks_still_clips_the_range_the_reader_chose():
    trades = pd.DataFrame([{
        "symbol": "BTC/USDT", "entry_time": "2026-01-01T00:00:00+00:00",
        "exit_time": "2026-01-02T00:00:00+00:00",
        "entry_price": 40000.0, "exit_price": 41000.0,
    }])
    assert pv.chart_marks(trades, "BTC/USDT", None,
                          start="2026-08-01T00:00:00+00:00").empty


def test_a_held_position_outside_the_window_is_not_drawn():
    pos = {"entry_time": "2026-01-01T00:00:00+00:00", "entry_price": 40000.0}
    assert pv.open_position_point(pos, start="2026-06-01T00:00:00+00:00",
                                  end="2026-08-01T00:00:00+00:00").empty


def test_no_position_or_a_broken_one_draws_nothing():
    """Never raises: this runs while the panel is drawing, where a blank chart
    beats a stack trace."""
    assert pv.open_position_point(None).empty
    assert pv.open_position_point({}).empty
    assert pv.open_position_point({"entry_price": 45.0}).empty              # no time
    assert pv.open_position_point({"entry_time": "2026-08-08T00:00:00+00:00"}).empty
    assert pv.open_position_point({"entry_time": "nie-data", "entry_price": 1.0}).empty


# ---------- price sources ----------

def test_closes_returns_an_empty_frame_for_a_missing_file(tmp_path):
    assert pv.closes(tmp_path / "never-downloaded.parquet").empty


def test_crypto_prices_falls_back_to_the_equity_journal(monkeypatch, tmp_path):
    """A pair can be traded before its Parquet file exists; the engine journals the
    closes it used, and that is better than an empty chart."""
    monkeypatch.setattr(pv.cfg.paths, "data_dir", tmp_path)
    equity = pd.DataFrame([
        {"timestamp": "2026-08-05T12:00:00+00:00", "symbol": "BTC/USDT", "close": 64388.0},
        {"timestamp": "2026-08-05T12:00:00+00:00", "symbol": "ETH/USDT", "close": 1917.4},
    ])
    out = pv.crypto_prices("ETH/USDT", equity)
    assert list(out["close"]) == [1917.4]
    assert pv.crypto_prices("SOL/USDT", equity).empty


def test_crypto_prices_extends_stale_candles_with_the_engines_own_closes(monkeypatch,
                                                                        tmp_path):
    """The downloader runs weekly, the bot trades every candle. A chart that stops
    where the Parquet stops is days behind the trades drawn on top of it."""
    monkeypatch.setattr(pv.cfg.paths, "data_dir", tmp_path)
    stored = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-08-05T12:00:00+00:00",
                                     "2026-08-05T16:00:00+00:00"], utc=True),
        "close": [64000.0, 64200.0],
    })
    monkeypatch.setattr(pv, "closes", lambda path: stored.copy())
    equity = pd.DataFrame([
        # already covered by the Parquet — must not be duplicated
        {"timestamp": "2026-08-05T16:00:00+00:00", "symbol": "BTC/USDT", "close": 64200.0},
        {"timestamp": "2026-08-07T20:00:00+00:00", "symbol": "BTC/USDT", "close": 64900.0},
        {"timestamp": "2026-08-07T20:00:00+00:00", "symbol": "ETH/USDT", "close": 1917.4},
    ])
    out = pv.crypto_prices("BTC/USDT", equity)
    assert list(out["close"]) == [64000.0, 64200.0, 64900.0]
    assert str(out["timestamp"].iloc[-1]) == "2026-08-07 20:00:00+00:00"
