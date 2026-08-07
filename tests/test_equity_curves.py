"""The three lines on „Jak to szło" come from one frame and must end together.

„Twój portfel" is drawn by `book_equity_series`, the two „kup i trzymaj" lines by
`buy_hold_curve`, and both read the frame `with_live_point` hands them. The first
groups on timestamp alone; the second pivots on `symbol`. Any row that carries an
equity but no price therefore lands on the bot's line and nowhere else — which is
how a dead engine once rendered as a bot quietly running ahead of the market.

These tests pin that invariant rather than the individual functions, because each
one is defensible alone and the bug only exists between them.
"""

import pandas as pd


def _journal(*timestamps: str) -> pd.DataFrame:
    """Two pairs per candle, the shape the engine appends to equity.jsonl."""
    rows = []
    for i, ts in enumerate(timestamps):
        for sym, base in (("BTC/USDT", 100.0), ("ETH/USDT", 10.0)):
            rows.append({"timestamp": ts, "symbol": sym, "close": base * (1 + i),
                         "equity": 1000.0 + i, "cash": 500.0})
    return pd.DataFrame(rows)


def _ends(df: pd.DataFrame) -> tuple:
    from trademon.dashboard.app import book_equity_series, buy_hold_curve
    bot = book_equity_series(df)
    bh = buy_hold_curve(df, 1000.0)
    fair = buy_hold_curve(df, 1000.0, exposure=0.25)
    return (bot["timestamp"].max(), bh["timestamp"].max(), fair["timestamp"].max())


def test_a_state_with_prices_extends_every_line():
    from trademon.dashboard.app import with_live_point

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
    from trademon.dashboard.app import with_live_point

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
    from trademon.dashboard.app import with_live_point

    df = _journal("2026-01-01T00:00:00+00:00", "2026-01-01T04:00:00+00:00")
    out = with_live_point(df, {
        "updated_at": "2026-01-01T06:30:00+00:00", "equity": 1010.0, "cash": 500.0,
        "last_close": {"BTC/USDT": 210.0},
    })
    assert len(out) == len(df) + 1
    bot, bh, fair = _ends(out)
    assert bot == bh == fair


def test_a_stale_state_does_not_move_the_curves_backwards():
    from trademon.dashboard.app import with_live_point

    df = _journal("2026-01-01T00:00:00+00:00", "2026-01-01T04:00:00+00:00")
    out = with_live_point(df, {
        "updated_at": "2026-01-01T02:00:00+00:00", "equity": 1010.0, "cash": 500.0,
        "last_close": {"BTC/USDT": 210.0, "ETH/USDT": 21.0},
    })
    assert out is df   # a candle already closed after 'now'; nothing to fill
