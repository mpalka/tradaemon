"""The three lines on „Jak to szło" come from one frame and must end together.

„Twój portfel" is drawn by `book_equity_series`, „Wszystko w rynku" by
`buy_hold_curve`, „Tyle w rynku co bot" by `matched_exposure_curve`, and all of
them read the frame `with_live_point` hands them. The first groups on timestamp
alone; the other two pivot on `symbol`. Any row that carries an equity but no price
therefore lands on the bot's line and nowhere else — which is how a dead engine
once rendered as a bot quietly running ahead of the market.

These tests pin that invariant rather than the individual functions, because each
one is defensible alone and the bug only exists between them. Below them sit the
tests for the fair line itself, which follows the bot's exposure bar by bar.
"""

import pandas as pd
import pytest


def _journal(*timestamps: str) -> pd.DataFrame:
    """Two pairs per candle, the shape the engine appends to equity.jsonl."""
    rows = []
    for i, ts in enumerate(timestamps):
        for sym, base in (("BTC/USDT", 100.0), ("ETH/USDT", 10.0)):
            rows.append({"timestamp": ts, "symbol": sym, "close": base * (1 + i),
                         "equity": 1000.0 + i, "cash": 500.0})
    return pd.DataFrame(rows)


def _book(bars: list[tuple[float, float]], equity: float = 1000.0) -> pd.DataFrame:
    """One pair, one bar per (close, exposure) pair — cash back-computed from the
    exposure so the frame reads exactly like the engine's journal."""
    return pd.DataFrame([
        {"timestamp": f"2026-01-{i + 1:02d}T00:00:00+00:00", "symbol": "BTC/USDT",
         "close": close, "equity": equity, "cash": equity * (1.0 - expo)}
        for i, (close, expo) in enumerate(bars)
    ])


def _ends(df: pd.DataFrame) -> tuple:
    from tradaemon.dashboard.app import (
        book_equity_series,
        buy_hold_curve,
        matched_exposure_curve,
    )
    bot = book_equity_series(df)
    bh = buy_hold_curve(df, 1000.0)
    fair = matched_exposure_curve(df, 1000.0)
    return (bot["timestamp"].max(), bh["timestamp"].max(), fair["timestamp"].max())


def test_a_state_with_prices_extends_every_line():
    from tradaemon.dashboard.app import with_live_point

    df = _journal("2026-01-01T00:00:00+00:00", "2026-01-01T04:00:00+00:00")
    out = with_live_point(df, {
        "updated_at": "2026-01-01T06:30:00+00:00", "equity": 1010.0, "cash": 500.0,
        "last_close": {"BTC/USDT": 210.0, "ETH/USDT": 21.0},
    })
    assert len(out) == len(df) + 2          # one row per pair
    bot, bh, fair = _ends(out)
    assert bot == bh == fair
    assert bot == pd.Timestamp("2026-01-01T06:30:00+00:00")


def test_a_state_without_prices_adds_no_point():
    """The reported bug: a crashed engine persists a fresh `updated_at` with an
    empty `last_close`, and the bot's line used to run on past both benchmarks."""
    from tradaemon.dashboard.app import with_live_point

    df = _journal("2026-01-01T00:00:00+00:00", "2026-01-01T04:00:00+00:00")
    out = with_live_point(df, {
        "updated_at": "2026-01-01T06:30:00+00:00", "equity": 1010.0, "cash": 500.0,
        "last_close": {},
    })
    assert len(out) == len(df)
    bot, bh, fair = _ends(out)
    assert bot == bh == fair
    assert bot == pd.Timestamp("2026-01-01T04:00:00+00:00")


def test_partial_prices_still_extend_every_line():
    """A pair missing from `last_close` is carried by `buy_hold_curve`'s ffill, so
    covering some pairs is enough — only covering none is not."""
    from tradaemon.dashboard.app import with_live_point

    df = _journal("2026-01-01T00:00:00+00:00", "2026-01-01T04:00:00+00:00")
    out = with_live_point(df, {
        "updated_at": "2026-01-01T06:30:00+00:00", "equity": 1010.0, "cash": 500.0,
        "last_close": {"BTC/USDT": 210.0},
    })
    assert len(out) == len(df) + 1
    bot, bh, fair = _ends(out)
    assert bot == bh == fair


def test_a_stale_state_does_not_move_the_curves_backwards():
    from tradaemon.dashboard.app import with_live_point

    df = _journal("2026-01-01T00:00:00+00:00", "2026-01-01T04:00:00+00:00")
    out = with_live_point(df, {
        "updated_at": "2026-01-01T02:00:00+00:00", "equity": 1010.0, "cash": 500.0,
        "last_close": {"BTC/USDT": 210.0, "ETH/USDT": 21.0},
    })
    assert out is df   # a candle already closed after 'now'; nothing to fill


def test_the_fair_line_follows_the_exposure_of_each_bar():
    """Raising the risk mid-flight must show up in the benchmark straight away, not
    diluted into an average of the weeks that came before it."""
    from tradaemon.dashboard.app import matched_exposure_curve

    # +10% a bar throughout; the book sits out the first move, then rides half of
    # the second and all of the third.
    curve = matched_exposure_curve(
        _book([(100.0, 0.0), (110.0, 0.5), (121.0, 1.0), (133.1, 1.0)]), 1000.0)
    assert list(curve["equity"]) == pytest.approx([1000.0, 1000.0, 1050.0, 1155.0])


def test_a_bar_entered_flat_cannot_move_the_fair_line():
    """The journal stamps cash at candle close, so the exposure on bar *t* already
    knows how bar *t* went. Reading it unlagged would let the benchmark buy the move
    it is being measured on."""
    from tradaemon.dashboard.app import matched_exposure_curve

    # flat going in, fully invested on the way out, and a +50% bar in between
    curve = matched_exposure_curve(_book([(100.0, 0.0), (150.0, 1.0)]), 1000.0)
    assert list(curve["equity"]) == pytest.approx([1000.0, 1000.0])


def test_the_fair_line_has_the_same_shape_in_every_window():
    """The reason this line is compounded per bar instead of scaled by one average:
    an average is a property of the window, so „7 dni" and „30 dni" used to draw two
    different benchmarks and the comparison flipped between them."""
    from tradaemon.dashboard.app import matched_exposure_curve

    bars = [(100.0, 0.3), (104.0, 0.3), (99.0, 0.9), (108.0, 0.9), (112.0, 0.9)]
    full = matched_exposure_curve(_book(bars), 1000.0).set_index("timestamp")["equity"]
    tail = matched_exposure_curve(_book(bars).tail(3), 1000.0).set_index("timestamp")["equity"]

    assert list(tail.index) == list(full.index[-3:])
    assert (tail / tail.iloc[0]).tolist() == pytest.approx(
        (full[-3:] / full.iloc[-3]).tolist())
