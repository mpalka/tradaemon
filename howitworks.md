# How it works (from the inside)

*English · [Polski](howitworks.pl.md)*

> This is an educational project running on simulated money. See
> [DISCLAIMER.md](DISCLAIMER.md) and
> [what to expect](README.md#what-to-expect-from-a-bot-like-this).

The README describes **what** this project does and **what results it produced**. This
file describes the **mechanism**: the path a single candle takes from the exchange to an
order, what the game the bot is actually playing looks like (§4), who writes and who
reads which file, and why several things are done differently from how the obvious
version would look.

Sections 1–3 are about **construction**. Section 4 and the "Mechanics" subsections in the
chapters that follow are about **behaviour**: what each component does over the following
minutes, days and weeks, and what it does in the cases where nothing interesting happens
— because that is its default state.

The code version this document describes: `0.2.0`.

---

## 1. The view from above

TraDaemon is **four processes over one directory of files**. There is no database, no
queue, no API between processes. All communication goes through the disk:

```
                   config/            data/            models/           runtime/
                   ───────            ─────            ───────           ────────
  bot          reads ──────►     reads ──────►    reads ──────►      WRITES ──────►
  portfolio    reads ──────►     reads/writes ►                       WRITES ──────►
  refresher    reads ──────►     WRITES ─────►    WRITES ─────►       writes status
  dashboard    reads + WRITES    reads ──────►    reads ──────►       reads only
                (overrides)
```

Two rules, from which the rest of the architecture follows:

1. **The engine is the only writer of book state.** `runtime/*/state.json` and the
   `*.jsonl` journals are written by the trading process alone. The panel never touches
   them — it reads. That is why two processes over the same bind mount need no lock at
   all.
2. **The panel is the only writer of configuration** — and not to `config/config.yaml`
   but to its sibling `config/config.overrides.yaml` (see §8).

Traffic in the other direction — the panel wanting to change something in the engine —
goes through the same disk: writing the overrides file (which the engine picks up by
itself) or the `runtime/restart_requested` flag file (the engine exits, Docker
resurrects it).

---

## 2. Three modules, one shared foundation

| | Module 1 — scalper | Module 2 — portfolio manager | Module 3 — ranking |
|---|---|---|---|
| Asks | "will this instrument rise" | "have the proportions drifted" | "which asset is stronger than the rest" |
| Clock | a 4h candle | a day | ~20 days |
| Decides by | an ML model (LightGBM) | a rule (drift/cadence) | a momentum ranking |
| Live book | yes (4 variants) | yes (1) | **no** — a study only |
| Data | Binance via CCXT | Yahoo Finance | both sources |

Shared by all of them: `execution/fills.py` (the cost model), `engine/state.py`
(`RuntimeStore` — persistence and journals), `backtest/metrics.py` (Sharpe, drawdown,
exposure) and the panel.

This is not sharing to save lines. **The backtest and paper trading go through the same
fills file**, so "what the backtest measured" and "what the bot does" are literally the
same execution path — not two implementations of one contract that diverge at the first
fix.

---

## 3. Module 1: the path from a candle to an order

### 3.1 Data

`scripts/download_data.py` → `data/ingestion.py` → Parquet, one file per (exchange, pair,
interval): `data/binance_BTC-USDT_4h.parquet`.

- Downloading is **incremental**: on a later run it fetches only what is missing — from
  the last stored candle forwards, and with a larger `--days` also backwards, before the
  oldest one.
- **A candle still open is discarded** (`df[df.timestamp < cutoff]`). The engine makes the
  same cut at startup (`raw[:-1]`) and in the feed. An open candle has moving
  `high`/`low`/`close` — a signal from it would be a signal from the future.
- `storage.find_gaps` reports holes in the history; it reads the interval from
  `TIMEFRAME_MS`.

### 3.2 Features (`features/engineering.py`)

26 columns (+4 optional ones from the funding rate), all computed strictly from the past
— `rolling`, `ewm`, `shift`, never `shift(-1)`. Four families:

- **returns and volatility** — log returns over 1/3/5/15/30/60 bars, standard deviations
  over 15 and 60, and their ratio (is volatility rising right now);
- **classic indicators** — RSI 14, ATR normalised by price, EMA 9/21 and the distance from
  EMA 50;
- **candle shape and volume** — `body_ratio`, the candle's range, a volume z-score;
- **regime context** — `trend_42`/`trend_180`, `mom_42`/`mom_180`, `vol_regime`, `dd_180`
  (how far below the 180-bar peak). At 4h that is roughly a week and a month.

The guarantee that "a feature's value at bar *t* does not change when later bars arrive"
is pinned by a test (`tests/test_features.py`), not merely by convention.

### 3.3 Labels: triple-barrier (`labeling/triple_barrier.py`)

The label is not "did the price rise" but **"entering here, would I have hit the
take-profit before the stop-loss"**. For a signal from bar *t*'s close:

- entry at **bar t+1's open** (not at t's close — you cannot buy that),
- barriers: `entry ± mult × ATR(t)`,
- scan bars t+1…t+H; the label is 1 only when the TP was touched **strictly earlier** than
  the SL,
- **a bar that touches both barriers counts as an SL**. We do not know the order of moves
  inside a bar, so we assume the worse case. The fill simulator makes the same assumption,
  so the label and the execution do not disagree about the same bar.

