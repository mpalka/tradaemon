"""Writing config from the dashboard: merge rules, validation, journal, hot-reload.

The point of these tests is that a bad value written from a browser must never reach
the engine, and that a good one must reach it without a restart.
"""

import asyncio
import json

import pandas as pd
import pytest
import yaml

from trademon import config_store as cs
from trademon.config import load_config, overrides_path
from trademon.engine.loop import Book
from trademon.engine.state import RuntimeStore
from trademon.execution.executors import PaperExecutor

from .conftest import FakeBundle, make_ohlcv

BASE_CONFIG = {
    "mode": "paper",
    "exchange": {"id": "binance", "symbols": ["BTC/USDT"], "timeframe": "1m"},
    "strategy": {"warmup_bars": 200, "horizon_bars": 10, "prob_threshold": 0.60,
                 "tp_atr_mult": 2.0, "sl_atr_mult": 1.0},
    "risk": {"position_pct": 0.10, "max_open_positions": 2},
    "paper": {"initial_capital": 1000.0},
}


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    """A throwaway config tree, wired up so load_config() and the engine find it."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    path = cfg_dir / "config.yaml"
    path.write_text(yaml.safe_dump(BASE_CONFIG))
    monkeypatch.setenv("TRADEMON_CONFIG", str(path))
    return path


# ---------- merge semantics ----------

def test_dicts_merge_deep_and_lists_replace_wholesale(cfg_path, tmp_path):
    cs.apply_changes(cfg_path, tmp_path / "runtime", {
        "strategy.prob_threshold": 0.45,
        "exchange.symbols": ["ETH/USDT"],
    })
    cfg = load_config(cfg_path)
    assert cfg.strategy.prob_threshold == 0.45
    assert cfg.strategy.warmup_bars == 200        # sibling key survives the merge
    assert cfg.exchange.symbols == ["ETH/USDT"]   # list replaced, not appended to


def test_baseline_file_is_never_rewritten(cfg_path, tmp_path):
    before = cfg_path.read_text()
    cs.apply_changes(cfg_path, tmp_path / "runtime", {"strategy.prob_threshold": 0.45})
    assert cfg_path.read_text() == before
    assert overrides_path(cfg_path).exists()


def test_none_restores_the_default(cfg_path, tmp_path):
    runtime = tmp_path / "runtime"
    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.45})
    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": None})
    assert load_config(cfg_path).strategy.prob_threshold == 0.60
    # nothing left to override, so the file goes away rather than lingering as
    # `strategy: {}` — the tree returns to exactly its pre-edit state
    assert not overrides_path(cfg_path).exists()


# ---------- validation happens before the write ----------

def test_only_genuinely_changed_fields_are_stored(cfg_path, tmp_path):
    """A section's Save submits every field it renders. Storing them all would pin
    values that were never touched, silently shadowing later edits to config.yaml."""
    report = cs.apply_changes(cfg_path, tmp_path / "runtime", {
        "strategy.prob_threshold": 0.45,   # actually changed
        "strategy.tp_atr_mult": 2.0,       # resubmitted unchanged
        "strategy.warmup_bars": 200,       # resubmitted unchanged
    })
    assert list(report.applied) == ["strategy.prob_threshold"]
    stored = yaml.safe_load(overrides_path(cfg_path).read_text())
    assert stored == {"strategy": {"prob_threshold": 0.45}}


def test_fields_absent_from_the_baseline_are_not_phantom_changes(cfg_path, tmp_path):
    """`strategy.direction` has no line in config.yaml — it lives as a pydantic
    default. Submitting that default must not register as null -> "long"."""
    runtime = tmp_path / "runtime"
    report = cs.apply_changes(cfg_path, runtime, {"strategy.direction": "long"})
    assert not report.changed
    assert cs.load_history(runtime) == []
    assert not overrides_path(cfg_path).exists()


def test_setting_a_value_back_to_the_baseline_drops_the_override(cfg_path, tmp_path):
    runtime = tmp_path / "runtime"
    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.45})
    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.60})
    assert not overrides_path(cfg_path).exists()
    assert load_config(cfg_path).strategy.prob_threshold == 0.60


def test_invalid_value_is_rejected_without_touching_disk(cfg_path, tmp_path):
    with pytest.raises(cs.ConfigWriteError):
        cs.apply_changes(cfg_path, tmp_path / "runtime",
                         {"strategy.prob_threshold": "bardzo wysoki"})
    assert not overrides_path(cfg_path).exists()
    assert load_config(cfg_path).strategy.prob_threshold == 0.60


def test_live_mode_cannot_be_set_from_the_dashboard(cfg_path, tmp_path):
    with pytest.raises(cs.ConfigWriteError, match="nie można zmieniać"):
        cs.apply_changes(cfg_path, tmp_path / "runtime", {"mode": "live"})
    assert load_config(cfg_path).mode == "paper"


# ---------- journal and restart classification ----------

def test_journal_records_old_and_new_values(cfg_path, tmp_path):
    runtime = tmp_path / "runtime"
    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.45}, actor="marcin")
    rows = cs.load_history(runtime)
    assert len(rows) == 1
    assert rows[0]["field"] == "strategy.prob_threshold"
    assert (rows[0]["old"], rows[0]["new"]) == (0.60, 0.45)
    assert rows[0]["actor"] == "marcin"


def test_unchanged_value_is_not_journaled(cfg_path, tmp_path):
    runtime = tmp_path / "runtime"
    report = cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.60})
    assert not report.changed
    assert cs.load_history(runtime) == []


def test_structural_fields_are_flagged_for_restart(cfg_path, tmp_path):
    report = cs.apply_changes(cfg_path, tmp_path / "runtime", {
        "strategy.prob_threshold": 0.45,   # hot
        "exchange.timeframe": "5m",        # structural
    })
    assert report.needs_restart == ["exchange.timeframe"]


def test_restart_flag_roundtrip(tmp_path):
    runtime = tmp_path / "runtime"
    assert cs.restart_requested_at(runtime) is None
    cs.request_restart(runtime)
    assert cs.restart_requested_at(runtime) is not None


def test_restart_watcher_ignores_a_stale_flag(cfg_path, tmp_path, monkeypatch):
    """A flag left over from a previous run must not send the engine into a restart
    loop on startup — only a request made after this process started counts."""
    from trademon.engine import loop as engine_loop

    cfg = load_config(cfg_path)
    cs.request_restart(cfg.paths.runtime_dir)          # written *before* the watcher starts
    monkeypatch.setattr(engine_loop, "RESTART_POLL_SECONDS", 0.01)
    book = _book(cfg, tmp_path, prob=0.5)
    engine = engine_loop.TradingEngine(cfg, book.bundles, book.executor, books=[book])

    async def run() -> None:
        await asyncio.wait_for(engine._restart_watcher(), timeout=0.1)

    with pytest.raises(TimeoutError):
        asyncio.run(run())


def test_restart_watcher_fires_on_a_fresh_request(cfg_path, tmp_path, monkeypatch):
    from trademon.engine import loop as engine_loop

    cfg = load_config(cfg_path)
    monkeypatch.setattr(engine_loop, "RESTART_POLL_SECONDS", 0.01)
    book = _book(cfg, tmp_path, prob=0.5)
    engine = engine_loop.TradingEngine(cfg, book.bundles, book.executor, books=[book])

    async def request_soon() -> None:
        await asyncio.sleep(0.02)
        cs.request_restart(cfg.paths.runtime_dir)

    async def run() -> None:
        await asyncio.gather(engine._restart_watcher(), request_soon())

    with pytest.raises(engine_loop.RestartRequested):
        asyncio.run(run())


# ---------- the engine actually picks hot changes up ----------

def _book(cfg, tmp_path, prob):
    store = RuntimeStore(tmp_path / "runtime" / "book")
    return Book("default", cfg, FakeBundle(prob=prob), PaperExecutor(cfg), store)


def test_hot_field_takes_effect_on_the_next_candle(cfg_path, tmp_path):
    cfg = load_config(cfg_path)
    book = _book(cfg, tmp_path, prob=0.55)   # below the 0.60 threshold
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    for _, row in df.iterrows():
        book.on_candle("BTC/USDT", row.to_dict())
    assert not book.positions, "0.55 < 0.60 — nothing should have opened yet"

    buffer_before, delta_before = book._buffer_len, book._bar_delta
    cs.apply_changes(cfg_path, cfg.paths.runtime_dir, {"strategy.prob_threshold": 0.50})

    last = df.iloc[-1]
    book.on_candle("BTC/USDT", {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": last["close"], "high": last["close"] * 1.001,
        "low": last["close"] * 0.999, "close": last["close"], "volume": 10.0,
    })
    assert book.positions, "0.55 >= the new 0.50 threshold — should have opened"
    assert book.cfg.strategy.prob_threshold == 0.50
    assert book._bar_delta == delta_before          # structural fields untouched
    assert book._buffer_len == buffer_before        # horizon_bars did not change

    alerts = [json.loads(x) for x in book.store.alerts_path.read_text().splitlines()]
    assert any(a["kind"] == "config" for a in alerts), "the change belongs in the journal"


def test_structural_change_does_not_leak_into_a_running_book(cfg_path, tmp_path):
    cfg = load_config(cfg_path)
    book = _book(cfg, tmp_path, prob=0.99)
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    for _, row in df.iterrows():
        book.on_candle("BTC/USDT", row.to_dict())

    warmup_before, delta_before = book.cfg.strategy.warmup_bars, book._bar_delta
    cs.apply_changes(cfg_path, cfg.paths.runtime_dir, {
        "strategy.warmup_bars": 42, "exchange.timeframe": "5m",
    })
    last = df.iloc[-1]
    book.on_candle("BTC/USDT", {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": last["close"], "high": last["close"] * 1.001,
        "low": last["close"] * 0.999, "close": last["close"], "volume": 10.0,
    })
    assert book.cfg.strategy.warmup_bars == warmup_before
    assert book._bar_delta == delta_before
