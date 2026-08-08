import asyncio
import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from trademon.engine.loop import Book, TradingEngine
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


def test_rollover_extends_instead_of_closing(engine, cfg):
    cfg.strategy.rollover = True
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
    cfg.strategy.rollover = True
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


def _tp_bar(df: pd.DataFrame, pos, close_price: float) -> dict:
    """A bar that touches the take-profit and closes where we say — with its low
    held clear of the stop, so `check_bracket_exit` cannot call it an SL instead."""
    last = df.iloc[-1]
    return {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": float(last["close"]), "high": max(pos.tp * 1.001, close_price),
        "low": max(pos.sl * 1.001, min(float(last["close"]), close_price) * 0.9999),
        "close": close_price, "volume": 5.0,
    }


def _closed_trades(engine) -> list[dict]:
    path = engine.store.trades_path
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_a_take_profit_is_never_rolled_over(engine, cfg):
    """Even when the round trip is pure cost — the bar closes above the target, so
    the bot sells low and buys back high, the SOL case that prompted this.

    Declining the fill here would be reading the future: TP is detected from the
    bar's high and filled at the barrier, i.e. it already went through before the
    bar ended. Rolling it over anyway measured +146.6% -> +182.8% mean return over
    5.5 years, thirty times the honest timeout-only effect — a number that says
    "lookahead", not "edge". The churn is real; this is not the way to remove it.
    """
    cfg.strategy.rollover = True
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    pos = engine.positions["BTC/USDT"]
    closed_before = len(_closed_trades(engine))

    engine.on_candle("BTC/USDT", _tp_bar(df, pos, close_price=pos.tp * 1.002))

    trades = _closed_trades(engine)
    assert len(trades) == closed_before + 1
    assert trades[-1]["exit_reason"] == "tp"


def test_a_cooldown_keeps_the_book_out_for_the_bar_it_just_closed(engine, cfg):
    """The exit and the entry that undoes it share one call to `on_candle`, so a
    cooldown of one bar is what separates them.

    Kept as a measured-off dial rather than a fix: sweeping it over 5.5 years and
    ten pairs cost 21.6 points of mean return at cd=1 and was worse on every
    single pair, so the immediate re-entry earns its fees several times over.
    The test pins the mechanism so the finding stays reproducible.
    """
    cfg.strategy.rollover = False        # let the take-profit actually close
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)                     # warm up without it, or the book ends flat
    pos = engine.positions["BTC/USDT"]
    cfg.strategy.reentry_cooldown_bars = 1

    engine.on_candle("BTC/USDT", _tp_bar(df, pos, close_price=pos.tp * 1.002))
    assert "BTC/USDT" not in engine.positions          # closed, and not bought back
    assert engine.signals["BTC/USDT"]["reason"] == "reentry_cooldown"

    last = df.iloc[-1]
    price = float(pos.tp) * 1.002
    engine.on_candle("BTC/USDT", {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=2),
        "open": price, "high": price * 1.0001, "low": price * 0.9999,
        "close": price, "volume": 5.0,
    })
    assert "BTC/USDT" in engine.positions              # the next bar is free again


def test_a_cooldown_survives_a_restart(engine, cfg):
    """A cooldown a restart forgets is not a cooldown — the container comes back
    inside the same bar and buys straight back in."""
    cfg.strategy.reentry_cooldown_bars = 1
    engine.last_exit_ts["BTC/USDT"] = "2026-01-01T00:00:00+00:00"
    engine.persist(datetime.now(UTC))

    fresh = Book("default", cfg, FakeBundle(), PaperExecutor(cfg), engine.store)
    fresh.restore()
    assert fresh.last_exit_ts == engine.last_exit_ts


def test_a_stop_loss_never_rolls_over(engine, cfg):
    """Extending a stop is abandoning the risk limit, not saving a fee — so it
    closes even with the signal still firing and the round trip a pure cost."""
    cfg.strategy.rollover = True
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    pos = engine.positions["BTC/USDT"]
    last = df.iloc[-1]

    def n_rollovers() -> int:
        rows = [json.loads(x) for x in
                engine.store.alerts_path.read_text().splitlines() if x.strip()]
        return sum(1 for a in rows if a["kind"] == "trade_rollover")

    # the warmup feed rolls over take-profits of its own, so count the delta
    rolled_before = n_rollovers()
    engine.on_candle("BTC/USDT", {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": float(last["close"]), "high": float(last["close"]),
        "low": pos.sl * 0.999, "close": pos.sl, "volume": 5.0,
    })

    trades = _closed_trades(engine)
    assert trades[-1]["exit_reason"] == "sl"
    assert n_rollovers() == rolled_before
    # the signal is still firing, so the engine re-enters on the same bar — that is
    # a *new* position, not the one the stop was meant to end
    assert engine.positions["BTC/USDT"].entry_price != pos.entry_price


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
    # Prices too, not just money: persist() writes them, so restore() must read them.
    assert engine2.last_close == engine.last_close
    assert engine2.last_candle_ts == engine.last_candle_ts