The last `H+1` bars cannot be labelled (they have no full horizon) — they stay NaN and
drop out of training.

### 3.4 Training: walk-forward with a purge (`models/train.py`)

Expanding windows: fold *i* learns on everything from the start to
`test_start − purge`, and is tested on the following slice. The key part is the **purge
gap** ≥ the label's horizon: without it a label from the end of the training set peeks
into bars that are already in the test — and the AUC comes out pretty because of leakage,
not because of signal.

The model: LightGBM (`n_estimators=400`, `learning_rate=0.03`,
`min_child_samples=200`). Without `libomp` (common on macOS) the code steps down to
scikit-learn's `HistGradientBoostingClassifier` by itself — the same interface, no native
dependencies.

`ModelBundle` stores **its own feature-column list** alongside the model. The backtest and
the engine read that list from the bundle rather than from a constant in the code —
otherwise adding a feature would silently invalidate every saved model.

### 3.5 The cost model (`execution/fills.py`)

Three functions and one decision: **a taker pays slippage plus a fee, a maker pays a fee
at the limit price**. By default 0.1% fees and 2 bps slippage, from `config.yaml`.

```
buy_fill:  effective_price = price × (1 + slippage),  fee = notional × taker_fee
sell_fill: effective_price = price × (1 − slippage),  fee = notional × taker_fee
```

`check_bracket_exit` answers "which barrier does this bar touch" — and it is the function
called by **both** the backtester and the live engine.

### 3.6 The engine (`engine/loop.py`)

Two layers, deliberately separated:

- **`Book`** — one book (cash, positions, risk, its own `RuntimeStore`). Fully
  synchronous: you feed it closed candles through `on_candle` and inspect its state. That
  is why it can be tested without network and without asyncio.
- **`TradingEngine`** — a thin async layer. It streams candles **once** and distributes
  each closed one to every book. Four A/B variants do not mean four times the requests to
  the exchange.

What happens on one closed candle, in this order:

```
on_candle(symbol, bar)
  1. append the bar to the buffer (last warmup + horizon + 50 bars)
  2. _maybe_reload_models()   – has the refresher swapped the model?
  3. _maybe_reload_config()   – has the panel changed parameters? (§8)
  4. _manage_position()       – TP / SL / timeout on an OPEN position
  5. _maybe_enter()           – only now consider a new entry
  6. append a row to equity.jsonl
  7. check the alarms (kill-switch, drawdown)
  8. write state.json (atomically: tmp + os.replace)
```

The order 4 → 5 is not accidental: a position must get its chance to close before the
"max open positions" limit blocks anything else.

**An entry** must pass four gates: there is no position on this symbol already, the buffer
exceeds `warmup_bars`, `RiskManager.can_open` allows it, and the model gives a probability
≥ `prob_threshold`. Every "no" lands in `signals[symbol]` with a reason (`warmup`,
`risk_blocked`, `below_threshold`, `in_position`, `features_nan`, `no_atr`) — that is the
source of the "Model: why it is not trading" tab.

**An exit**: TP, SL or a timeout after `horizon_bars`. The timeout has an exception
(`_maybe_rollover`, the `strategy.rollover` flag): if the deadline passes while the signal
is still above the threshold, the position is **extended** — new TP/SL from the current
ATR, a new deadline — instead of being closed and immediately reopened on the same candle
for double the fee and slippage. An explicit calculation decides, not the exit type alone:

```
edge = direction × (exit_price − candle_close)      what exiting here is worth
extend  ⟺  edge ≤ round-trip cost (2 × fee + 2 × slippage)
```

At a timeout both prices are the same candle's close, so `edge` = 0 and the condition
always holds. **A take-profit nevertheless never qualifies** — and that is the most
interesting result in this module. Extending rollover to TP exits looked spectacular in
the backtest (average result +146.6% → **+182.8%** over 5.5 years and ten pairs, every
pair in the black), but a TP is detected from the candle's high: a touch **inside** the
candle, settled at the barrier price, i.e. a trade that happened before the candle closed.
Declining it after seeing where the candle closed is reading from the future — and it
scores like reading from the future. The honest version, limited to timeouts, gives
+146.56% → +146.67% and 18 USDT less in fees. Three hundred times smaller, and that is
how much of it was true.

A stop-loss never extends: that is abandoning a risk limit, not saving on a fee. On a day
with an active kill-switch rollover is disabled too — because the re-entry it replaces
would also have been blocked.

### 3.7 Risk (`risk/manager.py`)

Three simple rules, deliberately without finesse:

- **position size** = `position_pct` × current equity (not the initial capital — the
  sizing shrinks itself after losses);
- **exposure ceiling** = `max_open_positions`. Crypto pairs are heavily correlated, so
  open positions usually move the same way anyway; 5 × 10% = 50% of the account in the
  market. The ceiling is not a comfort setting: on eighteen pairs it is the **strongest
  effect measured in this project** — a cap of 3 beats a cap of 10 by +4.5 pp per window,
  in 8 windows of 10 (t = +2.7 to +3.5). A wide board pays as a **pool to choose from**,
  not as a list to fill (§7.1);
- **a daily kill-switch**: after a realised loss ≥ `daily_loss_limit_pct` of the day's
  starting capital — no new entries for the rest of the UTC day. Existing positions still
  close. The day is part of the state (`snapshot`/`restore`), so a container restart does
  not clear the limit.

### 3.8 The feed and network failures

