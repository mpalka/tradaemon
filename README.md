# TraDaemon 👹💰

*English · [Polski](README.pl.md)*

> **This is an educational project.** Everything runs as **paper trading** — simulated
> money, no real orders. It is not investment advice and not a product. The crypto
> module's measured edge is **approximately zero after costs**, and this README says so
> in the places where the numbers say so. Before you take any of it seriously, read
> [what to expect](#what-to-expect-from-a-bot-like-this) and [DISCLAIMER.md](DISCLAIMER.md).

Three parallel modules for learning how algorithmic trading and portfolio discipline
actually behave when you measure them honestly.

1. **Module 1 — Crypto scalper** (LightGBM, 4h candles, 18 USDT pairs, paper trading)
   Short-horizon machine-learning trading with triple-barrier labelling, walk-forward
   validation and a backtest that charges costs. The backtest shows an edge of ~0 after
   costs — so the module serves as an **educational laboratory**, not a money machine.

2. **Module 2 — Portfolio manager** (ETF rebalancer, paper trading)
   Systematically restoring the target proportions of an SPY/TLT/GLD basket, with an
   optional trend filter. A 10-year backtest shows that rebalancing trims winners during
   a bull market — its value is discipline and risk reduction, not alpha.

3. **Module 3 — Cross-sectional ranking** (a study, no live book)
   Buy the strongest assets, sell the weakest — a bet on the difference *between* assets
   rather than on the market's direction. The same code on crypto and on ETFs, scored on
   disjoint windows. Result: still indistinguishable from noise, but the closest of the
   three.

The panel and the documentation are available in **English and Polish**. Pick your
language in the top-right corner of the dashboard, or with `?lang=en` / `?lang=pl` in
the URL.

---

## Getting started from scratch

This section assumes nothing: no Python, no data, no trained model. Follow it top to
bottom and you will end with a bot trading simulated money and a dashboard showing what
it did.

### 1. Prerequisites

| | You need | Check with |
|---|---|---|
| **Python 3.12 or newer** | the language everything runs on | `python3 --version` |
| **Git** | to get the code | `git --version` |
| ~1 GB free disk | downloaded candles and trained models | |

Optional but recommended:

- **`libomp`** — LightGBM's multithreading runtime. Without it the code automatically
  falls back to scikit-learn's `HistGradientBoostingClassifier`, which works fine and is
  only somewhat slower. Nothing breaks if you skip it.
- **Docker** — if you would rather run all four services at once; see [Docker](#docker).

<details>
<summary><b>Installing the prerequisites — macOS</b></summary>

```bash
# Homebrew (skip if you already have it): https://brew.sh
brew install python@3.12 git libomp
```

Apple silicon and Intel both work.
</details>

<details>
<summary><b>Installing the prerequisites — Linux (Debian/Ubuntu)</b></summary>

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git libgomp1
```

On Fedora/RHEL: `sudo dnf install python3.12 git libgomp`. On Arch:
`sudo pacman -S python git openmp`.
</details>

<details>
<summary><b>Installing the prerequisites — Windows</b></summary>

The simplest route, in PowerShell:

```powershell
winget install --id Python.Python.3.12 -e ; winget install --id Git.Git -e
```

Then **close and reopen PowerShell** so the new `python` and `git` are on your PATH.
LightGBM's Windows wheels bundle their own OpenMP runtime, so there is no `libomp` step.

If you prefer a Unix-like environment, [WSL2](https://learn.microsoft.com/windows/wsl/install)
works too — inside it, follow the Linux instructions instead.
</details>

### 2. Get the code and install it

The commands differ only in how the virtual environment is activated.

<details open>
<summary><b>macOS / Linux</b></summary>

```bash
git clone https://github.com/<your-account>/trademon.git
cd trademon
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # may stay empty; paper mode needs no keys
```
</details>

<details>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
git clone https://github.com/<your-account>/trademon.git
cd trademon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env   # may stay empty; paper mode needs no keys
```

If PowerShell refuses to run the activation script, allow it for this session:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`.
</details>

Once the environment is active your prompt shows `(.venv)`, and plain `python` and
`pytest` refer to it. **Every command below assumes an activated environment.** If you
would rather not activate it, prefix commands with `.venv/bin/` on macOS/Linux or
`.venv\Scripts\` on Windows.

Check that the installation is sound before going further:

```bash
pytest -q
```

294 tests should pass, and they need neither network nor data.

### 3. Download market data

Public Binance endpoints — no API key, no account.

```bash
python scripts/download_data.py --days 2000
```

This fetches roughly five and a half years of 1-minute candles for the 18 configured
pairs into `data/`. It takes a while and is the slowest step here. **Use the full
history**: on one year of data (a single bear regime) this project's conclusions came
out backwards — see [the note on data](#a-note-on-data). For a quick first look,
`--days 180` is enough to get the pipeline running, but do not trust results from it.

### 4. Train a model

```bash
python scripts/train.py
```

Walk-forward validation, with an AUC report per fold. The model lands in `models/`. The
engine refuses to start without one and will tell you so.

### 5. See what the backtest says

```bash
python scripts/backtest.py
```

Prints per-pair results after costs and writes an HTML report to `models/reports/`.
Expect an edge near zero — that is the honest result, not a broken installation.

### 6. Run the bot on simulated money

```bash
python -m trademon.engine
```

This is a **long-running loop**, not a one-shot command: it catches up on the candles it
missed, then waits for the next 4h close, and keeps going until you stop it with Ctrl-C.
The first run can take a few minutes while it loads history for all 18 pairs. It takes no
arguments — leave it in its own terminal, or use [Docker](#docker) to run it as a service.

Nothing here places a real order. `mode: paper` in `config/config.yaml` is the default,
and going live is a [separate, deliberate decision](#live-mode-module-1--a-deliberate-decision).

### 7. Open the dashboard

In a second terminal, with the environment activated:

```bash
streamlit run src/trademon/dashboard/app.py
```

Then open <http://localhost:8501>. Until the engine has run at least once the panel says
so rather than showing an empty chart.

### 8. Optional — the portfolio module

Independent of the above and needing no trained model. Daily data comes from Yahoo
Finance, free and keyless.

```bash
python scripts/portfolio_backtest.py --years 10   # rebalancing vs buy & hold
python -m trademon.portfolio --backfill           # replay the full history and exit
python -m trademon.portfolio --once               # one day and exit
python -m trademon.portfolio                      # the daily loop (Ctrl-C to stop)
```

The dashboard picks the portfolio books up on its own.

### Where things end up

Nothing outside the project directory is touched. Four directories are created on first
use and none of them are in git:

| Directory | Written by | Holds |
|---|---|---|
| `data/` | `download_data.py`, the refresher | downloaded candles (Parquet) |
| `models/` | `train.py`, the refresher | trained models and reports |
| `runtime/` | the engine, the portfolio loop | each book's state and journals |
| `.venv/` | you, in step 2 | the Python environment |

Deleting `runtime/` resets the paper books to their starting capital. Deleting `data/`
and `models/` means repeating steps 3 and 4.

---

## Docker

If you would rather not manage a Python environment, or you want all four services
running together:

```bash
cp .env.example .env   # must exist, may stay empty
docker compose up --build
```

This starts **four services**:

| Service | Role |
|---------|------|
| `bot` | Module 1: the crypto scalper, several A/B variants over 18 USDT pairs |
| `dashboard` | The panel on `localhost:8501` (both modules, beginner UI) |
| `portfolio` | Module 2: the portfolio manager, ETF rebalancing |
| `refresher` | Weekly retraining behind a safety gate (promotes only an improvement) |

Data, models and runtime state are mounted from `./data`, `./models` and `./runtime`, so
they survive a rebuild. Each service has its own log: `docker compose logs -f bot`.

> **The dashboard has no authentication.** It binds `0.0.0.0:8501` and lets anyone who
> can reach it change the running configuration. Keep it on a trusted local network and
> never port-forward it to the internet.

Deploying to a Synology NAS (built on the NAS, LAN only):
[docs/DEPLOY_SYNOLOGY.md](docs/DEPLOY_SYNOLOGY.md).

---

## The dashboard

### The beginner screen (the default view)

No jargon, in whichever language you picked:

- **"What you have"** — the portfolio's value and its change (🟢/🔴)
- **Bot status** — 🟢 running / 🔴 waiting, from the last market reading, plus a
  separate live line saying whether the exchange is reachable *right now*
- **"How it went"** — the equity curve against two grey buy-and-hold lines; 7d / 30d /
  all
- **"What the bot is holding"** — open positions as sentences ("Bought ETH for $100 —
  now +$2")
- **"Event log"** — a timeline with icons (opened, closed, loss limit hit)
- **Price preview** — instruments in both of those sections are clickable: clicking
  expands a price chart **under that row**, with the bot's trades (▲ buy, ▼ sell), the
  entry-price line and, when opened from the log, a marker at the moment of the event.
  Hovering shows a tooltip with the price and the 24h / 7d change. The choice is kept in
  the session, so the 60-second refresh does not close it.
- **"Details for the curious"** (collapsed) — the technical tabs

### Technical tabs

- **Analytics** — per pair, result distribution, exit reasons
- **Model** — why it is (not) trading: probabilities against the threshold
- **Variants** — the live A/B comparison of the parallel books
- **Experiments** — the backtest log
- **Health** — data freshness, kill-switch, alerts, refresher status
- **(Portfolio)** — when module 2 is selected: allocation, rebalances, weight drift

### The module switch (at the top)

**Crypto scalper · Portfolio manager · Research · Settings.**

The first two run a book and refresh themselves every 60 seconds. **Research** is
different: tools that hold no position and answer "does this idea hold up?". That tab
reads the newest saved report from `models/reports/` and can recompute it on data
already on disk (no downloading, so the panel never blocks):

- **Cross-sectional ranking** (Module 3) — the market × direction × window matrix, the
  "deviations from zero" measure, and a survivorship-bias warning;
- **Diversification screen** — the correlation table with verdicts; an `--as-of` run is
  labelled clearly so a historical screen cannot pose as a current one.

**Settings** writes to `config/config.overrides.yaml`, never to `config.yaml`, so the
documented baseline stays intact and "restore defaults" is a deleted key rather than a
retyped number. Fields marked ⚡ take effect on the next candle; 🔄 needs an engine
restart.

### Honest numbers: how much money is actually playing

The scalper has an exposure ceiling (`position_pct` × `max_open_positions` = 50%), so
most of the account sits in cash. That is **not a flaw in the strategy** — with an edge
near zero, putting more money in would only enlarge the loss. It is, however, a
measurement trap, and the panel now names it outright:

- **"in play: X% of the money"** — how much of the account is really in the market (the
  scalper ~20–30%, the portfolio manager 100%);
- **two numbers side by side** — "return on all the money" against "return on money at
  work"; the second is roughly 4× sharper and judges the signal more fairly;
- **two reference lines** on the chart — "all in the market" (light) and "matched to the
  bot" (dark). The dark one is the fair bar: comparing against someone who went all in
  praises the bot merely for being **absent** during the falls.

The conversion assumes linear scaling and **deliberately declines to show itself** when
the bot was in the market very rarely — in a per-pair backtest a position is open for
~6–11% of candles, so an average exposure of ~0.6% would multiply the result by 166. The
report then gives the plain facts instead: average exposure and time in market.

---

## Maintenance (automatic — Module 1)

The `refresher` service, once a week:

1. Downloads fresh data
2. Trains a candidate without the last `validation_days`
3. Runs an out-of-sample backtest on those days
4. **Gates it** — promotes the model ONLY if it is not a catastrophe (PnL > −10%) and it
   beats buy & hold over the same window
5. Swaps the model in; the bot hot-reloads it on its next candle, no restart

Manually: `python scripts/refresh.py` (exit 0 = promoted, 2 = the gate refused, 1 = error).

**Module 2** has no automatic training — it is a rebalancer, not a forecaster.

---

## Configuration

### Module 1: the crypto scalper

[config/config.yaml](config/config.yaml):

- `exchange.symbols` — the USDT pairs (18 of the most liquid by default)
- `exchange.timeframe` — the candle interval (4h)
- `strategy` — TP/SL in ATR units, holding horizon, probability threshold, rollover
- `costs` — fees and the slippage assumed on every fill
- `risk` — position size, maximum open positions, the daily kill-switch, the drawdown
  alert threshold
- `variants` — A/B: several configurations trade the same candles in parallel, each with
  its own `runtime/<name>/`, compared in the Variants tab. Omit for a single book.
- `primary_variant` — which book the beginner screen calls "your portfolio"
- `display_timezone` — the IANA zone timestamps are rendered in (the engine always
  stores UTC)
- `display_language` — `pl` or `en`, for everything with no viewer attached: engine
  alerts, webhook messages, printed reports. Dashboard viewers choose per session.

**Alerts**: an optional `ALERT_WEBHOOK_URL` in `.env` (Discord/Slack/Mattermost). By
default: the journal and the panel only.

### Module 2: the portfolio manager

[config/portfolio.yaml](config/portfolio.yaml):

- `symbols` / `base_weights` — the ETF basket (SPY 50% / TLT 30% / GLD 20% by default)
- `rebalance` — cadence in days and the drift threshold
- `trend` — the filter: hold an asset only above its moving average (educational; it
  reduces returns in a bull market)
- `costs` — the annual TER drag and per-transaction fees
- `initial_capital` — virtual capital (10,000 by default)

---

## Module 2: the portfolio manager (slow investing)

A second, independent module — **a rebalancer, not a forecaster**. Its value is
discipline and risk reduction, not alpha. Paper only; daily data from Yahoo Finance,
free and keyless.

```bash
python scripts/portfolio_backtest.py --years 10
```

Ten years (2016–2026) of the default SPY/TLT/GLD basket (50/30/20):

| Metric | Strategy | Benchmark (buy & hold) | Difference |
|---------|-----------|---------------------|---------|
| Return | +113.9% | +147.5% | −33.6 pts ❌ |
| CAGR | 7.94% | 10.38% | −2.44 pts |
| Sharpe | 0.77 | 0.69 | +0.08 |
| Max DD | −24.9% | −34.5% | +9.6 pts ✓ |

**The lesson**: rebalancing trims winners during an equity bull run — which is what
happens every quarter — but it does reduce drawdowns. An educational tool, not a way to
get rich.

### Paper trading

```bash
python -m trademon.portfolio --backfill   # replay the full history and exit
python -m trademon.portfolio --once       # one day and exit
python -m trademon.portfolio              # the daily loop (Ctrl-C to stop)
```

Unlike the crypto engine, this module *does* take `--once` and `--backfill`.

The dashboard discovers books from `runtime/portfolio/*/state.json` on its own and shows
capital, the drift of the weights from their target, a chart against the benchmark, a
rebalancing log and a health panel.

---

## The diversification screen (Module 2)

A question about risk, not about forecasting: **when the world market falls, what in the
basket does not fall with it?** The benchmark is `VT` (Vanguard Total World).

```bash
python scripts/correlation_screen.py                      # the last 10 years
python scripts/correlation_screen.py --as-of 2016-07-30   # what the method would have picked THEN
```

### Result: negatively correlated assets barely exist

Of 36 candidates over 119 months to July 2026, eight are negatively correlated with VT —
and **every one of them loses money by construction** (SH −14%/yr, VIXY −46%/yr). Among
the assets with a positive return, the lowest are UUP (−0.44) and gold (+0.21).

**The column that carries the meaning is the rolling range, not the average:**

| Asset | Correlation | 3-year range | CAGR |
|---|---|---|---|
| **GLD** | +0.21 | **−0.02 … +0.40** | **+11.8%** |
| TLT | +0.21 | −0.47 … **+0.75** | **−5.2%** |
| UUP | −0.44 | −0.67 … −0.28 | +1.3% |
| SH (inverse S&P) | −0.95 | −0.97 … −0.92 | −14.2% |

TLT looks like a diversifier on average, but it jumped to **+0.75** in 2022 — it stopped
protecting exactly when it was needed, and it lost 5.2% a year over the decade. That is
why the output is verdicts (`KANDYDAT` / `NIESTABILNY` / `TRACI` / `PUŁAPKA` — candidate,
unstable, loses, trap) rather than a ranking.

### The important part: a test with no knowledge of the future (`--as-of`)

Run on data **up to 2016**, the screen would have named **UUP and TLT** as the two best.
TLT then had a correlation of −0.27, never positive (max −0.08), and +5.4%/yr. A perfect
diversifier by this method. Applied over the following decade:

| Basket | Return | CAGR | Sharpe | Drawdown |
|---|---|---|---|---|
| by the 2016 screen (SPY/UUP/TLT) | +87.2% | 6.50% | 0.75 | **−15.4%** |
| current (SPY/TLT/GLD) | +112.5% | 7.87% | 0.77 | −24.9% |
| by the 2026 screen (SPY/GLD/UUP) | +179.5% | 10.87% | 1.06 | −18.1% |

**The method picked, in 2016, an asset that went on to fail** — because correlations and
returns are properties of a regime, and a 10-year window describes the regime that has
just ended. The third row looks best purely because it was chosen **after the fact**.

What survived the honest test: **the lowest drawdown (−15.4%)**. The screen does not
raise returns, but it does genuinely limit risk — and that is its honest value.

---

## Module 3: cross-sectional ranking (a study, no live book)

Instead of "will BTC go up" (Module 1's hypothesis, measured at ≈ zero) it asks: **which
assets are strongest relative to the others?** It buys the leaders, optionally sells the
laggards, and re-ranks every ~20 days. The bet is on the **difference between assets**,
not on the market's direction.

```bash
python scripts/crosssec_backtest.py --refresh        # download data and compute the matrix
python scripts/crosssec_backtest.py --market etf     # one market only
python scripts/crosssec_backtest.py --lookback 250 --rebalance 60
```

The same code runs on **25 crypto pairs and 29 ETFs**, in two variants (long only /
long-short), over **4 disjoint windows** — because three times in this project the "best"
result from a single window turned out to be noise. The report shows **every window** and
picks no winner.

### Result (2026-07): still zero, but more interesting

| Market | Variant | Return | Bar | Deviations from zero |
|---|---|---|---|---|
| crypto | long-short | **+66.3%** | cash | +1.11 — indistinguishable |
| crypto | long only | −9.6% | basket (−20.2%) | +0.80 — indistinguishable |
| ETF | long only | +57.7% | basket (+128.1%) | +1.08 — indistinguishable |
| ETF | long-short | −28.5% | cash | −1.04 — indistinguishable |

Crypto long-short is positive in **3 of 4 windows** and +66% over 5.5 years at 0.4% net
exposure (genuinely market-neutral) — the most interesting result in this project. **But
1.11 deviations from zero is not an edge**; you want ~2. And the ETFs, where
cross-sectional momentum is best documented in the literature, are **consistently
negative in 4 of 4 windows**. If the effect were a property of the method, it would show
up on both markets.

**The bar depends on exposure** (the same lesson as in Module 1): long-only is measured
against a buy-and-hold basket, long-short against **cash** — comparing a market-neutral
book with a fully long basket would flatter it in every downturn.

> **The main caveat: survivorship bias.** The 25 crypto pairs are the ones that
> **survived** to today and are liquid today. No LUNA, no FTT, none of the ones that
> died — and that skews the result in an unknown direction. On top of that, long-short
> on crypto needs perpetual futures rather than spot, and **funding cost is not modelled
> at all**. Treat it as measuring a hypothesis, not as a strategy.

---

## Live mode (Module 1 — a deliberate decision)

> **Module 2 (the portfolio) is paper-only** — rebalancing with real money is a separate
> decision involving a brokerage account, taxes and moving funds.

If you decide on live trading in Module 1:

1. **Don't** — the backtest shows an edge of ~0 after costs, and paper trading can look
   better through luck alone. Read [what to expect](#what-to-expect-from-a-bot-like-this)
   first.
2. If you really want to: verify the paper book first (several days, 10+ trades, no
   large losses).
3. Create a Binance API key with **TRADE permission only** — withdrawals disabled.
4. Put it in `.env` (template: [.env.example](.env.example)).
5. Change `mode: live` in `config/config.yaml`.
6. Test with a tiny position. Bugs, API glitches and edge cases are always possible.

---

## Architecture

The sketch below shows the flow of data. The full description of the mechanism — the
path of a single candle from the exchange to an order, who writes and who reads which
file, what applies hot and what needs a restart — is in [howitworks.md](howitworks.md).

### Module 1 — the crypto scalper

```
CCXT (1m, public API)
    ↓ Parquet (ohlcv_binance_*.parquet)
    ↓
Features (engineering.py) + triple-barrier labelling
    ↓
Walk-forward LightGBM ← Backtest (reconciled, with costs)
    ↓
Engine (loop.py: feeds > signals > orders > executors)
    ├─→ Paper executor (simulation)
    └─→ Live executor (CCXT) [optional]
        ↓
Runtime (state.json, trades.jsonl, equity.jsonl, alerts.jsonl)
        ↓
Dashboard (beginner screen + technical tabs)
```

**The key point**: the backtester and the paper/live engine share `fills.py` — the same
cost simulation — so paper testing exercises exactly the code that would go to
production.

### Module 2 — the portfolio manager

```
Yahoo Finance (daily, free)
    ↓ Parquet (ohlcv_yahoo_SPY_1d.parquet, …)
    ↓
Allocator (effective_weights, drift, rebalance_orders)
    ↓
Backtest (daily loop, benchmark = buy & hold once)
        ↓
Paper executor (rebalancing, simulated costs)
    ↓
Runtime (state.json, trades.jsonl, equity.jsonl, alerts.jsonl)
    ↓
Dashboard (portfolio view: allocation, rebalances, health)
```

**Both modules** share a `RuntimeStore` (persistence and journals), the cost model, the
metrics (including Sharpe annualisation) and the dashboard.

---

## Research ([scripts/research](scripts/research))

A separate set of scripts for answering "does this strategy have any edge at all". They
do not touch production — they compute and print a report.

Three rules they stand on, because without them the numbers lie:

1. **The model never sees the data it is judged on.** History is cut into disjoint
   windows; for each window the model is retrained from scratch on candles from before
   it only.
2. **The same cost model as production** — the backtest goes through
   `trademon.backtest.runner`, which shares `execution/fills.py` with the engine.
3. **Naive reference points.** "Always long", "always short", "at random". A strategy
   that does not beat those has proved nothing — and comparing only against buy & hold is
   easy to fool yourself with, since in a bear market anything able to go short looks
   brilliant.

```bash
# How much of the edge do fees eat? Same model, different exchange price lists.
python scripts/research/fee_grid.py --windows 30

# Are the profit/loss levels set well? A sweep of TP/SL combinations.
python scripts/research/rr_grid.py --windows 30 --every 3

# Is it worth picking trades by expected value rather than model confidence alone?
python scripts/research/ev_gate.py --windows 30

# Do a wider board and a different slot-allocation rule help the whole book?
python scripts/research/universe.py --windows 10 --window-days 90

# Does the model's probability carry information near its upper edge?
python scripts/research/prob_calibration.py
```

`universe.py` measures something the other scripts cannot, because they go through
`backtest/runner.py` — which gives **every pair its own wallet and unlimited slots**.
Counted that way, adding pairs can only raise the result, since it just appends another
account to an average. A real book has one wallet and `risk.max_open_positions` slots
that the pairs compete for. This script measures that competition through
[`backtest/book.py`](src/trademon/backtest/book.py) — shared cash, shared cap, the same
`RiskManager` the engine uses.

### Result (2026-08): the cap decides the outcome, not the board

The reason for the study was practical: `prog_050` with its cap raised to 10 from the
panel was holding **9 of 10 pairs** with 99 USDT of free cash. The board was exhausted —
the question was whether to add pairs.

Ten 90-day windows, a model retrained before each one, separately for each board, all
pairs competing for one wallet:

**1. Widening the board pays only under a tight cap** (18 pairs minus 10 pairs):

| cap | difference | windows in the black |
|---|---|---|
| 3 | **+0.78 pp** | 7/10 |
| 5 | −0.31 pp | 5/10 |
| 10 | **−2.32 pp** | 3/10 |

**2. The cap itself is the strongest effect this project has measured** (cap 3 minus cap 10):

| board | difference | windows in the black | t |
|---|---|---|---|
| 18 pairs | **+4.49 pp** | 8/10 | **+2.73** |
| 10 pairs | +1.39 pp | 5/10 | +0.90 |

This is the only result here that clears the usual significance bar. The mechanism is
coherent: a wide board is valuable as a **pool to choose from**, not as a list to fill.
At 10 slots the book takes everything that signals — 2609 trades instead of 1713 at the
same 80% exposure — so the extra pairs buy turnover and fees and nothing else.

**3. Giving the slot to the strongest signal does not pay**: −0.6 to +0.7 pp, five of six
comparisons at zero or negative, even where the cap turns away 3000 candidates. The
simplest explanation is that the model's probability is too weakly informative to sort
by. The ranking was **not adopted**. The engine kept only the diagnostic from it: it asks
the model **before** checking the cap, so the panel can show how large an opportunity the
cap turned away instead of an empty column next to "blocked by the risk limit".

18 pairs and a cap of 5 were adopted — widening is neutral at five, but five beats ten on
both boards, and three (the best measured) would keep half as much capital at work.

Every script splits its result by **what the market was doing** (up / sideways / down).
That is the most important table in the report: a strategy positive in only one kind of
market is a directional bet, not an edge.

Reports land in `models/reports/research_*.json`.

### A note on data

One year of history is not enough. On 2025–2026 data (a single bear regime) the
conclusions came out the opposite of those from 5.5 years. Download the full history:

```bash
python scripts/download_data.py --days 2000
```

---

## Tests

```bash
pytest
```

**294 tests**, covering:

- **Module 1**: backtest (prices, costs, benchmark), engine (paper), features, labelling
  (triple-barrier), fills (simple/maker/short), funding, risk (kill-switch)
- **Module 2**: allocator (drift, trend filter, no look-ahead), backtest (capital,
  benchmark, rebalancing costs), book (isolation between two books), Yahoo data parsing
- **Module 3**: signal (no look-ahead), disjoint-window scoring
- **Dashboard**: humanize (raw data to plain sentences), the config screen's arithmetic,
  the price preview, journals
- **i18n**: that every language defines the same keys with the same placeholders, and
  that no key used in the code is missing from a catalogue

Linting: `ruff check .`

---

## What to expect from a bot like this

This section exists because the honest answer is easy to lose among the tables above.
**The realistic expected outcome of running this bot with real money is a loss**, and
that expectation is not pessimism about this particular code — it is what the research
on retail trading consistently finds.

**What this project's own measurements say.** The crypto module's backtested edge is
approximately zero after costs. The portfolio module underperforms buy & hold over ten
years. The cross-sectional study reaches 1.11 standard deviations from zero where ~2 is
the usual bar. Not one of the three modules produced a result that clears the
significance threshold, and this README reports each of them as measured rather than as
hoped.

**What the wider literature says.** Read these yourself rather than taking a README's
word for it; the findings below are well replicated and easy to look up:

- Barber and Odean, *Trading Is Hazardous to Your Wealth* (2000), found that the most
  active individual traders underperformed the market substantially after costs — the
  more they traded, the worse they did.
- Barber, Lee, Liu and Odean's work on the Taiwanese market (2014) found that only a
  very small fraction of day traders — well under 1% — were reliably profitable net of
  fees, and that most losses persisted year after year.
- Chague, De-Losso and Giovannetti (2020), studying Brazilian futures day traders, found
  that among those who persisted for more than 300 days, the overwhelming majority lost
  money.
- López de Prado's work on backtest overfitting shows that if you try enough strategy
  variants on the same history, an impressive Sharpe ratio appears **by chance**. A
  backtest is not evidence unless you account for how many things you tried.

**Why this is structural, not bad luck.** Three forces work against a retail bot at once,
and this project can measure all three:

1. **Costs compound against turnover.** Every round trip pays a fee and slippage. A
   strategy trading often needs a real edge just to break even — `scripts/research/fee_grid.py`
   exists precisely to show how much of an apparent edge the fee schedule eats.
2. **The counterparties are professionals.** Whatever pattern a gradient-boosted model
   finds in public OHLCV data, firms with faster data, lower fees and more capital have
   already looked for. Anything easy is already priced in.
3. **Backtests overstate.** They assume fills at modelled prices, ignore outages, and are
   fitted to a regime that has already happened. This project has been surprised in that
   exact way — conclusions from one year of data reversed on five and a half.

**What this is genuinely good for.** Learning how the machinery fits together; building
the habit of measuring against an honest benchmark; developing an intuition for how
easily a plausible result turns out to be noise. Those are real, and they are the reason
the project exists. Making money is not on the list.

If you take one number away: the three modules here produced results of ≈0, −33.6
percentage points against the benchmark, and 1.11 standard deviations. Those are the
outcomes to expect.

---

## Licence and disclaimer

MIT — see [LICENSE](LICENSE).

The full disclaimer, in English and Polish, is in [DISCLAIMER.md](DISCLAIMER.md). In
short: educational project, paper trading, not investment advice, no warranty, and the
dashboard has no authentication so it belongs on a trusted local network only.