def test_a_restored_book_persists_prices_it_never_saw_a_candle_for(engine, cfg):
    """The regression behind the missing buy&hold lines.

    A start that dies before the first candle still reaches a persist on the way
    out. It used to write empty `last_close`/`last_candle_ts` over good ones, which
    the panel then read as "the engine is live but knows no prices" — and drew the
    bot's line past both benchmarks. Asserted on the file, because the file is what
    the dashboard reads.
    """
    feed(engine, make_ohlcv(cfg.strategy.warmup_bars + 5))
    before = json.loads(engine.store.state_path.read_text())
    assert before["last_close"] and before["last_candle_ts"]

    fresh = Book("default", cfg, FakeBundle(), PaperExecutor(cfg), engine.store)
    fresh.restore()
    fresh.persist(datetime.now(UTC))   # no candle in between

    after = json.loads(engine.store.state_path.read_text())
    assert after["last_close"] == before["last_close"]
    assert after["last_candle_ts"] == before["last_candle_ts"]


def test_seed_buffer_counts_as_having_read_the_market(engine, cfg):
    """Otherwise the panel calls a healthy, freshly restarted bot 🔴 for four hours."""
    df = make_ohlcv(50)
    engine.seed_buffer("BTC/USDT", df)
    assert engine.last_candle_ts["BTC/USDT"] == df["timestamp"].iloc[-1].isoformat()


class FlakyExchange:
    """Fails `fail_times` times, then serves candles — a DNS outage at startup."""

    def __init__(self, df: pd.DataFrame, fail_times: int):
        self.remaining = fail_times
        self.calls = 0
        self.raw = [[int(r.timestamp.timestamp() * 1000), r.open, r.high,
                     r.low, r.close, r.volume] for r in df.itertuples()]

    async def fetch_ohlcv(self, symbol, timeframe, limit=None):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise ConnectionError("Temporary failure in name resolution")
        return self.raw


def test_bootstrap_waits_the_network_out_instead_of_dying(engine, cfg, tmp_path, monkeypatch):
    """The NAS failure: without this the process exits and Docker restarts it
    straight back into the same lookup — 826 times in five hours."""
    import trademon.engine.loop as loop_mod
    monkeypatch.setattr(loop_mod, "RETRY_SECONDS", 0.0)
    monkeypatch.setattr(loop_mod, "MAX_RETRY_SECONDS", 0.0)

    eng = TradingEngine(cfg, FakeBundle(), PaperExecutor(cfg), books=[engine])
    # Long enough to trip CONNECTION_ALERT_AFTER, so the journal side is covered too.
    fake = FlakyExchange(make_ohlcv(50), fail_times=loop_mod.CONNECTION_ALERT_AFTER)
    last_seen = asyncio.run(eng._bootstrap_with_retry(fake))

    assert fake.calls == loop_mod.CONNECTION_ALERT_AFTER + 1   # failures, then success
    assert last_seen["BTC/USDT"] is not None
    assert engine.last_close["BTC/USDT"] > 0

    alerts = [json.loads(x) for x in engine.store.alerts_path.read_text().splitlines()]
    conn = [a for a in alerts if a["kind"] == "connection"]
    assert [a["ok"] for a in conn] == [False, True]   # outage opened, then closed


def test_an_outage_from_a_previous_container_is_closed_on_recovery(engine, cfg, monkeypatch):
    """The reported problem: the process that files the outage may never come back.

    Restart the container and the all-clear has no author, so the newest line in
    the event log keeps saying the exchange is unreachable — for hours, until some
    unrelated event scrolls it down. The reader cannot tell recovery from silence.
    """
    import trademon.engine.loop as loop_mod
    monkeypatch.setattr(loop_mod, "RETRY_SECONDS", 0.0)
    monkeypatch.setattr(loop_mod, "MAX_RETRY_SECONDS", 0.0)

    # what the previous container left behind, and nothing else
    engine.alert("connection", "brak połączenia z giełdą", datetime.now(UTC), ok=False)

    fresh = Book("default", cfg, FakeBundle(), PaperExecutor(cfg), engine.store)
    eng = TradingEngine(cfg, FakeBundle(), PaperExecutor(cfg), books=[fresh])
    asyncio.run(eng._bootstrap_with_retry(FlakyExchange(make_ohlcv(50), fail_times=0)))

    alerts = [json.loads(x) for x in engine.store.alerts_path.read_text().splitlines()]
    assert alerts[-1]["kind"] == "connection" and alerts[-1]["ok"] is True


def test_a_clean_start_does_not_invent_a_recovery(engine, cfg, monkeypatch):
    """No outage on record means nothing to close — otherwise every restart would
    file a 'connection restored' for a connection that was never lost."""
    import trademon.engine.loop as loop_mod
    monkeypatch.setattr(loop_mod, "RETRY_SECONDS", 0.0)
    monkeypatch.setattr(loop_mod, "MAX_RETRY_SECONDS", 0.0)

    eng = TradingEngine(cfg, FakeBundle(), PaperExecutor(cfg), books=[engine])
    asyncio.run(eng._bootstrap_with_retry(FlakyExchange(make_ohlcv(50), fail_times=0)))
    assert engine.store.last_alert("connection") is None


def test_a_start_that_never_ran_leaves_the_book_alone(engine, cfg, tmp_path):
    """A state.json too corrupt to parse used to be overwritten by a virgin book."""
    feed(engine, make_ohlcv(cfg.strategy.warmup_bars + 5))
    engine.store.state_path.write_text('{"cash": 1')   # truncated mid-write
    corrupt = engine.store.state_path.read_bytes()

    eng = TradingEngine(cfg, FakeBundle(), PaperExecutor(cfg),
                        books=[Book("default", cfg, FakeBundle(),
                                    PaperExecutor(cfg), engine.store)])
    with pytest.raises(json.JSONDecodeError):
        asyncio.run(eng.run())

    assert engine.store.state_path.read_bytes() == corrupt