A WebSocket (`ccxt.pro`) with an **automatic fallback to REST polling** when it breaks. A
candle is distributed only once we see its successor — that is the definition of "closed".

A separate `_ticker_loop`, every 60 s, refreshes valuations for the panel through
`mark_to_market` — and **never trades**. The panel shows a live "what you have" even
though decisions are made once every 4 hours.

Three things here look redundant and are not (each has its own changelog entry):

- **Retry with backoff at startup.** Without it the process died on `fetch_ohlcv` and
  `restart: unless-stopped` came back into the same failure — 826 restarts over five
  hours. Now: 5 s → 10 s → … → 300 s, indefinitely, because a 4h bot loses nothing by
  waiting.
- **The connection alarm gets closed.** A `connection` with `ok=False` is a state, not an
  event — so once the network returns, its pair with `ok=True` is appended.
  Unconditionally at every startup, because a hanging failure usually belongs to the
  **previous** container.
- **The log is not flooded.** The traceback goes out once, then only a `WARNING` with a
  counter. Synology does not rotate container logs.

### 3.9 What stays on disk

Per variant, in `runtime/<name>/`:

| File | Contents | Who reads it |
|---|---|---|
| `state.json` | a snapshot: cash, positions, last prices, per-symbol signals, risk state, `live_config` | the panel (written atomically, so it never catches half of it) |
| `trades.jsonl` | **closed** trades (entry, exit, reason, fees, PnL) | the panel: log, analytics |
| `equity.jsonl` | one row per processed candle: equity and cash | the panel: the equity curve, exposure |
| `alerts.jsonl` | events: open, close, rollover, kill-switch, drawdown, connection, config change | the panel: the timeline |

JSONL, not a database — deliberately. It keeps `tail -f` working on a live bot, `jq`, a
readable `git diff`, and a corrupted write costs one row rather than the file.

Beware a trap this format once set here: `trades.jsonl` gets a row only when a position
**closes**, so the trade journal alone knows nothing about what the bot is holding now.
Open positions live in `state.json`, and the panel has to read both sources.

---

## 4. The mechanics of the game: what the bot does at the table

Section 3 describes what the bot is built from. This one describes what it actually
**plays** — what its rules are, what it does in a typical turn, and what happens at the
edges.

### 4.1 The rules of the game

| | |
|---|---|
| **The board** | 18 USDT pairs, each independently |
| **A turn** | a 4h candle's close — 6 turns a day per pair, 108 decisions a day in total |
| **A hand** | at most 5 open positions at once, 10% of capital each |
| **Table limit** | 1 position per pair — no adding, no averaging down |
| **Direction** | long only by default; `direction: long_short` enables a second model |
| **End of turn** | take-profit, stop-loss, a timeout after 12 bars (2 days), or an extension |
| **Sent off** | a realised loss ≥ 3% of the day's opening capital — until the UTC day ends |
| **The stake** | virtual, as long as `mode: paper` |

The bot has no leverage, no trailing stop, does not scale into entries and does not move a
stop to break-even. Every position is **one bet with a payout and a deadline fixed in
advance**. That is a deliberate choice: with an edge near zero, every additional mechanism
only adds a parameter to fit.

### 4.2 The life of one position, with numbers

Capital 1000 USDT, ETH at 2000, ATR(14) = 40 USDT (2% of the price), the model gives
`p_long` = 0.58 against a threshold of 0.55.

```
1. SIZE          1000 × 10%  = 100 USDT  →  100 / 2000 = 0.05 ETH
2. ENTRY         2 bps slippage: 2000 × 1.0002 = 2000.40
                 0.1% fee: 0.10 USDT           →  100.12 leaves the cash
3. BARRIERS      TP = 2000.40 + 1.5 × 40 = 2060.40   (+3.0%)
                 SL = 2000.40 − 2.0 × 40 = 1920.40   (−4.0%)
                 deadline = now + 12 × 4h = 48 hours
4. WAITING       each candle: is high ≥ TP? is low ≤ SL? has the deadline passed?
                 a candle touching BOTH barriers counts as an SL
5. EXIT (TP)     sell at 2060.40 × 0.9998 = 2059.99, fee 0.10
                 PnL = 0.05 × (2059.99 − 2000.40) − 0.10 − 0.10 ≈ +2.78 USDT
```

A round trip costs **0.24% of the notional** (2 × 0.1% fee + 2 × 0.02% slippage), so about
0.24 USDT here. That is why the backtest report prints `median_tp_pct` next to
`round_trip_cost_pct`: if the median distance to the TP does not clear the round-trip cost
with room to spare, the strategy has nothing to live on — and that is exactly what
invalidated the idea of trading 1-minute candles.

The position goes into `state.json` immediately. It reaches `trades.jsonl` only at step 5
— at the close (§3.9).

### 4.3 Barrier arithmetic: why the threshold sits where it sits

TP = 1.5 ATR, SL = 2.0 ATR. The bot **risks more than it aims for** — so winning more
often than losing is not on its own enough:

```
break-even = SL / (TP + SL) = 2.0 / 3.5 ≈ 57% hit rate
```

It is no coincidence that the model is trained on precisely this event: the triple-barrier
label (§3.3) says "TP before SL" at the same multipliers, so `prob_threshold` compares
directly against that break-even. The default of 0.55 sits **below** 57% — the bot
knowingly admits bets with a slightly negative expected value from the barriers alone, in
exchange for playing more often.

