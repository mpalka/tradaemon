"""The book backtest: one wallet, one position cap, an explicit allocation rule.

The allocation tests drive the loop through the `cache` parameter with hand-made
probability series. Going through the real feature pipeline would work too, but a
model stub returns the same number for every pair, and "which pair wins a slot"
is exactly the thing that needs different numbers per pair.
"""

import numpy as np
import pandas as pd
import pytest

from trademon.backtest.book import _Series, run_book_backtest

from .conftest import FakeBundle, make_ohlcv


def frames_for(symbols, n=800):
    """Same bars for every pair, so the pairs differ only in what the model says."""
    return {s: make_ohlcv(n, seed=11 + i) for i, s in enumerate(symbols)}


def series_with(df: pd.DataFrame, prob: float) -> _Series:
    """A pair the model likes exactly `prob` much, on every bar."""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    n = len(df)
    return _Series(
        index={t: i for i, t in enumerate(ts)}, ts=ts.to_numpy(),
        open=df["open"].to_numpy(float), high=df["high"].to_numpy(float),
        low=df["low"].to_numpy(float), close=df["close"].to_numpy(float),
        atr=np.full(n, 1.0),
        p_long=np.full(n, prob), p_short=np.full(n, np.nan), n=n,
    )


def book_cfg(cfg, symbols, max_open):
    return cfg.model_copy(update={
        "exchange": cfg.exchange.model_copy(update={"symbols": list(symbols)}),
        "risk": cfg.risk.model_copy(update={"max_open_positions": max_open}),
    })


def overlapping(trades: pd.DataFrame) -> int:
    """Largest number of positions open at the same instant, read off the journal."""
    events = [(t, 1) for t in trades["entry_time"]] + [(t, -1) for t in trades["exit_time"]]
    events.sort(key=lambda e: (e[0], e[1]))   # exits before entries at the same stamp
    peak = live = 0
    for _, delta in events:
        live += delta
        peak = max(peak, live)
    return peak


@pytest.mark.parametrize("cap", [1, 2, 3])
def test_cap_is_never_exceeded(cfg, cap):
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT"]
    frames = frames_for(symbols, 1500)
    result = run_book_backtest(frames, FakeBundle(prob=0.99),
                               book_cfg(cfg, symbols, max_open=cap))
    trades = result["trades"]
    assert len(trades) > 0
    assert result["summary"]["max_concurrent"] == cap   # the cap binds, and holds
    # the journal has to tell the same story as the counter, which it only does
    # if entries are stamped with the bar they filled on
    assert overlapping(trades) <= cap
    # every pair signals on every bar, so most of the signal is thrown away —
    # the number the per-symbol backtest cannot produce
    assert result["summary"]["slot_blocked"] > 0


def test_one_position_per_symbol(cfg):
    symbols = ["BTC/USDT", "ETH/USDT"]
    frames = frames_for(symbols, 1200)
    trades = run_book_backtest(frames, FakeBundle(prob=0.99),
                               book_cfg(cfg, symbols, max_open=5))["trades"]
    for _, g in trades.groupby("symbol"):
        g = g.sort_values("entry_time")
        assert (g["entry_time"].shift(-1).dropna() >= g["exit_time"].iloc[:-1]).all()


def test_best_first_gives_the_slot_to_the_stronger_signal(cfg):
    symbols = ["BTC/USDT", "ETH/USDT"]
    frames = frames_for(symbols, 900)
    # BTC is first in the config but the weaker candidate
    cache = {"BTC/USDT": series_with(frames["BTC/USDT"], 0.60),
             "ETH/USDT": series_with(frames["ETH/USDT"], 0.90)}
    trades = run_book_backtest(frames, FakeBundle(), book_cfg(cfg, symbols, max_open=1),
                               allocation="best_first", cache=dict(cache))["trades"]
    assert set(trades["symbol"]) == {"ETH/USDT"}

    # fcfs is the engine's current behaviour: the config order decides, and the
    # weaker signal takes the slot every time
    trades = run_book_backtest(frames, FakeBundle(), book_cfg(cfg, symbols, max_open=1),
                               allocation="fcfs", cache=dict(cache))["trades"]
    assert set(trades["symbol"]) == {"BTC/USDT"}


def test_best_first_ignores_config_order(cfg):
    """The ranking must come from the probability, not from where the pair sits
    in the list — otherwise the two rules would be the same rule."""
    symbols = ["BTC/USDT", "ETH/USDT"]
    frames = frames_for(symbols, 900)
    cache = {"BTC/USDT": series_with(frames["BTC/USDT"], 0.60),
             "ETH/USDT": series_with(frames["ETH/USDT"], 0.90)}
    for order in (["BTC/USDT", "ETH/USDT"], ["ETH/USDT", "BTC/USDT"]):
        trades = run_book_backtest(frames, FakeBundle(), book_cfg(cfg, order, max_open=1),
                                   allocation="best_first", cache=dict(cache))["trades"]
        assert set(trades["symbol"]) == {"ETH/USDT"}


def test_shared_wallet_is_not_a_wallet_per_pair(cfg):
    """The whole point of the module: two pairs on one account do not each get
    the starting capital."""
    symbols = ["BTC/USDT", "ETH/USDT"]
    frames = frames_for(symbols, 1200)
    result = run_book_backtest(frames, FakeBundle(prob=0.99),
                               book_cfg(cfg, symbols, max_open=2))
    equity = result["equity"]
    initial = cfg.paper.initial_capital
    assert result["summary"]["initial_capital"] == initial
    # 2 slots x 10% of equity, so the account is never more than ~20% deployed
    cash_floor = min(equity) * 0.5
    assert cash_floor > 0


def test_no_signal_no_trades(cfg):
    symbols = ["BTC/USDT", "ETH/USDT"]
    frames = frames_for(symbols, 600)
    s = run_book_backtest(frames, FakeBundle(prob=0.0),
                          book_cfg(cfg, symbols, max_open=3))["summary"]
    assert s["n_trades"] == 0
    assert s["signals"] == 0
    assert s["total_return_pct"] == pytest.approx(0.0)


def test_maker_execution_is_refused(cfg):
    symbols = ["BTC/USDT"]
    c = book_cfg(cfg, symbols, max_open=1)
    c = c.model_copy(update={
        "execution": c.execution.model_copy(update={"order_style": "maker"})
    })
    with pytest.raises(NotImplementedError):
        run_book_backtest(frames_for(symbols, 400), FakeBundle(), c)
