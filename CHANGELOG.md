# Changelog

*English · [Polski](CHANGELOG.pl.md)*

Newest first. The version at the top of this file must match `__version__` in
`src/tradaemon/__init__.py`, and the Polish changelog must cover the same versions —
`tests/test_version.py` enforces both.

## 0.2.1 — 2026-08-31

- **The package is `tradaemon`, not `trademon`.** The project answered to three spellings
  at once: the repository was `Tradaemon`, the import was `trademon`, and the docs wrote
  `TraDaemon`. The missing "a" was the real inconsistency, and a public repository is a
  bad place to keep it. `src/trademon/` is now `src/tradaemon/`, and every import, command
  and path follows — `python -m tradaemon.engine`, `streamlit run
  src/tradaemon/dashboard/app.py`. The stylised display name stays **TraDaemon**, which is
  the same convention PyTorch and similar projects use: a lowercase identifier and a
  capitalised mark.
- Older changelog entries were rewritten to the new module path too. A history that cites
  paths which no longer exist is not more honest, only less useful.
- **If you already run this on a NAS, it is a migration, not a redeploy.** The compose
  project name comes from the directory, so `/volume1/docker/trademon` becomes
  `/volume1/docker/tradaemon`, containers become `tradaemon-bot-1`, and the Docker network
  becomes `tradaemon_default` — which matters if your DSM firewall rule was pinned to the
  old subnet. Move the directory before the rebuild and `runtime/` comes with it, so no
  book loses its history.

## 0.2.0 — 2026-08-31

The release that makes this repository publishable. Three things had to be true before
anyone else could use it, and one of them was a bug that had been invisible since the
first commit.

- **A clone of this repository did not import.** `.gitignore` had bare `data/` and
  `models/` entries, which match a directory of that name at **any** depth — so
  `src/tradaemon/data/` (4 files) and `src/tradaemon/models/` (2 files) were never
  committed. They are imported from a dozen places, including the engine, the backtester
  and the dashboard. Nobody noticed because the files exist on the machine the project
  was written on. Every top-level artefact directory is now anchored with a leading
  slash, and the six files are in git. `scripts/research/prob_calibration.py` was added
  too: it had never been committed, yet `config/config.yaml` and the changelog both cite
  it by name.
- **MIT licence, and a disclaimer that says what this is.** `LICENSE` plus
  `DISCLAIMER.md` in both languages, covering paper trading, the absence of investment
  advice, the lack of any warranty, and the fact that the dashboard has no
  authentication. `pyproject.toml` carries the licence and the classifiers.
- **The panel and the docs speak English as well as Polish.** A new `tradaemon.i18n`
  module and two message catalogues in `tradaemon.locales` — plain dicts, no gettext, no
  new dependency. The dashboard picks its language per session (top right, or `?lang=`),
  which matters because one Streamlit process serves several viewers; the engine, the
  webhook and the printed reports read `display_language` from the config instead, since
  they have no viewer to ask. Polish remains the default and the source language.
  `tests/test_i18n.py` fails if the catalogues drift apart, if a key used in the code is
  missing, or if a `{placeholder}` is lost in translation.
- **Alerts are journalled as `msg_key` + `params`, not as a finished sentence.** That is
  what lets the panel render the same outage in either language. The rendered sentence is
  still stored, because the webhook and the log have no viewer to ask — and because every
  line already sitting in a running deployment's `alerts.jsonl` has only that field.
  `humanize.event_line` falls back to it, so months of existing history stay readable
  instead of turning into a column of bare keys.
- **Four things that would have broken quietly, had they simply been translated.**
  Booleans on the settings screen were encoded *as the Polish word* (`raw == "włączony"`),
  so an English label would have turned every save of `rollover` and `trend.enabled` into
  False; the widget now carries real booleans and translates only for display.
  `?layout=telefon` is a URL parameter documented in the README, so the internal codes
  became language-independent while the Polish spellings keep working as aliases. The
  verdict tokens in `models/reports/*.csv` (`KANDYDAT`, `PUŁAPKA`, …) are **data** — every
  saved report holds them and the panel filters on them — so they stay untranslated and
  only their labels move. And the research scripts' Polish column names were renamed to
  English, since nothing reads them back.