Two caveats, so this arithmetic does not sound harsher than it is: it applies only to
exits through the barriers (a timeout exits at the close price, wherever that is), and it
assumes a calibrated model. But it explains why `prob_threshold` is the most frequently
adjusted parameter in the panel, and why one of the A/B variants tests 0.65.

### 4.4 What the bot does most of the time: nothing

This is the most important part of the mechanics and the easiest to overlook. In a
backtest a position is open on **6–11% of candles per pair**. For the other ~90% of the
time a turn ends with an entry in `signals[symbol]` and nothing else.

The reasons ranked, most frequent first:

| Reason | What it means |
|---|---|
| `below_threshold` | the model computed a probability and it came out too low — **the normal state** |
| `in_position` | this pair is already occupied |
| `risk_blocked` | the pair **wanted to enter**, but the slots are taken or the kill-switch is on |
| `warmup` | the buffer is shorter than 300 bars (after a fresh start with no history) |
| `features_nan` / `no_atr` | a hole in the data, or a candle with no range |

The order inside the engine matters here, and it used to be the other way round.
`_maybe_enter` asks the model **before** checking the limit, even though computing a
prediction costs more than glancing at a position counter. The reason is diagnostic: under
the old order a blocked pair had no probability computed yet, so the panel showed "held
back by the risk limit" next to an **empty** `p(long)` column — which could equally mean a
rejected 0.92 opportunity or a 0.31 non-event. On top of that the reason was lying: with a
full book, pairs far below the threshold, which would not have entered anyway, also landed
under `risk_blocked`. Now `risk_blocked` is always a **genuinely rejected opportunity**,
with the number beside it.

The panel reads this one-to-one in the "Model: why it is not trading" tab. Boredom in the
event log is not a fault — it is this strategy's default operating mode. A side effect:
**~70–80% of the account sits in cash**, and that fact is what forces two benchmarks in
the panel rather than one (§7).

### 4.5 The day the bot loses

The kill-switch counts only the **realised loss** since the start of the UTC day, measured
against the capital at its start. Once 3% is exceeded:

- new entries are blocked on every pair until UTC midnight (`can_open` returns
  `risk_blocked`);
- open positions **carry on living** — TP, SL and the timeout work normally, because
  closing is exiting risk, not entering it;
- extending a position (rollover) is disabled, because it replaces an entry that would
  have been blocked anyway;
- one `kill_switch` alarm goes to `alerts.jsonl`, not one per candle.

The day is part of the book's state, so a container restart in the middle of a bad day
**does not clear the limit** — `RiskManager.restore` reads back the date, the day's
opening capital and the realised result.

A drawdown alarm works separately: on a fall of `drawdown_alert_pct` from the peak one
notification goes out, and the threshold for re-arming it is half the alarm threshold —
hysteresis, so a book oscillating around the boundary does not send an alarm every candle.

Both of these safety catches watch for the day the market is bad. They do not watch for
the day the **settings** are bad: a raised exposure ceiling is not a loss until the
positions start falling, so nothing stops it. See §4.8 for that.

### 4.6 The rhythm of a day: what happens between candles

The engine does not sit idle between decisions. Four loops run in parallel, on very
different clocks:

```
every 5 s     REST polling (the fallback when the WebSocket dies) — looks for a new closed candle
every 10 s    _restart_watcher — has the panel asked for a restart?
every 60 s    _ticker_loop — fresh prices → mark_to_market → state.json.  IT DOES NOT TRADE
every 4 h     a candle closes → on_candle → the only moment an order can be created
```

Hence the apparent contradiction in the panel: "what you have" changes every minute while
trades appear a few times a week. The valuation is continuous; the decision is discrete.

With the network down the rhythm diverges deliberately: each loop has its own backoff
(5 s → 10 s → … → 300 s), after the third failed startup attempt a `connection` alarm with
`ok=False` goes to the journals, and on recovery its pair with `ok=True` (§3.8).

### 4.7 Four books playing the same dealt hand

`variants:` in the configuration is not four bots. It is **one stream of candles and four
independent portfolios** receiving exactly the same data at exactly the same moment:

| Book | Threshold | Sizing | Exposure ceiling |
|---|---|---|---|
| `prog_050` (primary) | 0.50 | 5 × 10% | 50% |
| `prog_055` | 0.55 | 5 × 10% | 50% |
| `prog_060` | 0.60 | 5 × 10% | 50% |
| `prog_065` | 0.65 | 5 × 10% | 50% |
| `ryzyko_100` | 0.50 | 5 × 20% | **100%** |

The threshold books differ in the threshold alone, so the difference between their equity
curves is a difference of threshold and nothing else. The last one has an **identical
signal to `prog_050`** — only the appetite changes. That is an experiment with its thesis
stated in advance: on the measured daily returns the Kelly-optimal fraction comes out at
~0.47, so 100% exposure is roughly twice too far, where the variance penalty (growing with
the square) overtakes the return (growing linearly). `primary_variant` pins `prog_050` to
the main screen, so that book can never appear there as "your portfolio".

Every book has its own directory under `runtime/`, its own cash and its own kill-switch.
What they share: the candles, the model and the executor.

### 4.8 The 9–10 Aug 2026 episode: what one click on the limit costs

