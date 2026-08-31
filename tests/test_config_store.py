"""Writing config from the dashboard: merge rules, validation, journal, hot-reload.

The point of these tests is that a bad value written from a browser must never reach
the engine, and that a good one must reach it without a restart.
"""

import asyncio
import json
import os

import pandas as pd
import pytest
import yaml

from trademon import config_store as cs
from trademon.config import Config, load_config, overrides_path
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
    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.45}, actor="tester")
    rows = cs.load_history(runtime)
    assert len(rows) == 1
    assert rows[0]["field"] == "strategy.prob_threshold"
    assert (rows[0]["old"], rows[0]["new"]) == (0.60, 0.45)
    assert rows[0]["actor"] == "tester"


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


def _warm(book, cfg):
    """Feed enough candles to get past warmup, and hand back the last bar."""
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    for _, row in df.iterrows():
        book.on_candle("BTC/USDT", row.to_dict())
    return df.iloc[-1]


def _one_more_candle(book, last):
    """One flat candle after `last`, which is all it takes to trigger a reload."""
    bar = {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": last["close"], "high": last["close"] * 1.001,
        "low": last["close"] * 0.999, "close": last["close"], "volume": 10.0,
    }
    book.on_candle("BTC/USDT", bar)
    return pd.Series(bar)


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


# ---------- the watch sees every kind of change, not just a newer mtime ----------

def test_reverting_the_last_override_deletes_the_file_and_the_engine_notices(cfg_path, tmp_path):
    """The reported bug. Restoring a default removes the key, and with nothing left to
    override the whole file goes away — which the old mtime watch read as "no change",
    because a missing file scored 0.0 and 0.0 is never newer. The book went on
    enforcing 5 while the panel showed 3, until someone restarted the container."""
    cfg = load_config(cfg_path)
    runtime = tmp_path / "runtime"
    book = _book(cfg, tmp_path, prob=0.99)
    last = _warm(book, cfg)

    cs.apply_changes(cfg_path, runtime, {"risk.max_open_positions": 5})
    last = _one_more_candle(book, last)
    assert book.risk.cfg.max_open_positions == 5

    cs.apply_changes(cfg_path, runtime, {"risk.max_open_positions": None})
    assert not overrides_path(cfg_path).exists()
    _one_more_candle(book, last)
    # both copies matter: can_open() reads the risk manager's, not the book's
    assert book.cfg.risk.max_open_positions == 2
    assert book.risk.cfg.max_open_positions == 2


def test_two_saves_in_one_mtime_tick_are_both_adopted(cfg_path, tmp_path):
    """Rules out watching (mtime, size) instead of content: `0.50` and `0.45` are the
    same number of bytes, so a coarse clock would hide the second save completely."""
    cfg = load_config(cfg_path)
    runtime = tmp_path / "runtime"
    book = _book(cfg, tmp_path, prob=0.99)
    last = _warm(book, cfg)

    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.50})
    last = _one_more_candle(book, last)
    assert book.cfg.strategy.prob_threshold == 0.50

    frozen = overrides_path(cfg_path).stat().st_mtime
    cs.apply_changes(cfg_path, runtime, {"strategy.prob_threshold": 0.45})
    os.utime(overrides_path(cfg_path), (frozen, frozen))
    _one_more_candle(book, last)
    assert book.cfg.strategy.prob_threshold == 0.45


def test_a_hand_edit_to_the_baseline_is_adopted_too(cfg_path, tmp_path):
    """config.yaml is the other half of what load_config merges, and on the NAS it is a
    bind mount — editing it there used to be invisible for the life of the container."""
    cfg = load_config(cfg_path)
    book = _book(cfg, tmp_path, prob=0.99)
    last = _warm(book, cfg)

    edited = {**BASE_CONFIG, "strategy": {**BASE_CONFIG["strategy"], "prob_threshold": 0.45}}
    cfg_path.write_text(yaml.safe_dump(edited))
    _one_more_candle(book, last)
    assert book.cfg.strategy.prob_threshold == 0.45


def test_a_broken_file_changes_nothing_and_does_not_stop_the_candle(cfg_path, tmp_path):
    """A file that parses as YAML but not as a Config can only arrive by hand, since
    apply_changes validates before it writes. Trading carries on regardless."""
    cfg = load_config(cfg_path)
    book = _book(cfg, tmp_path, prob=0.99)
    last = _warm(book, cfg)

    overrides_path(cfg_path).write_text(
        yaml.safe_dump({"strategy": {"prob_threshold": "bardzo wysoki"}}))
    last = _one_more_candle(book, last)
    assert book.cfg.strategy.prob_threshold == 0.60

    overrides_path(cfg_path).write_text(yaml.safe_dump({"strategy": {"prob_threshold": 0.45}}))
    _one_more_candle(book, last)
    assert book.cfg.strategy.prob_threshold == 0.45, "the next good file must still land"


def test_a_reload_that_failed_is_retried_not_remembered(cfg_path, tmp_path, monkeypatch):
    """The failure here is transient — the file is valid and never changes between the
    two candles. That is the case the old ordering lost: it recorded the file as handled
    *before* trying to load it, so one unlucky read stranded the book on its previous
    parameters until someone restarted the container."""
    from trademon.engine import loop as loop_mod

    cfg = load_config(cfg_path)
    book = _book(cfg, tmp_path, prob=0.99)
    last = _warm(book, cfg)
    overrides_path(cfg_path).write_text(yaml.safe_dump({"strategy": {"prob_threshold": 0.45}}))

    real, calls = loop_mod.load_config, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk hiccup halfway through the read")
        return real(*args, **kwargs)

    monkeypatch.setattr(loop_mod, "load_config", flaky)

    last = _one_more_candle(book, last)
    assert book.cfg.strategy.prob_threshold == 0.60, "the failed read adopted nothing"

    _one_more_candle(book, last)      # same file, untouched
    assert book.cfg.strategy.prob_threshold == 0.45, "and the retry must still pick it up"