- **Fixed along the way: Streamlit's markdown was eating the currency symbol.** A caption
  naming two amounts contains two `$`, which Streamlit reads as LaTeX delimiters — so both
  symbols vanished and the text between them rendered as maths. It had been doing this in
  the Polish panel too. `humanize.md()` escapes them at the three caption sites.
- Documentation is now paired: `README.md` / `README.pl.md`, `howitworks.md` /
  `howitworks.pl.md`, and so on. The README gained a from-scratch setup guide with
  macOS, Linux and Windows instructions, an honest section on
  [what to expect from a bot like this](README.md#what-to-expect-from-a-bot-like-this),
  and a corrected test count — it claimed 74; there are 294. The Synology guide was
  generalised: no home-network addresses, no personal key names, and the war stories
  rewritten in the second person.
- **Corrected: `python -m tradaemon.engine --once` was never a thing.** The README had
  documented that flag as "process one candle and exit" since 0.1.0, but the engine's
  entry point parses no arguments at all — it ignored `--once` silently and ran the 4h
  loop forever. Harmless on a NAS, actively confusing in a from-scratch guide, where a
  newcomer would be told to run a one-shot command that never returns. Both READMEs now
  say what it does. `python -m tradaemon.portfolio` really does take `--once` and
  `--backfill`; only the crypto engine does not.

## 0.1.16 — 2026-08-12

- **A new book, `prog_060`.** 0.1.15 showed that the model's probability carries
  information only at its upper edge, but could not say what to do about it: the tables
  worked in **quantiles within a window** ("the weakest three fifths") while the config
  takes a number. The new table E sweeps **fixed thresholds through a full book
  backtest**, one run per window and threshold — so it also counts what table D could
  not: that a cut signal **frees a slot for the next candidate**.
- **Result: a threshold of 0.58–0.60 beats 0.55 by ~+2.9 pp per window, in 5 windows out
  of 6** — and the same comes out under both slot-allocation rules (`fcfs` +2.80/+2.87 pp,
  `best_first` +3.40/+3.42 pp), so this is a conclusion about the threshold, not about
  allocation. The mechanism shows in the regime breakdown: **the gain comes from losing
  less when the market falls** (−8.3% → −3.5% per window) rather than from winning more
  when it rises (+13.3% → +12.3%). Above 0.62 the upside collapses (+5.3%) — cutting
  stops selecting and starts simply not trading.
- **But this is not a result to reconfigure on; it is a result to put in front of the
  market.** Under `fcfs`, which is what the engine actually does, **t = +1.0** (0.60) and
  **+1.2** (0.58) — because the windows differ from each other far more than the
  thresholds do: at one and the same threshold results run from −15% to +25%. Hence a
  book rather than an edit.
- **0.60, not the 0.58 at the top of the table.** The difference between +2.87 and
  +2.80 pp sits deep inside the noise, so picking the higher one would be fitting the
  sweep. 0.60 is the code default in `config.py`, it sits evenly between the books either
  side of it, and it **holds less**: 55% of candles in the market against 82% at 0.55,
  and 30% fewer trades to pay fees on.
- **`primary_variant` stays on `prog_050` — deliberately, even though the sweep puts it
  last** (−2.58 pp against 0.55, better in only 2 windows of 6). The reason is in the live
  books, and they say **the opposite of the backtest**. Over the same period (24.07–12.08,
  19 days, all at 20% × 3 from the panel):

  | book | threshold | result | trades | win % | avg. exposure | maxDD |
  |---|---|---|---|---|---|---|
  | prog_050 | 0.50 | **+0.16%** | 42 | 54.8 | 36% | −1.90% |
  | prog_065 | 0.65 | −0.91% | 12 | 33.3 | 10% | −1.18% |
  | prog_055 | 0.55 | −1.31% | 30 | 50.0 | 28% | −2.43% |

  The backtest orders them 0.60 ≈ 0.58 > 0.65 > 0.55 > 0.50; the account gives
  0.50 > 0.65 > 0.55. **Both orderings are too weak to reconfigure anything on** — 19 days
  with a ±1.3% spread is noise, and `prog_050`'s edge over `prog_055` (1.5 pp at three
  times the turnover) sits well inside what two weeks produce out of nothing. Pinning
  "your portfolio" to a fresh book would cost all the visible history on the main screen,
  so the pin stays until `prog_060` has gathered a comparable period of its own.