The position ceiling is **the strongest effect measured in this project** (§7.1: a cap of
3 beats a cap of 10 by +4.5 pp per window, 8 windows of 10, t = +2.7 — the only result
that clears the usual significance bar). This episode is a live confirmation of it,
recorded here because it shows something a backtest will not: **how that change arrives
in time**.

The timeline of the `prog_050` book (all UTC, from `runtime/config_history.jsonl` and the
journals):

| When | What | Exposure |
|---|---|---|
| 09.08 12:00 | equity peak: 1019.95 USDT | 50% |
| 09.08 17:51 | from the panel: `max_open_positions` 5 → 10 | 50% |
| 09.08 20:00 | the first candle after the change: **four new positions** (ETH p=0.62, ADA 0.59, XRP 0.57, DOGE 0.58) | **90%** |
| 09.08 22:43 | from the panel: `max_open_positions` 10 → 5 | 90% |
| 10.08 04:00 → 16:00 | three of those four exit on the stop, the fourth hangs on | 50% |
| 10.08 17:39 | equity 1006.16 USDT | 50% |

**Breaking the fall down.** From the peak to the end of 10 Aug:

- an equal-weight basket of the traded pairs: **−1.60%** (ETH −2.57%, LTC −2.60%, BTC
  −1.42%) — that is the market, and it set the direction;
- the fair bar (`matched_exposure_curve`, §7): **−1.04%**; the book: **−1.30%**;
- the four positions opened on the 20:00 candle: **−7.07 USDT**, i.e. **51% of the whole
  drawdown**. Without them the book would have ended at 1013.23 instead of 1006.16, and
  the drawdown would have been −0.66% instead of −1.35%.

**The control that separates the market from the settings.** `prog_065` (too few signals
to make use of the free slots) and `ryzyko_100` (no cash for more) took not one position
under the raised limit — and they fell **−0.90%** and **−1.34%**. That much was the
market; the rest, for `prog_050` and `prog_055` (where an analogous four positions cost
−6.59 USDT), was exposure.

**The conclusion that went into the panel.** The loss did not come from the model
ceasing to work — the bot lost to passively holding the same market at the same exposure
by 0.26 pp, and the rest was the market's direction multiplied by exposure. It came from
exposure being nearly twice its usual size for five hours, landing squarely on a decline.
The click that did it said neither how many pairs were queued for the new slots nor — more
importantly — that **reverting the limit closes nothing**: a change upwards takes effect
on the next candle, a change downwards only once the surplus positions close on their own.
Since 0.1.13 the settings screen shows both (§8.1).

---

## 5. Module 2: the portfolio manager

The same skeleton, a different clock and a different decision.
`PortfolioBook.on_day(day, prices, panel)` instead of `on_candle`.

The logic fits in four pure functions (`portfolio/allocator.py`, zero I/O):

```
effective_weights(history, base_weights, trend)  → target weights (optional trend filter)
max_drift_pct(...)                               → the largest divergence, in pct. points
should_rebalance(days_since_last, drift, cfg)    → cadence OR the drift threshold
rebalance_orders(...)                            → orders; sells before buys
```

Sells are sorted before buys so the freed cash has something to fund the buys with. The
trend filter (**off** by default) parks an asset below its `ma_days` average in the
`safe_asset` or in cash.

A rebalance is **idempotent within a day** — repeating it on the same day changes nothing.
That is why the loop can wake every 6h with no risk of double execution, and why
`--backfill` can push the entire history (5452 days) through exactly the same code as live
trading.

### 5.1 Mechanics: what a year in this book's life looks like

The rules are the inverse of module 1's — there is no forecast, there is **a band and a
deadline**:

| | |
|---|---|
| **The board** | 3 ETFs: SPY 50% / TLT 30% / GLD 20% |
| **A turn** | one trading day |
| **The trigger** | 90 days since the last rebalance **OR** any weight off by ≥ 5 pct. points |
| **The move** | sell what there is too much of; buy what there is too little of; return to target weights |
| **End of game** | there is none — the book is always 100% invested |

A typical year is **2–4 moves**. The rest of the days end with a row appended to
`equity.jsonl` and nothing else. An example of one turn that changes something:

```
Value $11,000 after a good quarter for equities:
  SPY  $6,160  (56.0%)   target 50%  →  $5,500    SELL $660
  TLT  $2,750  (25.0%)   target 30%  →  $3,300    BUY  $550
  GLD  $2,090  (19.0%)   target 20%  →  $2,200    BUY  $110

max drift = 6.0 pts ≥ 5.0  →  rebalance
sells go first, so they have something to fund the buys with
```

Notice what just happened: the bot **sold what was rising** and bought more of what was
falling. That is not a bug, that is the entire strategy — and it is the same reason it
loses to buy & hold by 33 points over ten years, trimming the winner during a bull run,
while having a 9.6-point shallower drawdown. The value is discipline, not alpha.

Three details of the behaviour that are easy to miss:

- **The first day is an exception.** A fresh book holds $10,000 in cash and has no drift to
  measure, so `on_day` performs an `initial_allocation` unconditionally, outside the
  cadence rule.
- **Buying is limited by cash**, and selling by holdings (`settle_orders`). A fee will
  never push the book into overdraft, even when the rounding does not line up.
- **The trend filter is off and should stay off.** Switched on, it turns a rebalancer into
  a strategy: an asset below its 200-day average lands in TLT or in cash. That is a field
  for experiments, not an improvement — the README shows it costs return in a bull market.

