"""Tests for the portfolio-manager module: allocator (drift, targeting, trend
filter), cost-aware backtest (reconciliation, benchmark, no look-ahead, cost
impact), book isolation/reconciliation, and the Stooq CSV parser."""

import numpy as np
import pandas as pd
import pytest

from tradaemon.config import CostsConfig
from tradaemon.engine.state import RuntimeStore
from tradaemon.portfolio import allocator
from tradaemon.portfolio.backtest import run_portfolio_backtest
from tradaemon.portfolio.book import PortfolioBook
from tradaemon.portfolio.config import (
    AssetConfig,
    PortfolioConfig,
    RebalanceConfig,
    TrendConfig,
)
from tradaemon.portfolio.data import parse_stooq_csv, parse_yahoo_chart
from tradaemon.portfolio.rebalance import settle_orders

ZERO_COSTS = CostsConfig(taker_fee=0.0, maker_fee=0.0, slippage_bps=0.0)


def make_panel(n=400, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=n, freq="B", tz="UTC")

    def walk(mu, sig, p0):
        return p0 * np.exp(np.cumsum(rng.normal(mu, sig, n)))

    return pd.DataFrame({"SPY": walk(0.0004, 0.01, 400),
                         "TLT": walk(0.0, 0.007, 100),
                         "GLD": walk(0.0002, 0.008, 170)}, index=dates)


def make_cfg(trend=False, **kw) -> PortfolioConfig:
    return PortfolioConfig(
        assets=[AssetConfig(symbol="SPY", target_weight=0.5),
                AssetConfig(symbol="TLT", target_weight=0.3, safe=True),
                AssetConfig(symbol="GLD", target_weight=0.2)],
        initial_capital=10_000.0,
        rebalance=RebalanceConfig(**kw) if kw else RebalanceConfig(),
        trend=TrendConfig(enabled=trend, ma_days=100, safe_asset="TLT"),
    )


# ---------- allocator ----------

def test_base_weights_normalized():
    cfg = PortfolioConfig(assets=[AssetConfig(symbol="A", target_weight=3),
                                  AssetConfig(symbol="B", target_weight=1)])
    assert cfg.base_weights == {"A": 0.75, "B": 0.25}


def test_effective_weights_no_trend_returns_base():
    cfg = make_cfg(trend=False)
    panel = make_panel()
    assert allocator.effective_weights(panel, cfg.base_weights, cfg.trend) == cfg.base_weights


def test_effective_weights_parks_below_ma_in_safe():
    # SPY clearly below its own MA on the last row -> its weight goes to TLT (safe).
    dates = pd.date_range("2022-01-03", periods=150, freq="B", tz="UTC")
    spy = np.concatenate([np.full(120, 400.0), np.linspace(400, 250, 30)])
    panel = pd.DataFrame({"SPY": spy, "TLT": np.full(150, 100.0),
                          "GLD": np.full(150, 170.0)}, index=dates)
    cfg = make_cfg(trend=True)
    eff = allocator.effective_weights(panel, cfg.base_weights, cfg.trend, "TLT")
    assert eff["SPY"] == 0.0
    assert eff["TLT"] == pytest.approx(0.8)  # 0.3 + parked 0.5
    assert eff["GLD"] == pytest.approx(0.2)


def test_effective_weights_insufficient_history_returns_base():
    cfg = make_cfg(trend=True)  # ma_days=100
    short = make_panel(n=50)
    assert allocator.effective_weights(short, cfg.base_weights, cfg.trend, "TLT") == cfg.base_weights


def test_rebalance_orders_reach_targets_without_costs():
    prices = {"SPY": 400.0, "TLT": 100.0, "GLD": 170.0}
    holdings = {"SPY": 0.0, "TLT": 0.0, "GLD": 0.0}
    cash = 10_000.0
    targets = {"SPY": 0.5, "TLT": 0.3, "GLD": 0.2}
    orders = allocator.rebalance_orders(holdings, cash, prices, targets)
    cash, _ = settle_orders(orders, holdings, cash, prices, ZERO_COSTS, "t0")
    w = allocator.current_weights(holdings, cash, prices)
    for s, tgt in targets.items():
        assert w[s] == pytest.approx(tgt, abs=1e-6)
    assert cash == pytest.approx(0.0, abs=1e-6)


def test_should_rebalance_threshold_and_cadence():
    reb = RebalanceConfig(cadence_days=90, drift_threshold_pct=5.0)
    assert not allocator.should_rebalance(days_since_last=10, max_drift=2.0, rebalance=reb)
    assert allocator.should_rebalance(days_since_last=10, max_drift=6.0, rebalance=reb)
    assert allocator.should_rebalance(days_since_last=90, max_drift=0.0, rebalance=reb)


def test_max_drift_pct():
    prices = {"A": 1.0, "B": 1.0}
    holdings = {"A": 60.0, "B": 40.0}  # 60/40
    drift = allocator.max_drift_pct(holdings, 0.0, prices, {"A": 0.5, "B": 0.5})
    assert drift == pytest.approx(10.0)


# ---------- backtest ----------