def test_a_change_with_no_hot_field_is_not_reparsed_forever(cfg_path, tmp_path):
    """A save that only touched restart-only fields is still *handled*. Recording the
    fingerprint only when something was adopted would re-parse both YAMLs every candle
    from then on."""
    cfg = load_config(cfg_path)
    book = _book(cfg, tmp_path, prob=0.99)
    last = _warm(book, cfg)

    cs.apply_changes(cfg_path, tmp_path / "runtime", {"strategy.warmup_bars": 42})
    _one_more_candle(book, last)
    assert book._config_digest == book._config_fingerprint()


# ---------- what the engine is actually enforcing ----------

def test_live_config_covers_exactly_the_hot_field_list(cfg_path, tmp_path):
    """Welds the engine's three HOT_* tuples to config_store.HOT_FIELDS. A field added
    to one and not the other would silently drop out of the drift check."""
    book = _book(load_config(cfg_path), tmp_path, prob=0.99)
    assert set(book.live_config()) == cs.HOT_FIELDS


def test_state_json_reports_what_the_book_enforces_not_what_is_on_disk(cfg_path, tmp_path):
    cfg = load_config(cfg_path)
    book = _book(cfg, tmp_path, prob=0.99)
    _warm(book, cfg)
    state = json.loads(book.store.state_path.read_text())
    assert state["live_config"]["risk.max_open_positions"] == 2

    cs.apply_changes(cfg_path, tmp_path / "runtime", {"risk.max_open_positions": 5})
    state = json.loads(book.store.state_path.read_text())
    assert state["live_config"]["risk.max_open_positions"] == 2, (
        "no candle has closed yet, so the book is still on the old value — and saying so "
        "is the whole point of this field")


def _write_state(book_dir, live_config, last_candle):
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "state.json").write_text(json.dumps({
        "live_config": live_config, "last_candle_ts": {"BTC/USDT": last_candle},
    }))


def test_drift_is_quiet_until_a_candle_has_closed(cfg_path, tmp_path):
    runtime = tmp_path / "runtime"
    cs.apply_changes(cfg_path, runtime, {"risk.max_open_positions": 5})
    _write_state(runtime, {"risk.max_open_positions": 2}, "2000-01-01T00:00:00+00:00")

    drift = cs.live_drift(cfg_path, runtime)
    assert [(d.field, d.live, d.on_disk, d.stuck) for d in drift] == [
        ("risk.max_open_positions", 2, 5, False)]


def test_drift_flags_a_book_that_saw_a_candle_and_still_disagrees(cfg_path, tmp_path):
    runtime = tmp_path / "runtime"
    cs.apply_changes(cfg_path, runtime, {"risk.max_open_positions": 5})
    _write_state(runtime, {"risk.max_open_positions": 2}, "2100-01-01T00:00:00+00:00")

    drift = cs.live_drift(cfg_path, runtime)
    assert len(drift) == 1 and drift[0].stuck
    assert (drift[0].live, drift[0].on_disk) == (2, 5)


def test_drift_compares_each_book_against_its_own_variant(cfg_path, tmp_path):
    """ryzyko_100 runs 5 against a base of 3 on purpose. Comparing it with the base
    config would turn a designed experiment into a permanent red warning."""
    cfg_path.write_text(yaml.safe_dump({
        **BASE_CONFIG,
        "variants": [{"name": "ryzyko_100", "max_open_positions": 5}],
    }))
    runtime = tmp_path / "runtime"
    _write_state(runtime / "ryzyko_100", {"risk.max_open_positions": 5},
                 "2100-01-01T00:00:00+00:00")
    assert cs.live_drift(cfg_path, runtime) == []


def test_drift_ignores_a_book_written_by_an_older_engine(cfg_path, tmp_path):
    """Between deploying the new image and the engine restarting, state.json has no
    live_config. That is silence, not disagreement."""
    runtime = tmp_path / "runtime"
    cs.apply_changes(cfg_path, runtime, {"risk.max_open_positions": 5})
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "state.json").write_text(json.dumps({"cash": 1000.0}))
    assert cs.live_drift(cfg_path, runtime) == []


# ---------------------------------------------------------------------------
# the shipped config itself
# ---------------------------------------------------------------------------


def _shipped() -> Config:
    """The real config/config.yaml, not a fixture — overrides deliberately ignored
    so this tests what is committed, not what a local panel edit did to it."""
    from trademon.config import PROJECT_ROOT
    path = PROJECT_ROOT / "config" / "config.yaml"
    return Config.model_validate(yaml.safe_load(path.read_text()))


def test_shipped_config_parses():
    """Nothing else in the suite reads config/config.yaml, so a typo there used to
    surface only on the NAS — where a rebuild goes through the Container Manager GUI
    and costs a deploy cycle to find out."""
    assert _shipped().exchange.symbols


def test_shipped_variant_names_are_unique():
    """Two variants of one name means two books sharing `runtime/<name>/`: one
    state.json overwritten twice a minute and two strategies' trades merged into one
    journal, with nothing in the panel to suggest the comparison is fiction."""
    names = [v.name for v in _shipped().variants]
    assert len(names) == len(set(names)), f"zduplikowany wariant: {names}"


def test_shipped_primary_variant_exists():
    """`primary_variant` pins which book the beginner screen calls "Twój portfel".
    Pointing it at a name no variant has does not fail loudly — it silently falls
    back, and the main screen then shows a book nobody chose."""
    cfg = _shipped()
    if cfg.primary_variant is not None:
        assert cfg.primary_variant in {v.name for v in cfg.variants}