---

## 6. Module 3: cross-sectional ranking (a study)

There is no book and no container — there is a script and a report. The signal is
`lookback_days` of momentum **skipping** the last `skip_days` (the freshest move tends to
revert; counting it would mix a reversion signal into a momentum signal). `select_legs`
trims the legs so they do not overlap — with a narrow universe, 5 long + 5 short out of 8
names would be buying and selling the same thing.

The same code runs on crypto and on ETFs, over **four disjoint windows**, and the report
shows all of them — because three times in this project the "best" result from a single
window turned out to be noise.

### 6.1 Mechanics: one turn of the ranking

```
every ~20 days:
  1. compute a score for each of the 25 (crypto) / 29 (ETF) assets:
     the return from day −125 to day −5  ← the last 5 days deliberately skipped
  2. sort; take the 5 strongest (long) and the 5 weakest (short)
  3. trim the legs so they do not overlap
  4. rebuild the basket to equal weights; costs through the same fills.py
  5. hold for the next 20 days, looking at nothing
```

Three behavioural differences from module 1, which are the substance of this study: the
bet is on the **difference between assets** rather than on the market's direction; there
is no stop-loss and no take-profit (a position lives exactly until the next re-ranking);
and there is no learning here at all — the signal is an explicit formula, not a model.

That is why the bar differs per variant: long-only is measured against a buy-and-hold
basket, and long-short against **cash** — a book with 0.4% net exposure is practically
market-neutral, so comparing it with a fully long basket would flatter it in every
downturn.

---

## 7. The backtest and honest measurement

`backtest/runner.py` is event-driven and goes through `fills.py` (§3.5). Beyond that, a
few things in `backtest/metrics.py` change how a result should be read:

- `avg_exposure_pct` and `time_in_market_pct` — how much of the account is really in the
  market;
- `return_on_risked_pct` — the result recomputed against the money that played;
- the benchmark is computed **twice**: "all in the market" and "matched to the bot".

The reason is simple: the scalper holds ~20–30% of the account, so comparing against
someone who put in everything praises the bot merely for being **absent** during the
falls. The exposure conversion deliberately declines to show itself when the bot was in
the market very rarely — a ×166 multiplier is not information, it is an artefact.

`scripts/research/` is a separate set of scripts answering "does this have any edge at
all", on three rules: disjoint windows with the model retrained from scratch, the same
cost model as production, and **naive controls** (always long, always short, at random, do
not trade). A strategy that does not beat the controls has proved nothing.

### 7.1 A per-pair backtest versus a book backtest (`backtest/book.py`)

`runner.py` counts **one pair on its own account, with no position limit**. That is the
right question when judging a model, and it is what the refresher's gate asks. It is,
however, **the wrong question about the board**: since every pair gets its own capital and
its own unlimited slots, adding pairs raises the average by definition — it appends
another account, not another competitor. A live book has one portfolio and
`max_open_positions` slots.

`book.py` counts that competition: one shared timeline across all pairs, one pot of cash,
the same `RiskManager` the engine uses (so the cap and the kill-switch are not written a
second time here) and an explicit allocation rule — `fcfs` (the order from the config,
i.e. what the engine does) or `best_first` (the highest probability wins). It returns one
number `runner.py` cannot produce: **how many signals the book threw away for lack of a
free slot**. At 18 pairs and a cap of 3, that is ~3000 candidates over 10 windows.

Two deliberate differences from `runner.py`, both in the engine's direction, because it is
the engine being modelled: position size is computed from **equity** rather than cash
(with a shared portfolio the cash version quietly shrinks each successive position), and
`maker` mode is rejected with an exception — a resting order would either hold a slot or
not, and there is no answer in the engine to copy, because the engine trades taker.

What this module does **not** change: the promotion gate in `refresh.py` still measures
"model versus naive controls" per pair. That is a different question and was deliberately
left untouched.

---

## 8. Configuration: what applies hot, and what needs a restart

The panel **never writes to `config/config.yaml`**. That file is a documented baseline —
it carries comments explaining why 4h, why a 2000-day window, why the `ryzyko_100` book
exists. `yaml.safe_dump` would delete all of them on the first write. Instead
`config/config.overrides.yaml` is created and merged in by `load_config`, so "restore
defaults" is a deleted key and a `git diff` shows only what really changed.

Two guarantees from `config_store.py`:

1. **nothing invalid reaches the disk** — a change is merged and validated through the
   pydantic model *before* being written;
2. **every change is journalled** (`runtime/config_history.jsonl`) — changing parameters
   on the fly turns the equity curve into a blend of two strategies, and the journal lets
   the panel draw the seam rather than quietly average over it.

Fields fall into two classes:

- **HOT** (`prob_threshold`, `tp/sl_atr_mult`, `horizon_bars`, `position_pct`,
  `max_open_positions`, fees…) — `Book` reads them off `self.cfg` on every candle, so they
  apply on the next bar without a restart.
- **RESTART** (`exchange.symbols`, `timeframe`, `warmup_bars`, the `variants` list,
  `initial_capital`…) — read once in `__init__` or in `run()`. The panel writes a
  `runtime/restart_requested` flag, `_restart_watcher` sees it, the engine **saves the
  books and exits**, Docker resurrects it, and `Book.restore()` reads back the cash and
  positions. The panel has no Docker socket and should not have one.