- **The deployed `config.yaml` finally has tests.** No test read `config/config.yaml`
  until now, so a typo only surfaced on the NAS — where a rebuild goes through the
  Container Manager GUI and costs a full deployment cycle. Three invariants: the file
  parses, **variant names are unique** (a duplicate means two books writing into one
  `runtime/<name>/` — one `state.json` overwritten every minute and two strategies in one
  journal, with nothing in the panel to say the comparison is fiction), and
  `primary_variant` names a variant that exists (pointing at nothing does not shout; it
  quietly shows a book on the main screen that nobody chose).

## 0.1.15 — 2026-08-12

- **A trade finally records the probability that opened it.** The model computed `p`, the
  engine compared it against the threshold, wrote it to the log and **threw it away** — it
  was in no trade record, not in the per-pair backtest, not in the book backtest, not in
  the engine's journal. The consequence was that "did high-`p` trades end better?" could
  not be answered from data the project already had. The `prob` column now travels
  everywhere, so in a few months the **live books** will answer it rather than a backtest.
  Positions saved in a pre-0.1.15 `state.json` still load (`entry_prob=None`). Verified
  that this is recording only: 2148 trades across four configurations, **identical to the
  row** before and after.
- Incidentally: `runner.py` was not updating `best_p` on a short signal. That changed
  nothing while nobody read the variable — but the trade record reads it, so **every short
  would have been filed under the long model's probability**. The test shows it: without
  the fix, 325 shorts are recorded at 0.65 instead of 0.85.
- **Measured and unresolved: scaling position size by probability.** A new
  `scripts/research/prob_calibration.py`, 6 windows × 120 days, a model trained separately
  before each window, 1669 trades. Findings:
  - **The calibration curve is not a ramp; it is a threshold.** The three lowest buckets
    (p 0.550–0.591) are indistinguishable from one another and **all below the break-even
    win rate** of 57.1%: 55.4 / 53.6 / 53.9%. The top two (p ≳ 0.58) are the only ones
    that beat it — **60.5% and 63.9%** — and the only ones with a positive net result. The
    control on a model without knowledge gives a flat curve (53.4 / 57.0 / 52.9 / 50.6 /
    56.7), so this is not an artefact of the machinery.
  - **The gain from scaling alone does not clear the gate.** A budget-neutral ramp gives
    +2.6 to +3.5 pp per window, but against the knowledge-free model that is **z = +1.29
    and +1.55** against a bar of 1.65. On top of that the whole thing sits in the rises
    (+6.4 pp) and vanishes in the falls (+0.7 pp).
  - **Cutting beats shrinking.** Throwing away the weakest three fifths of signals gives
    **+3.4 pp per window over cutting the same number of trades at random**, in 5 windows
    of 6 — and it does not pay fees on them either. The control gives noise here (±1 pp,
    3/6). That is leverage on one field in the config (`prob_threshold`), not on a new
    mechanism.
  - A caveat for adopting it: the "0.585" in the table is a quantile **within a window**,
    and the model is retrained before each window, so the scale of `p` drifts. A fixed
    number in `config.yaml` is not the same thing as "cut this window's weakest 60%".
- **Two methodological errors caught on the way, both by the control.** The first version
  accepted a null distribution from shuffling `p` between trades — and that let **a model
  without knowledge through at the 96.5th percentile**. The reason: shuffling by
  individual trade treats eighteen crypto pairs as eighteen independent observations, and
  they move together, so the spread comes out too narrow. The second version compared a
  ramp linear in `p` against a control whose `p` has a completely different distribution
  shape — with `p` squeezed against the threshold the same ramp puts nearly everything on
  a handful of trades, while with a uniform spread it distributes smoothly. After pinning
  the multiplier distribution (`matched_multipliers`) the supposed **z = +3.99 fell to
  +1.55**.
