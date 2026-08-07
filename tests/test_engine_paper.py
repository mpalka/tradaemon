import json

import pandas as pd
import pytest

from trademon.engine.loop import Book
from trademon.engine.state import RuntimeStore
from trademon.execution.executors import PaperExecutor

from .conftest import FakeBundle, make_ohlcv


@pytest.fixture
def engine(cfg, tmp_path):
    cfg.exchange.symbols = ["BTC/USDT"]
    store = RuntimeStore(tmp_path / "runtime")
    return Book("default", cfg, FakeBundle(prob=0.99), PaperExecutor(cfg), store)


def feed(engine, df: pd.DataFrame, symbol: str = "BTC/USDT") -> None:
    for _, row in df.iterrows():
        engine.on_candle(symbol, row.to_dict())


def test_opens_position_after_warmup_and_persists_state(engine, cfg):
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    assert "BTC/USDT" in engine.positions
    pos = engine.positions["BTC/USDT"]
    assert pos.tp > pos.entry_price > pos.sl
    assert engine.cash < cfg.paper.initial_capital

    state = json.loads((engine.store.state_path).read_text())
    assert state["positions"]["BTC/USDT"]["qty"] == pytest.approx(pos.qty)
    assert state["mode"] == "paper"


def test_take_profit_close_is_profitable_and_journaled(engine, cfg):
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    pos = engine.positions["BTC/USDT"]
    engine.bundles = {"long": FakeBundle(prob=0.0)}  # no re-entry after the close

    last = df.iloc[-1]
    tp_bar = {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": last["close"], "high": pos.tp * 1.001, "low": last["close"] * 0.9999,
        "close": pos.tp, "volume": 10.0,
    }
    engine.on_candle("BTC/USDT", tp_bar)

    assert "BTC/USDT" not in engine.positions
    trades = [json.loads(x) for x in engine.store.trades_path.read_text().splitlines()]
    assert trades[-1]["exit_reason"] == "tp"
    assert trades[-1]["pnl"] > 0
    total_pnl = sum(t["pnl"] for t in trades)
    assert engine.equity() == pytest.approx(cfg.paper.initial_capital + total_pnl)


def test_timeout_close(engine, cfg):
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    pos = engine.positions["BTC/USDT"]

    last = df.iloc[-1]
    ts = last["timestamp"]
    price = float(last["close"])
    for i in range(cfg.strategy.horizon_bars + 1):
        bar = {
            "timestamp": ts + pd.Timedelta(minutes=i + 1),
            # stay strictly inside the barriers so only the deadline can close it
            "open": price, "high": min(price * 1.0001, pos.tp * 0.999),
            "low": max(price * 0.9999, pos.sl * 1.001), "close": price, "volume": 5.0,
        }
        engine.on_candle("BTC/USDT", bar)
        if "BTC/USDT" not in engine.positions:
            break
    trades = [json.loads(x) for x in engine.store.trades_path.read_text().splitlines()]
    assert trades and trades[-1]["exit_reason"] == "timeout"


def _flat_bars(df: pd.DataFrame, pos, n: int) -> list[dict]:
    """`n` bars glued to the last close, strictly inside the position's barriers,
    so only the deadline (or a rollover) can act."""
    last = df.iloc[-1]
    price = float(last["close"])
    return [{
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=i + 1),
        "open": price, "high": min(price * 1.0001, pos.tp * 0.999),
        "low": max(price * 0.9999, pos.sl * 1.001), "close": price, "volume": 5.0,
    } for i in range(n)]


def test_timeout_rollover_extends_instead_of_closing(engine, cfg):
    cfg.strategy.timeout_rollover = True
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    pos = engine.positions["BTC/USDT"]
    entry_price, deadline = pos.entry_price, pos.deadline

    def n_trades() -> int:
        path = engine.store.trades_path
        return len(path.read_text().splitlines()) if path.exists() else 0

    closed_before = n_trades()
    for bar in _flat_bars(df, pos, cfg.strategy.horizon_bars + 1):
        engine.on_candle("BTC/USDT", bar)

    # still the same position (same entry), just with a pushed-out deadline
    assert "BTC/USDT" in engine.positions
    assert engine.positions["BTC/USDT"].entry_price == entry_price
    assert engine.positions["BTC/USDT"].deadline > deadline
    assert n_trades() == closed_before  # nothing was closed past the deadline

    alerts = [json.loads(x) for x in engine.store.alerts_path.read_text().splitlines()]
    rollovers = [a for a in alerts if a["kind"] == "trade_rollover"]
    assert rollovers and rollovers[-1]["symbol"] == "BTC/USDT"


def test_timeout_still_closes_when_signal_is_gone(engine, cfg):
    cfg.strategy.timeout_rollover = True
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    pos = engine.positions["BTC/USDT"]
    engine.bundles = {"long": FakeBundle(prob=0.0)}  # signal died while holding

    for bar in _flat_bars(df, pos, cfg.strategy.horizon_bars + 1):
        engine.on_candle("BTC/USDT", bar)
        if "BTC/USDT" not in engine.positions:
            break
    trades = [json.loads(x) for x in engine.store.trades_path.read_text().splitlines()]
    assert trades and trades[-1]["exit_reason"] == "timeout"


def test_hot_reload_swaps_models_when_file_changes(engine, tmp_path, monkeypatch):
    import trademon.engine.loop as loop_mod

    model_file = tmp_path / "model_long.joblib"
    model_file.write_text("v1")
    engine._model_path = model_file
    engine._model_mtime = model_file.stat().st_mtime

    new_bundles = {"long": FakeBundle(prob=0.5)}
    monkeypatch.setattr(loop_mod, "load_bundles", lambda _dir: new_bundles)

    engine._maybe_reload_models()  # no change yet
    assert engine.bundles is not new_bundles

    model_file.write_text("v2")  # simulate refresh.py promoting a new model
    import os
    future = engine._model_mtime + 10
    os.utime(model_file, (future, future))
    engine._maybe_reload_models()
    assert engine.bundles is new_bundles


def test_state_restore_round_trip(engine, cfg, tmp_path):
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    assert engine.positions

    engine2 = Book("default", cfg, FakeBundle(), PaperExecutor(cfg), engine.store)
    engine2.restore()
    assert engine2.cash == pytest.approx(engine.cash)
    assert engine2.positions.keys() == engine.positions.keys()
    p1, p2 = engine.positions["BTC/USDT"], engine2.positions["BTC/USDT"]
    assert p2.qty == pytest.approx(p1.qty)
    assert p2.deadline == p1.deadline