The change sensor itself is a **hash of the contents** of both files, not an mtime — and
that is a fix that cost one real bug. An `mtime` compared with `>` was blind to three
things at once: deleting the file (restoring a default!) gave 0.0, i.e. "never newer" —
forever; two writes in the same second merged into one; and uploading an older copy was
ignored. The consequence was the same every time: the panel shows the new parameters while
the bot trades on the old ones for the rest of the container's life.

A symmetric detail: **a failed configuration read is not remembered as done**. The old
code ticked the file off before trying to load it — one unlucky read froze a book until a
restart.

The model swapped in by the refresher is watched by an ordinary `mtime`, and that is the
right choice: the file is megabytes (hashing it on every candle would not be free), only
one process swaps it, and nobody deletes it.

### 8.1 Mechanics: what happens after clicking "Save"

```
panel                                        engine (each of the books, separately)
─────                                        ──────────────────────────────────────
1. pydantic validation (merged config)
2. write config.overrides.yaml (atomic)
3. a row into config_history.jsonl
   (who, when, from what to what)
4a. a HOT field   → done, wait                 …each candle: has the content hash changed?
                                               → load it, compare field by field
                                               → swap self.cfg, alarm "settings changed:
                                                 prob_threshold: 0.55 → 0.60"
                                               → from this bar it trades the new way
4b. a RESTART field → write the flag           …every 10 s: is the flag newer than my start?
    runtime/restart_requested                  → save the books, cancel the feeds, exit
                                               → Docker resurrects it, restore() comes
                                                 back with the cash and the positions
```

The change is visible from the other side: `state.json` carries `live_config` — the
parameters the book is **currently enforcing** — and the settings screen compares them with
the disk and warns on a divergence. The warning waits for the candle at which the change
should have taken effect, and compares each book against its own variant, so it neither
cries wolf right after a save nor mistakes `ryzyko_100` for a fault.

Changing parameters on the fly turns the equity curve into a blend of two strategies — and
that is the reason point 3's journal exists. The panel draws the seam rather than quietly
averaging.

**Two risk changes ask before they take effect.** Raising the exposure ceiling
(`position_pct × max_open_positions` — either half of it) opens a confirmation dialog,
because the effect arrives one candle later and cannot be taken back: positions opened
under the higher limit live until their target, their stop or their deadline, and merely
restoring the lower value closes none of them. The "Risk" section also shows how many
pairs are **queued** for a freed slot — counted from `state.json` as signals rejected by
the ceiling alone (the kill-switch does not count, because raising the limit will not
unblock it). That number only became meaningful in 0.1.12: before then the engine checked
the limit **before** asking the model, so a rejected pair had no probability attached.
Where all this comes from: §4.8.

---

## 9. The refresher: a weekly gate

`scripts/refresh.py`, in a `sleep 604800` loop:

1. fetches fresh candles (incrementally),
2. trains a **candidate** without the last `validation_days` days,
3. backtests it on that window — data it has never seen — alongside naive controls on
   exactly the same bars,
4. **the gate**: it promotes only a candidate that is not a catastrophe, beats "do not
   trade" and beats **every** naive control,
5. on passing: trains a final model on everything and saves it under the production name.

The bot picks the new file up through `_maybe_reload_models` on the next candle — no
restart. Exit codes: `0` = promoted, `2` = the gate refused (the old model stays), `1` =
error.

The gate used to compare against buy & hold — and that was nearly free to pass in a
falling market: a candidate that barely trades returns ~0% and "beats" a benchmark that
lost 17%. Naive controls are attainable alternatives, so beating them means something.

### 9.1 Mechanics: what happens in a week when the gate refuses

The default outcome of this ritual is **"nothing changes"** — and that is how it should
be.

```
week N        fetch data  →  train a candidate  →  OOS backtest
              candidate −0.38%  vs  "do nothing" +0.00%   →  REFUSED
              models/*.joblib untouched, the bot carries on with the old model
              runtime/refresh_status.json: {"status": "gate_failed", "detail": "..."}
              exit code 2; docker-compose logs the message and sleeps 7 days
```

The last real run (2026-08-07) looked exactly like that. Three consequences worth stating:

- **The bot never stops because of a refusal.** The production model is an independent
  file; the candidate is created beside it and dies if it does not pass.
- **The swap needs neither a restart nor synchronisation.** The refresher writes the file,
  and each book notices the new `mtime` on its next candle (§8, the paragraph about the
  model). Four books may switch on different bars — and that does no harm, because the
  model is stateless.
- **A refusal is visible in the panel**, not only in the container log:
  `refresh_status.json` is read by the "Health" tab. A gate nobody hears about is, after a
  few months, indistinguishable from a gate that is switched off.

That same file is the only writer of `data/` on module 1's side: how much history the
refresher fetches also determines how much the bot ever collects
(`model.train_window_days`).

---

## 10. The panel (`dashboard/`)

Streamlit, **read-only** as far as book state goes; it writes configuration only.

- `app.py` — the main screen, metrics, curves, the module switch
- `journals.py` — reading `*.jsonl` with a cache keyed by the **file's fingerprint**, not
  by a TTL. Streamlit re-runs the whole script on every click; without this, dragging a
  slider would re-parse the entire equity journal. Keying on content rather than time
  means "a new row is visible immediately, not once a cache expires".