- **`ConstantBundle` stops handing every pair the same fate.** The generator was rebuilt
  from a seed on **every** `predict_proba` call, so the "random" control handed eighteen
  pairs an identical sequence of probabilities. In a per-pair backtest that only narrowed
  the variance; in a book backtest it destroyed the control, because `best_first` had
  nothing to rank. The generator is now built once. This affects the `random` control
  only — `always_long` / `always_short` are unchanged.
- `window_frames` moved from `scripts/research/universe.py` to `research/lab.py`, because
  two scripts use it now. No change in behaviour.

## 0.1.14 — 2026-08-11

- **The panel stopped computing the same thing sixty times.** The event log draws up to
  sixty rows, each with a tooltip showing the price, and `prices=prices_for(sym)` was an
  **argument** to `preview_button` — so it was computed eagerly for every row, even though
  those sixty rows name only **11 distinct pairs**. Measured on live books on the NAS:
  **1267 ms of pandas per refresh**, repeated every 15 s by a `run_every` fragment. Now
  `price_view.tooltips()` builds a tooltip once per instrument and `price_view.memoized()`
  reads its quotes once — **95 ms, 13.4× faster** (on the NAS, an estimated ~3.5 s →
  ~0.26 s).
- **`summary()` stopped parsing the whole history to read three numbers off the tail.**
  `pct_change` was calling `pd.to_datetime` on ~12,000 rows from Parquet, and doing it
  twice (once per 24h / 7d horizon). The column is now parsed once, on a tail of 200
  candles — 33 days at 4h and 200 days on daily quotes, so a 7-day horizon fits
  comfortably in both modules. The slice limits *how far back it looks*, not the answer: a
  test compares the result against the same question asked of the full frame.
- This is the presentation layer only — **no change to the bot's logic, its decisions or
  its books**. The tooltips are identical to the character; verified by comparing 60 rows
  before and after.
- The same pattern fixed in the portfolio module (`portfolio_view.py`), where it was
  milder (15 log rows instead of 60).
- **The panel refreshes every 60 s instead of every 15 s** — on both layouts, not just on
  a phone. This is not a compromise but a ceiling: decisions land on closed 4h candles, and
  between them the only writer of `equity`/`last_close` is the engine's ticker loop,
  running at `TICKER_SECONDS = 60`. Refreshing at 15 s redrew the same numbers three times
  out of four. Together with the fixes above, the panel uses **about 54× less CPU time** on
  the NAS (~3.5 s every 15 s, i.e. 23% of a core continuously → ~0.26 s every 60 s, i.e.
  0.4%).

## 0.1.13 — 2026-08-10

- **Raising the exposure ceiling asks before it takes effect.** The confirmation dialog
  catches every increase in the product `position_pct × max_open_positions` — 5 × 10% →
  10 × 10% just as much as 5 × 10% → 5 × 20% — and says what the screen did not say
  before: that the effect arrives one candle later, and that **going back to a lower value
  closes nothing**. Lowering the limit saves without a question.
- **The "Risk" section shows the queue for a freed slot**: how many pairs cleared the
  threshold and were turned away by the ceiling alone, with the highest probability among
  them, per book. The kill-switch is deliberately not counted — raising the limit will not
  unblock its refusals. This number only became meaningful in 0.1.12, when the engine
  started asking the model **before** checking the limit.
- The reason this exists is described in `howitworks.md` §4.8: on 9 Aug at 17:51 UTC the
  limit went from 5 to 10 and came back at 22:43, but the 20:00 candle had already opened
  four positions and pushed `prog_050` from 50% to 90% of the account. They stayed after
  the setting was reverted, three stopped out, and they **cost 7.07 USDT — 51% of the whole
  drawdown**; the market over that time gave −1.60%, and the fair bar at that exposure was
  −1.04% against the book's −1.30%. The control: `prog_065` and `ryzyko_100` took no
  positions at all in that window and fell −0.90% / −1.34% — that much was the market.
- `journals.book_states` reads the `state.json` of every crypto book; the settings screen
  needs live state and cannot import `app.py` (it is `app` that imports `config_view`).
- Corrected a stale table in §4.7: the three threshold books have a ceiling of 5 × 10%
  today, not 3 × 10%.

## 0.1.12 — 2026-08-10

