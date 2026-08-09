"""What the engine records when the position limit turns an opportunity away.

The limit itself is covered in test_risk.py. What is covered here is the *reason*
the panel shows next to it: the engine used to check the cap before asking the
model, so a blocked pair had no probability to report and every idle pair on a
full book was filed under "risk_blocked" — including pairs that were nowhere near
the threshold and would not have opened anyway.
"""

import pandas as pd
import pytest

from trademon.engine.loop import Book
from trademon.engine.state import RuntimeStore
from trademon.execution.executors import PaperExecutor

from .conftest import FakeBundle, make_ohlcv


@pytest.fixture
def book(cfg, tmp_path):
    cfg.exchange.symbols = ["BTC/USDT", "ETH/USDT"]
    cfg.risk.max_open_positions = 1
    return Book("default", cfg, FakeBundle(prob=0.99), PaperExecutor(cfg),
                RuntimeStore(tmp_path / "runtime"))


def feed(book: Book, symbol: str, df: pd.DataFrame) -> None:
    for _, row in df.iterrows():
        book.on_candle(symbol, row.to_dict())


def fill_the_book(book: Book, cfg) -> None:
    feed(book, "BTC/USDT", make_ohlcv(cfg.strategy.warmup_bars + 5, seed=3))
    assert list(book.positions) == ["BTC/USDT"]


def test_blocked_pair_reports_the_probability_it_was_denied(book, cfg):
    fill_the_book(book, cfg)
    feed(book, "ETH/USDT", make_ohlcv(cfg.strategy.warmup_bars + 5, seed=4))

    assert list(book.positions) == ["BTC/USDT"]        # the cap held
    sig = book.signals["ETH/USDT"]
    assert sig["reason"] == "risk_blocked"
    assert "max_open_positions" in sig["detail"]
    # the point of the change: the panel can now say how big an opportunity the
    # limit turned away, instead of showing an empty probability
    assert sig["p_long"] == pytest.approx(0.99)
    assert sig["side"] == "long"


def test_a_full_book_is_not_blamed_for_a_pair_that_had_no_signal(book, cfg):
    fill_the_book(book, cfg)
    book.bundles = {"long": FakeBundle(prob=0.10)}     # ETH is not a candidate
    feed(book, "ETH/USDT", make_ohlcv(cfg.strategy.warmup_bars + 5, seed=4))

    sig = book.signals["ETH/USDT"]
    assert sig["reason"] == "below_threshold"
    assert sig["p_long"] == pytest.approx(0.10)


def test_the_limit_still_gates_the_entry(book, cfg):
    """Diagnostics only — asking the model earlier must not let a trade through."""
    fill_the_book(book, cfg)
    cash_before = book.cash
    feed(book, "ETH/USDT", make_ohlcv(cfg.strategy.warmup_bars + 5, seed=4))
    assert "ETH/USDT" not in book.positions
    assert book.cash == cash_before