- `humanize.py` — numbers and events into plain sentences ("Bought ETH for $100 — now +$2")
- `price_view.py` — the price chart with trade markers; it reads `trades.jsonl` **and** the
  open positions from `state.json`
- `config_view.py` — the settings screen; it calls `auth.current_user()` before every write
- `research_view.py` — module 3 and the correlation screen, from the newest report in
  `models/reports/`
- `i18n.py` / `locales/` — which language the viewer reads. The catalogues are plain
  dicts; the dashboard keeps the choice per session, because one process serves several
  viewers.
- `auth.py` — today it returns `"local"` and `True`. It is a seam, not a security system:
  when a login appears, one implementation changes rather than every write site.

### 10.1 Mechanics: the life cycle of one click

Streamlit has no events — it has a **complete re-run of the script** on every interaction
and every auto-refresh (60 s, because a 4h candle closes six times a day and asking more
often only costs CPU).

```
click / refresh tick
   → app.py runs from its first line
   → load_config()                       (cheap)
   → journals.load_*()                   ← cache keyed by the FILE'S FINGERPRINT
        the file has not changed → from cache, zero parsing
        the engine appended a row → parse and show it at once
   → st.session_state holds what the human chose
        (the expanded instrument, the 7d/30d range, the module, the language)
   → render
```

Two decisions follow directly from this model:

- **Cache on content, not on time.** A TTL would give a window in which the panel shows a
  moment-old state although the file is already new. A file fingerprint means "a new row is
  visible at the next refresh, not a second later".
- **A choice has to live in `session_state`.** Without that, the refresh would close an
  expanded price chart — an interface element would shut itself before anyone had a chance
  to look at it.

The panel never computes anything heavy live. The "Research" tab reads the **newest saved
report** from `models/reports/` and recomputes only on data already on disk, on an explicit
request — downloading during a render would block the whole screen.

What the panel cannot do by definition: start a container, kill the bot, close a position.
It has exactly two channels of influence over the engine — the configuration overrides and
the restart flag (§8). There is no Docker socket, and there should not be one.

---

## 11. A map of the directories

```
src/trademon/
  config.py, config_store.py   configuration: a pydantic model + safe writes from the panel
  i18n.py, locales/            which language the reader gets; one dict per language
  data/        ingestion.py    downloading through CCXT (incremental)
               storage.py      Parquet, gap detection
               funding.py      funding rate (optional features)
  features/    engineering.py  26 (+4) features, strictly from the past
  labeling/    triple_barrier.py
  models/      train.py        walk-forward + purge, LightGBM or a fallback
  backtest/    runner.py       event-driven, one pair on its own account
               book.py         the whole book: shared cash and a shared position cap
               metrics.py      Sharpe, drawdown, exposure, return on risked
  execution/   fills.py        the cost model — SHARED by the backtest and production
               executors.py    paper / live (CCXT)
  risk/        manager.py      sizing, the position ceiling, the kill-switch
  engine/      loop.py         Book + TradingEngine (module 1)
               state.py        RuntimeStore: state.json + JSONL
               notify.py       webhook (Discord/Slack)
  portfolio/   allocator.py    pure rebalancing functions
               book.py         the daily book
               engine.py       the loop + --once / --backfill
               correlation.py  the diversification screen
  crosssec/    signal.py       cross-sectional momentum (module 3)
               backtest.py, validate.py, panels.py
  research/    lab.py          disjoint windows, naive controls
               log.py          the experiment journal
  dashboard/   app.py + the views

config/    config.yaml (the baseline, with comments) + *.overrides.yaml (from the panel)
data/      Parquet per (exchange, symbol, interval)
models/    *.joblib + reports/
runtime/   <variant>/{state.json, trades.jsonl, equity.jsonl, alerts.jsonl}
           config_history.jsonl, experiments.jsonl, restart_requested
scripts/   download_data, train, backtest, refresh, portfolio_backtest,
           correlation_screen, crosssec_backtest, research/*
```

---

## 12. What this system deliberately does not do

- **It does not trade on an open candle.** Nowhere. Three places cut it off independently.
  The ticker refreshes the valuation every minute and has no right to buy anything.
- **It does not average down, add to a position, or move a stop.** One position per pair,
  with the payout and the deadline fixed at entry (§4.1). Every additional mechanism is
  another parameter to fit when the edge is near zero.
- **It uses no leverage.** A short is accounted for futures-style (margin = the entry
  notional), but in the backtest and on paper; on spot it cannot be executed.
- **It does not change structure without a restart.** Better to go down for 20 seconds than
  to trade a configuration half of which has taken effect.
- **There is no database and no API between processes.** Four containers, one directory,
  one writer per file.
- **It does not pick a winning window.** The reports show every window, including the bad
  ones.
- **It does not model funding cost** on crypto shorts (module 3 says so outright), nor
  does it correct for **survivorship bias** in the universe of pairs.
- **It does not pretend TP settlement is certain.** The engine wakes only at a candle's
  close, and yet settles a take-profit at the barrier price — assuming an order that
  executed inside the candle. That assumption is optimistic and underlies every
  measurement in this project's history; it is recorded as an open question rather than
  swept under the rug.
- **It does not protect the panel with a login** — it is meant for a local network.
  `auth.py` exists so that this can be changed in one place one day.
- **It does not send real orders without a deliberate change** of `mode: live` in the
  configuration and API keys in `.env`. By default everything is paper.