- **The dark line on "How it went" now follows the bot's exposure candle by candle**
  (`matched_exposure_curve`) instead of scaling the whole basket by one average over the
  window. The old version diverged exactly when risk settings changed on the fly: a book
  that ran at 30% for three weeks and then at 90% got a benchmark for ~40% — wrong for
  both halves. Worse, that average depended on the selected range, so **switching 7 days /
  30 days changed not only the period but the measure itself** (31% vs 39% exposure), and
  the "the bot beats it / does not" verdict could flip because of it. Now the shape of the
  line over any stretch is the same whichever window it is drawn in, and raising the risk
  shows in the benchmark immediately.
- Exposure enters the formula **lagged by one bar**: the engine journals `cash` at candle
  close, so the value at index `t` already knows how `t` went — without the shift the
  benchmark would be trading on the very move it is measured against.
- **The caption under the chart shows both exposure numbers** — the window's average and
  the current state. The header reads the instantaneous `(equity-cash)/equity` from
  `state.json` while the chart used the book's average, and after a settings change those
  two numbers diverged with no word of explanation (90% in the header, 31% under the
  chart).
- `buy_hold_curve` loses its `exposure` parameter — the light line was always the default
  call, and the dark one now has a function of its own.

## 0.1.11 — 2026-08-10

- **The board grows from 10 to 18 USDT pairs** (adding DOT, TRX, ATOM, BCH, XLM, UNI, ETC,
  NEAR) and `max_open_positions` goes from 3 to **5**. The reason was visible in the
  books: `prog_050`, with its cap raised to 10 from the panel, was holding **9 of 10
  pairs** with 99 USDT of free cash — the board was exhausted.
- **The most important measured result is about the cap, not the board.** Widening pays
  **only under a tight cap**: +0.78 pp per window at a cap of 3, −0.31 pp at 5, and
  **−2.32 pp at 10**. The cap itself is the strongest effect measured anywhere in this
  project: on eighteen pairs, a cap of 3 beats a cap of 10 by **+4.49 pp per window, in 8
  windows of 10, t = +2.73** (under `best_first`, t = +3.50) — the only result here that
  clears the usual significance bar. The mechanism: a wide board is a pool **to choose
  from**, not a list to fill; at ten slots the book takes everything that signals (2609
  trades instead of 1713 at the same 80% exposure), so the extra pairs add nothing but
  turnover and fees. Adopted: 18 pairs + a cap of 5 — widening is neutral at five, but five
  beats ten on both boards, and three would keep half as much capital at work.
- **A new whole-book backtest (`backtest/book.py`) and the `scripts/book_backtest.py`
  script.** `runner.py` gives every pair its own wallet and unlimited slots, so counted
  that way adding pairs raises the average by definition — it appends another account, not
  a competitor. `book.py` counts one wallet, one cap and the same `RiskManager` the engine
  uses, and returns a number `runner.py` cannot produce: how many signals the book threw
  away for lack of a free slot. `maker` mode raises rather than guessing, because the
  engine has no answer for whether an unfilled limit order holds a slot. The promotion gate
  in `refresh.py` was left untouched — it measures a different question.
- **Measured and rejected: giving the slot to the strongest signal.** A new
  `scripts/research/universe.py` — the model retrained before each window, separately for
  each board, because widening the board also widens the training set and that is part of
  the change rather than a confounder to zero out. Ranking by probability gives **−0.6 to
  +0.7 pp**, five of six comparisons at zero or negative — it does not pay even where the
  cap turns away 3000 candidates. The simplest explanation is that the model's probability
  is too weakly informative to sort by. Not adopted.
- **A research script must not quietly compare a thing with itself.** The first version of
  `universe.py` took its narrow arm from `config.exchange.symbols` — so the moment its own
  conclusion reached the config, "base" and "wide" became the same eighteen pairs and the
  script printed a tidy table of four rows identical to the last decimal. Both boards are
  now pinned in code (`--base` / `--add`), and identical arms end in an error rather than a
  report.
- **`risk_blocked` stops lying and starts carrying a number.** `_maybe_enter` asks the
  model **before** checking the cap. Under the old order a blocked pair had no probability
  computed yet, so the panel showed "held back by the risk limit" next to an empty
  `p(long)` column — which could equally mean a rejected 0.92 opportunity or a 0.31
  non-event; and pairs far below the threshold, which would not have entered anyway, landed
  under the same reason. Now `risk_blocked` is always a genuinely rejected opportunity,
  with its probability and side beside it. No trade changes — `can_open` still gates every
  entry, just one call later.
