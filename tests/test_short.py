import json

import numpy as np
import pandas as pd
import pytest

from trademon.backtest.runner import run_backtest
from trademon.engine.loop import Book
from trademon.engine.state import RuntimeStore
from trademon.execution.executors import PaperExecutor
from trademon.execution.fills import check_bracket_exit
from trademon.features.engineering import FEATURE_COLUMNS
from trademon.labeling.triple_barrier import triple_barrier_labels

from .conftest import FakeBundle, make_ohlcv
from .test_labeling import make_flat_df


def short_labels(df, horizon=5):
    atr = pd.Series(1.0, index=df.index)  # short: tp = entry-2, sl = entry+1
    return triple_barrier_labels(df, atr, 2.0, 1.0, horizon, direction="short")


def test_short_label_one_when_price_falls_first():
    df = make_flat_df(20)
    df.loc[3, "low"] = 97.5  # falls through the short take-profit (98)
    out = short_labels(df)
    assert out.loc[1, "label"] == 1.0
    assert out.loc[2, "label"] == 1.0


def test_short_label_zero_when_price_rises_first():
    df = make_flat_df(20)
    df.loc[3, "high"] = 101.5  # rises through the short stop (101)
    df.loc[5, "low"] = 97.5    # falls only later
    out = short_labels(df)
    assert out.loc[1, "label"] == 0.0


def test_short_same_bar_both_barriers_is_conservative_sl():
    df = make_flat_df(20)
    df.loc[3, "high"] = 102.0
    df.loc[3, "low"] = 97.0
    out = short_labels(df)
    assert out.loc[2, "label"] == 0.0


def test_long_and_short_labels_are_mirrored_on_mirrored_data():
    """Shorting a falling market == going long the mirrored rising market."""
    df = make_ohlcv(300, seed=11)
    mirrored = df.copy()
    # mirror prices around a constant: up-moves become down-moves
    c = 2 * float(df["close"].iloc[0])
    mirrored["open"] = c - df["open"]
    mirrored["close"] = c - df["close"]
    mirrored["high"] = c - df["low"]   # high/low swap under mirroring
    mirrored["low"] = c - df["high"]
    atr = pd.Series(1.0, index=df.index)
    long_on_mirror = triple_barrier_labels(mirrored, atr, 2.0, 1.0, 5, direction="long")
    short_on_orig = triple_barrier_labels(df, atr, 2.0, 1.0, 5, direction="short")
    valid = long_on_mirror["label"].notna() & short_on_orig["label"].notna()
    np.testing.assert_array_equal(
        long_on_mirror.loc[valid, "label"].to_numpy(),
        short_on_orig.loc[valid, "label"].to_numpy(),
    )


def test_check_bracket_exit_short_directions():
    # short: tp below entry, sl above
    assert check_bracket_exit(100.5, 97.5, tp=98.0, sl=101.0, direction="short") == "tp"
    assert check_bracket_exit(101.5, 99.5, tp=98.0, sl=101.0, direction="short") == "sl"
    assert check_bracket_exit(100.5, 99.5, tp=98.0, sl=101.0, direction="short") is None
    # both in one bar -> conservative stop
    assert check_bracket_exit(101.5, 97.5, tp=98.0, sl=101.0, direction="short") == "sl"


class SidedFakeBundle(FakeBundle):
    feature_columns = FEATURE_COLUMNS


def test_backtest_long_short_trades_both_sides(cfg):
    cfg.strategy.direction = "long_short"
    df = make_ohlcv(2000, seed=9)
    bundles = {"long": FakeBundle(prob=0.99), "short": FakeBundle(prob=0.0)}
    only_long = run_backtest(df, bundles, cfg, "BTC/USDT")
    assert (only_long["trades"]["side"] == "long").all()

    bundles = {"long": FakeBundle(prob=0.0), "short": FakeBundle(prob=0.99)}
    only_short = run_backtest(df, bundles, cfg, "BTC/USDT")
    assert len(only_short["trades"]) > 0
    assert (only_short["trades"]["side"] == "short").all()
    s = only_short["summary"]
    assert s["gross_pnl"] - s["fees_paid"] == pytest.approx(s["net_pnl"])


def test_short_trades_are_filed_under_the_short_probability(cfg):
    """Both sides clear the threshold and the short one wins. The recorded
    probability must be the short model's, not the long model's.

    The long branch runs first and leaves its number behind; until the trade record
    existed nothing read it afterwards, so a short could quietly be filed under
    p_long. That would have inverted the very measurement this column is for.
    """
    cfg.strategy.direction = "long_short"
    df = make_ohlcv(2000, seed=9)
    bundles = {"long": FakeBundle(prob=0.65), "short": FakeBundle(prob=0.85)}
    trades = run_backtest(df, bundles, cfg, "BTC/USDT")["trades"]
    assert len(trades) > 0
    assert (trades["side"] == "short").all()
    assert trades["prob"].eq(0.85).all()


def test_backtest_short_profits_in_falling_market(cfg):
    """A strongly falling series must be profitable for an always-short bot
    (gross of fees) and the accounting identity must hold."""
    cfg.strategy.direction = "long_short"
    n = 600
    ts = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    price = 100.0 * np.exp(np.linspace(0, -0.5, n))  # steady -39% decline
    rng = np.random.default_rng(1)
    df = pd.DataFrame(
        {"timestamp": ts, "open": price, "high": price * 1.001,
         "low": price * 0.999, "close": price,
         "volume": rng.uniform(10, 100, n)}  # varied, else volume_z is NaN
    )
    bundles = {"long": FakeBundle(prob=0.0), "short": FakeBundle(prob=0.99)}
    result = run_backtest(df, bundles, cfg, "BTC/USDT")
    assert result["summary"]["n_trades"] > 0
    assert result["summary"]["net_pnl"] > 0  # falling market, short must win


def test_engine_opens_and_closes_short(cfg, tmp_path):
    cfg.exchange.symbols = ["BTC/USDT"]
    cfg.strategy.direction = "long_short"
    store = RuntimeStore(tmp_path / "runtime")
    bundles = {"long": FakeBundle(prob=0.0), "short": FakeBundle(prob=0.99)}
    engine = Book("default", cfg, bundles, PaperExecutor(cfg), store)

    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    for _, row in df.iterrows():
        engine.on_candle("BTC/USDT", row.to_dict())
    pos = engine.positions["BTC/USDT"]
    assert pos.side == "short"
    assert pos.tp < pos.entry_price < pos.sl  # mirrored barriers

    engine.bundles = {"long": FakeBundle(prob=0.0), "short": FakeBundle(prob=0.0)}
    last = df.iloc[-1]
    tp_bar = {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": last["close"], "high": last["close"] * 1.0001,
        "low": pos.tp * 0.999, "close": pos.tp, "volume": 10.0,
    }
    engine.on_candle("BTC/USDT", tp_bar)
    assert "BTC/USDT" not in engine.positions
    trades = [json.loads(x) for x in store.trades_path.read_text().splitlines()]
    assert trades[-1]["side"] == "short"
    assert trades[-1]["exit_reason"] == "tp"
    assert trades[-1]["pnl"] > 0
    total = sum(t["pnl"] for t in trades)
    assert engine.equity() == pytest.approx(cfg.paper.initial_capital + total)