def test_backtest_reconciles_and_has_benchmark():
    cfg = make_cfg()
    r = run_portfolio_backtest(make_panel(), cfg)
    s = r["summary"]
    assert r["equity"].iloc[0] > 0 and r["equity"].iloc[-1] > 0
    assert len(r["benchmark"]) == len(r["equity"])
    assert {"total_return_pct", "benchmark_return_pct", "excess_return_pct",
            "sharpe", "max_drawdown_pct", "n_rebalances"} <= set(s)
    assert s["n_rebalances"] >= 1
    assert s["fees_paid"] > 0  # default costs charged on rebalances


def test_backtest_costs_reduce_return():
    cfg = make_cfg(cadence_days=20)  # rebalance often -> costs bite
    panel = make_panel()
    with_costs = run_portfolio_backtest(panel, cfg)["summary"]["final_equity"]
    cfg_free = cfg.model_copy(update={"costs": ZERO_COSTS})
    without = run_portfolio_backtest(panel, cfg_free)["summary"]["final_equity"]
    assert without > with_costs


def test_backtest_no_lookahead():
    """Crashing the final day must not change any earlier equity point."""
    cfg = make_cfg(trend=True, cadence_days=30, drift_threshold_pct=5.0)
    panel = make_panel()
    r1 = run_portfolio_backtest(panel, cfg)
    panel2 = panel.copy()
    panel2.iloc[-1] = panel2.iloc[-1] * 0.5  # halve the last day's prices
    r2 = run_portfolio_backtest(panel2, cfg)
    pd.testing.assert_series_equal(r1["equity"].iloc[:-1], r2["equity"].iloc[:-1])


# ---------- book ----------

def _feed(book: PortfolioBook, panel: pd.DataFrame) -> None:
    for i, d in enumerate(panel.index):
        prices = {s: float(panel.iloc[i][s]) for s in book.symbols}
        book.on_day(d.to_pydatetime(), prices, panel.iloc[: i + 1])


def test_book_reconciles(tmp_path):
    cfg = make_cfg()
    book = PortfolioBook("core", cfg, RuntimeStore(tmp_path / "core"))
    panel = make_panel(n=250)
    _feed(book, panel)
    recon = book.cash + sum(book.holdings[s] * book.last_close[s] for s in book.symbols)
    assert book.equity() == pytest.approx(recon, abs=1e-6)
    assert (tmp_path / "core" / "state.json").exists()
    assert (tmp_path / "core" / "trades.jsonl").exists()


def test_two_books_isolated(tmp_path):
    cfg_a = make_cfg(cadence_days=20)
    cfg_b = make_cfg(cadence_days=200)
    a = PortfolioBook("a", cfg_a, RuntimeStore(tmp_path / "a"))
    b = PortfolioBook("b", cfg_b, RuntimeStore(tmp_path / "b"))
    panel = make_panel(n=250)
    for i, d in enumerate(panel.index):
        prices = {s: float(panel.iloc[i][s]) for s in cfg_a.symbols}
        a.on_day(d.to_pydatetime(), prices, panel.iloc[: i + 1])
        b.on_day(d.to_pydatetime(), prices, panel.iloc[: i + 1])
    # different cadence -> different number of rebalances -> separate files
    ta = (tmp_path / "a" / "trades.jsonl").read_text().count("\n")
    tb = (tmp_path / "b" / "trades.jsonl").read_text().count("\n")
    assert ta != tb
    assert a.store.runtime_dir != b.store.runtime_dir


# ---------- data ----------

def test_parse_stooq_csv():
    csv = ("Date,Open,High,Low,Close,Volume\n"
           "2020-01-02,100,101,99,100.5,1000\n"
           "2020-01-03,100.5,102,100,101.5,1200\n")
    df = parse_stooq_csv(csv)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == pytest.approx(101.5)
    assert str(df["timestamp"].dt.tz) == "UTC"


def test_parse_stooq_csv_without_volume():
    csv = "Date,Open,High,Low,Close\n2020-01-02,100,101,99,100.5\n"
    df = parse_stooq_csv(csv)
    assert df["volume"].iloc[0] == 0.0


def test_parse_yahoo_chart():
    payload = {"chart": {"error": None, "result": [{
        "timestamp": [1577972580, 1578058980],  # 2020-01-02, 2020-01-03 (market open)
        "indicators": {"quote": [{
            "open": [100.0, 100.5], "high": [101.0, 102.0],
            "low": [99.0, 100.0], "close": [100.5, 101.5],
            "volume": [1000, 1200]}]},
    }]}}
    df = parse_yahoo_chart(payload)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == pytest.approx(101.5)
    # normalized to the UTC date (midnight), so the daily key is clean
    assert df["timestamp"].iloc[0] == pd.Timestamp("2020-01-02", tz="UTC")


def test_parse_yahoo_chart_drops_nan_days():
    payload = {"chart": {"error": None, "result": [{
        "timestamp": [1577972580, 1578058980],
        "indicators": {"quote": [{
            "open": [100.0, None], "high": [101.0, None], "low": [99.0, None],
            "close": [100.5, None], "volume": [1000, None]}]},
    }]}}
    assert len(parse_yahoo_chart(payload)) == 1
