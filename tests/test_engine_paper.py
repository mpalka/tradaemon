import asyncio
import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from tradaemon.engine.loop import Book, Position, TradingEngine
from tradaemon.engine.state import RuntimeStore
from tradaemon.execution.executors import PaperExecutor

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
    import tradaemon.engine.loop as loop_mod

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


def test_a_position_saved_before_entry_prob_existed_still_restores(cfg, tmp_path):
    """The NAS restart case: books have open positions serialized in state.json from
    before the field existed, and a restart must not trip over its own saved state.
    Those positions carry no probability, which is the truth about them."""
    saved = {
        "symbol": "BTC/USDT", "qty": 0.5, "entry_price": 100.0, "entry_fees": 0.05,
        "tp": 110.0, "sl": 95.0, "side": "long", "margin": 50.0,
        "entry_time": "2026-08-01T12:00:00+00:00",
        "deadline": "2026-08-03T12:00:00+00:00",
    }
    pos = Position.from_json(saved)
    assert pos.entry_prob is None
    assert pos.qty == pytest.approx(0.5)
    # and it survives another round trip, now with the field present
    assert Position.from_json(pos.to_json()).entry_prob is None


def test_journaled_trades_carry_the_probability_that_opened_them(engine, cfg):
    """The live counterpart of the backtests' `prob` column: in a few months this is
    what lets the question be asked of real trades rather than of a backtest."""
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(engine, df)
    pos = engine.positions["BTC/USDT"]
    assert pos.entry_prob == pytest.approx(0.99)
    engine.bundles = {"long": FakeBundle(prob=0.0)}  # no re-entry after the close

    last = df.iloc[-1]
    engine.on_candle("BTC/USDT", {
        "timestamp": last["timestamp"] + pd.Timedelta(minutes=1),
        "open": last["close"], "high": pos.tp * 1.001, "low": last["close"] * 0.9999,
        "close": pos.tp, "volume": 10.0,
    })
    trades = [json.loads(x) for x in engine.store.trades_path.read_text().splitlines()]
    assert trades[-1]["prob"] == pytest.approx(0.99)


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


def test_events_are_stamped_when_the_candle_closed(cfg, tmp_path):
    """The regression behind "the journal skips the newest candle".

    A candle reaches the engine only once it has closed, so its OPEN time — what
    ccxt puts in the row — is a full timeframe before anything was decided. Every
    journal row used to carry it: on 4h bars the trades from the candle that closed
    at 22:00 were filed under 18:00, and the panel looked hours behind while being
    perfectly up to date. A 4h timeframe over 1m candles is deliberate here: it
    makes the shift impossible to confuse with the next candle's open time.

    `last_candle_ts` keeps the open time on purpose — `humanize.bot_status` and
    `config_store.live_drift` add the timeframe back themselves — so this pins both
    conventions at once.
    """
    cfg.exchange.symbols = ["BTC/USDT"]
    cfg.exchange.timeframe = "4h"
    book = Book("default", cfg, FakeBundle(prob=0.0), PaperExecutor(cfg),
                RuntimeStore(tmp_path / "runtime"))
    df = make_ohlcv(cfg.strategy.warmup_bars + 5)
    feed(book, df.iloc[:-1])          # warm up without ever signalling an entry
    assert not book.positions

    book.bundles = {"long": FakeBundle(prob=0.99)}   # the last candle is the entry
    last_open = df["timestamp"].iloc[-1]
    closed_at = last_open + pd.Timedelta(hours=4)
    book.on_candle("BTC/USDT", df.iloc[-1].to_dict())

    assert book.positions["BTC/USDT"].entry_time == closed_at
    opens = [json.loads(x) for x in book.store.alerts_path.read_text().splitlines()]
    opens = [a for a in opens if a["kind"] == "trade_open"]
    assert len(opens) == 1
    assert datetime.fromisoformat(opens[0]["timestamp"]) == closed_at

    equity = [json.loads(x) for x in book.store.equity_path.read_text().splitlines()]
    assert datetime.fromisoformat(equity[-1]["timestamp"]) == closed_at

    state = json.loads(book.store.state_path.read_text())
    assert datetime.fromisoformat(state["updated_at"]) == closed_at
    assert state["last_candle_ts"]["BTC/USDT"] == last_open.isoformat()  # still the open


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
    import tradaemon.engine.loop as loop_mod
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
    import tradaemon.engine.loop as loop_mod
    monkeypatch.setattr(loop_mod, "RETRY_SECONDS", 0.0)
    monkeypatch.setattr(loop_mod, "MAX_RETRY_SECONDS", 0.0)

    # what the previous container left behind, and nothing else
    engine.alert("connection", "alert.connection.lost", {}, datetime.now(UTC), ok=False)

    fresh = Book("default", cfg, FakeBundle(), PaperExecutor(cfg), engine.store)
    eng = TradingEngine(cfg, FakeBundle(), PaperExecutor(cfg), books=[fresh])
    asyncio.run(eng._bootstrap_with_retry(FlakyExchange(make_ohlcv(50), fail_times=0)))

    alerts = [json.loads(x) for x in engine.store.alerts_path.read_text().splitlines()]
    assert alerts[-1]["kind"] == "connection" and alerts[-1]["ok"] is True


def test_an_alert_carries_both_a_key_and_a_rendered_sentence(engine):
    """0.2.0 changed the journal format. The key is what lets the panel render the
    line in either language; the sentence is what the webhook sends and what every
    line written before this version has instead."""
    engine.alert("drawdown", "alert.drawdown", {"dd": "-4.2"}, datetime.now(UTC))
    rec = json.loads(engine.store.alerts_path.read_text().splitlines()[-1])
    assert rec["msg_key"] == "alert.drawdown"
    assert rec["params"] == {"dd": "-4.2"}
    assert rec["message"] == "obsunięcie -4.2% od szczytu kapitału"

    from tradaemon.dashboard import humanize
    assert humanize.event_line(rec)["text"] == rec["message"]


def test_a_clean_start_does_not_invent_a_recovery(engine, cfg, monkeypatch):
    """No outage on record means nothing to close — otherwise every restart would
    file a 'connection restored' for a connection that was never lost."""
    import tradaemon.engine.loop as loop_mod
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
