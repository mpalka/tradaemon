"""Tests for the phase-2 laboratory features: multi-book A/B isolation,
Sharpe annualization, and the experiment log."""

import json

import numpy as np
import pandas as pd
import pytest

from trademon.backtest.metrics import periods_per_year, sharpe_ratio
from trademon.config import VariantConfig
from trademon.engine.loop import Book, build_books
from trademon.engine.state import RuntimeStore
from trademon.execution.executors import PaperExecutor
from trademon.research.log import load_experiments, log_experiment

from .conftest import FakeBundle, make_ohlcv


def feed(book: Book, df: pd.DataFrame, symbol="BTC/USDT") -> None:
    for _, row in df.iterrows():
        book.on_candle(symbol, row.to_dict())


def test_periods_per_year_matches_timeframe():
    assert periods_per_year("4h") == pytest.approx(2190.0)
    assert periods_per_year("1h") == pytest.approx(8760.0)
    assert periods_per_year("1m") == pytest.approx(525600.0)


def test_sharpe_scales_with_annualization():
    eq = pd.Series(np.linspace(1000, 1010, 50) + np.sin(np.arange(50)))
    s_4h = sharpe_ratio(eq, periods_per_year("4h"))
    s_1m = sharpe_ratio(eq, periods_per_year("1m"))
    # same series, different annualization -> 1m factor is sqrt(240x) larger
    assert s_1m > s_4h
    assert s_1m / s_4h == pytest.approx(np.sqrt(525600 / 2190), rel=1e-6)


def test_build_books_default_and_variants(cfg):
    cfg.exchange.symbols = ["BTC/USDT"]
    assert [b.name for b in build_books(cfg, FakeBundle(), PaperExecutor(cfg))] == ["default"]

    cfg.variants = [VariantConfig(name="agresywny", prob_threshold=0.50),
                    VariantConfig(name="ostrozny", prob_threshold=0.70)]
    books = build_books(cfg, FakeBundle(), PaperExecutor(cfg))
    assert [b.name for b in books] == ["agresywny", "ostrozny"]
    assert books[0].cfg.strategy.prob_threshold == 0.50
    assert books[1].cfg.strategy.prob_threshold == 0.70
    # each book has its own runtime namespace
    assert books[0].store.runtime_dir != books[1].store.runtime_dir


def test_books_are_isolated_on_same_candles(cfg, tmp_path):
    """Two variants fed identical candles keep separate portfolios and files."""
    cfg.exchange.symbols = ["BTC/USDT"]
    trade_all = Book("all", cfg, FakeBundle(prob=0.99),
                     PaperExecutor(cfg), RuntimeStore(tmp_path / "all"))
    trade_none = Book("none", cfg, FakeBundle(prob=0.0),
                      PaperExecutor(cfg), RuntimeStore(tmp_path / "none"))

    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    for _, row in df.iterrows():
        bar = row.to_dict()
        trade_all.on_candle("BTC/USDT", bar)
        trade_none.on_candle("BTC/USDT", bar)

    assert trade_all.positions and not trade_none.positions
    assert trade_all.cash < cfg.paper.initial_capital
    assert trade_none.cash == pytest.approx(cfg.paper.initial_capital)
    # separate state files, no cross-contamination
    assert (tmp_path / "all" / "state.json").exists()
    assert (tmp_path / "none" / "state.json").exists()
    assert json.loads((tmp_path / "none" / "state.json").read_text())["positions"] == {}


def test_signals_recorded_for_why_no_trade(cfg, tmp_path):
    book = Book("default", cfg, FakeBundle(prob=0.0),
               PaperExecutor(cfg), RuntimeStore(tmp_path / "r"))
    feed(book, make_ohlcv(cfg.strategy.warmup_bars + 5))
    sig = book.signals["BTC/USDT"]
    assert sig["reason"] == "below_threshold"
    assert sig["p_long"] == pytest.approx(0.0)
    assert sig["threshold"] == cfg.strategy.prob_threshold


def test_trade_writes_alert(cfg, tmp_path):
    store = RuntimeStore(tmp_path / "r")
    book = Book("default", cfg, FakeBundle(prob=0.99), PaperExecutor(cfg), store)
    feed(book, make_ohlcv(cfg.strategy.warmup_bars + 5))
    alerts = [json.loads(x) for x in store.alerts_path.read_text().splitlines()]
    assert any(a["kind"] == "trade_open" for a in alerts)


def test_experiment_log_round_trip(tmp_path):
    log_experiment(tmp_path, {"kind": "backtest", "mean_return_pct": -0.18, "pairs": 10})
    log_experiment(tmp_path, {"kind": "sweep", "mean_return_pct": 0.05})
    rows = load_experiments(tmp_path)
    assert len(rows) == 2
    assert rows[0]["kind"] == "backtest"
    assert "timestamp" in rows[0]