- The panel's event log shows 60 entries instead of 30: a book with five slots can close
  five positions and open five more on one candle, so thirty rows was three candles — half
  a day.
- Fixed along the way: `book.py` stamped an entry with the **signal's** candle rather than
  the **fill's** (an entry happens at the next bar's open, as in `runner.py`), so the trade
  journal backdated every entry by one candle and positions looked like they overlapped
  despite the cap being respected.

## 0.1.10 — 2026-08-09

- **Events carry the candle's close time, not its open.** `bar["timestamp"]` from ccxt is
  the *open* time, and a candle only reaches the engine once it has closed — so every log
  entry, every trade and every point on the equity curve was set back by a whole timeframe.
  At 4h it looked as though the bot had stopped doing anything four hours ago: trades from
  a candle that closed at 22:00 sat under 18:00. The fix is one line in `Book.on_candle`,
  but everything passes through it — the log, `trades.jsonl`, `equity.jsonl`, a position's
  `deadline`, `updated_at` in `state.json` and the day boundary for the kill-switch.
  `last_candle_ts` stays the open time, because `bot_status` and `live_drift` add the
  timeframe themselves; two conventions in adjacent lines are now described in a comment.
  A one-off cost: at the seam between old and new records the equity history jumps by 4h,
  and positions opened before the deployment may expire one candle early.
- **The chart shows recent entries.** Trade markers were clipped to the right-hand edge of
  the quotes, and the quotes are fetched by `refresher` once a week — so everything the bot
  had done since the last download vanished from the chart. Clipping is now only on the
  left (the selected range). The price line itself no longer ends last week either:
  `crypto_prices` extends the stored candles with the closes the engine journals alongside
  equity anyway.
- A settings-change entry gets a ⚙️ icon in the log rather than a bare dot, and the event
  list shows 30 rows instead of 15 — with ten pairs and ten positions, one candle can write
  a dozen or more rows.

## 0.1.9 — 2026-08-08

- `strategy.timeout_rollover` is now `strategy.rollover` and has an explicit cost test: it
  extends when the exit price's advantage over the re-entry price does not cover two fees.
  At a timeout both prices are the same candle's close, so the condition always holds —
  behaviour unchanged. A stop-loss never extends: that would be abandoning a risk limit,
  not saving money.
- **The finding that makes this change smaller than it was meant to be.** Extending
  rollover to take-profit exits looked spectacular in the backtest: the average result went
  +146.6% → **+182.8%** over 5.5 years and ten pairs, every pair in the black. That is not
  an edge, it is looking into the future. A TP is detected from the candle's high — a touch
  **inside** the candle, filled at the barrier price, i.e. a trade that happened before the
  candle closed. Declining it after seeing where the candle closed uses information from
  the future. The honest version, limited to timeouts, gives +146.56% → +146.67% and 18
  USDT less in fees — three hundred times smaller, and that is exactly how much of it was
  real.
- A genuine problem remains, to be settled separately: the engine wakes only at a candle's
  close, and yet it settles a TP at the barrier price. That optimistic assumption underlies
  every measurement in this project's history so far.

## 0.1.8 — 2026-08-08

- **The price chart shows the position the bot is holding right now** — as a green circle
  at the place and time of entry, alongside the triangles of completed trades. Previously
  the markers came only from `trades.jsonl`, to which the engine appends a row only when a
  position **closes**, so the chart told the opposite story to the card above it: LINK
  (bought and never sold) had no markers at all, while LTC and ADA had a red exit as their
  last marker — from the very candle on which the bot immediately re-entered.

## 0.1.7 — 2026-08-08

- **A settings change in the panel really reaches the engine.** Restoring a default
  deletes `config.overrides.yaml` (there is nothing left to override), and the sensor
  looked only at that file's modification time: its disappearance gave "0", i.e. never
  "newer". So the bot traded on the previous parameters for the rest of the container's
  life while the panel already showed the new ones — in practice "maximum open positions"
  went back to 3 while the bot kept opening 5, i.e. 50% exposure rather than 30%. The
  engine now compares the **contents** of `config.yaml` and the overrides, so it sees every
  change: a deleted file, two writes in the same second, an older version being uploaded —
  and also a hand edit to `config.yaml` itself, which it previously could not accept.
- A failed configuration read is no longer remembered as done. The engine ticked the file
  off *before* trying to load it, so one unlucky read froze a book on the old settings
  until a restart.
- **The panel confirms a save.** The "Saved…" message was lost in the page reload right
  after the click, so saving a change looked identical to clicking into the void. It now
  survives the reload the same way the restart confirmation does.
- **You can see what the engine is really trading on.** `state.json` records the parameter
  values the book is currently enforcing, and the settings screen warns when the engine has
  diverged from the disk. The warning waits for the candle at which the change should have
  taken effect and compares each book against its own variant — so it neither cries wolf
  right after a save nor mistakes `ryzyko_100` for a fault.

## 0.1.6 — 2026-08-08

- The event log **closes its own alarms**. When the bot regains connectivity it appends
  "✅ the exchange connection is back" — including when a previous container opened the
  alarm, because the engine checks at startup whether an unclosed outage is hanging in the
  journal. Before, you had to wait for some unrelated event (on 4h candles, potentially
  hours) to stop seeing "no connection" at the top.
- An open alarm and its all-clear differ by icon (📡 versus ✅), so it is visible while
  scrolling, without reading the text.

## 0.1.5 — 2026-08-07

- Under the bot status, the panel shows **live contact with the exchange** ("exchange
  contact: just now" / "no contact for 47 min"). Computed from `updated_at`, which the
  ticker refreshes every 60 s and only after a successful request — so it reacts in minutes
  rather than hours like the candle clock.
- This closes the gap from 0.1.3: the "no connection to the exchange" alert was written by
  the same process that saw the fault, so after a container restart the all-clear was never
  created and the journal held an alarm that was true about the past and misleading about
  the present. A heartbeat cannot go stale that way.

## 0.1.4 — 2026-08-07

- Reverted the forced public DNS resolvers in `docker-compose.yml`. The theory behind them
  (that DSM leaves a loopback address in `/etc/resolv.conf`) turned out, measured on the
  NAS, to be untrue: the router is there, and it answers 20/20 queries in 5 ms — faster
  than any public resolver. Pinning `1.1.1.1` pushed every query out through NAT and broke
  name resolution intermittently. Docker's default behaviour is both the shorter and the
  more reliable path here.
- The deployment guide now says to **measure the host's resolver first** and configure
  anything only afterwards.

## 0.1.3 — 2026-08-07

- The engine no longer dies on a momentary network outage at startup. Fetching the first
  candles is retried (5 s, then progressively less often, at most every 5 min) instead of
  killing the process — on the NAS that ended in 826 restarts in five hours, because
  `restart: unless-stopped` brought the container straight back into the same DNS error. A
  dropped and recovered connection reaches the event log (📡).
- An interrupted start no longer wipes book state. `restore()` also restores the last
  prices and the last candle's time, and state is saved only once the engine has really
  got going. Previously it overwrote a good `state.json` with an empty one — and that is
  why the chart lost both grey buy-and-hold lines, leaving a flat tail on the bot's line.
- The bot status no longer shows red for the first hours after a restart: loading candle
  history counts as reading the market.
- The panel does not draw a "live" point without prices the benchmark has nothing to
  compute from — all three lines end at the same place.
- `docker-compose.yml` sets the containers' DNS resolvers. There had been a recipe for
  this in the guide, but the override file lived only on the NAS, outside the repo — and
  simply disappeared.

## 0.1.2 — 2026-08-07

- The event log no longer takes the panel down on an alert with no instrument (a
  configuration change, for instance). Log rows now come back without the fields they
  never had — previously pandas manufactured them as NaN, and NaN passed `if sym:`.

## 0.1.1 — 2026-08-07

- The panel shows the version number under the title, on every module.
- The version is kept in one place (`src/tradaemon/__init__.py`); `pyproject.toml` reads it
  when building the package.

## 0.1.0

- First version: the crypto scalper engine, the portfolio manager, the research scripts
  and the panel.
