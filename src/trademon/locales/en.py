"""English message catalogue — a translation of `pl.py`, which is the source language.

When you add a key, add it to both files: `tests/test_i18n.py` fails otherwise, and it
also checks that the `{placeholders}` match, so a sentence cannot lose its numbers in
translation.

Sections follow the modules the strings appear in.
"""

from __future__ import annotations

MESSAGES: dict[str, str] = {

    # ---------- formatting ----------
    # English puts the sign in front of the amount; Polish puts it after.
    "fmt.decimal_separator": ".",
    "fmt.money": "${amount}",

    # ---------- humanize: why the bot did or did not trade ----------
    "reason.in_position": "holding a position",
    "reason.warmup": "warming up (gathering data)",
    "reason.risk_blocked": "sees an opportunity, but the risk limit says no",
    "reason.features_nan": "waiting for complete data",
    "reason.no_atr": "waiting for complete data",
    "reason.below_threshold": "does not see a good enough opportunity",
    "reason.enter_long": "opening a position (betting on a rise)",
    "reason.enter_short": "opening a position (betting on a fall)",

    # ---------- humanize: how a position closed ----------
    "exit.tp": "at a profit (target reached)",
    "exit.sl": "at a loss (stop-loss)",
    "exit.timeout": "after running out of time",

    # ---------- humanize: glossary tooltips ----------
    "glossary.sharpe": "Return relative to how much it swings. Higher = better. Above 1 "
                       "is good; below 0 means you lost ground for the risk taken.",
    "glossary.max_drawdown": "The largest fall from a peak to a trough. -20% means that "
                             "at the worst moment the portfolio was a fifth below its "
                             "high.",
    "glossary.profit_factor": "How much was earned for every $1 lost. Above 1 = more "
                              "profit than loss.",
    "glossary.win_rate": "The share of trades that ended in the black.",
    "glossary.buy_hold": "You buy once and do nothing. It is the bar to clear: the bot "
                         "is only worth running if it beats simply holding.",
    "glossary.rebalance": "Restoring the basket's planned proportions (say, back to "
                          "50/30/20) once prices have pulled them apart.",
    "glossary.drift": "How far the basket's proportions have wandered from the plan, in "
                      "percentage points.",
    "glossary.cagr": "Compound annual growth rate — the percent per year this would "
                     "average out to.",
    "glossary.volatility": "How hard the value jumps up and down. Lower = calmer.",
    "glossary.kill_switch": "A safety catch: after too large a loss in one day, the bot "
                            "stops opening new positions.",
    "glossary.money_at_work": "How much of the account is actually in the market. The "
                              "rest waits in cash doing nothing — neither earning nor "
                              "losing.",
    "glossary.return_total": "The result measured against all the money, including what "
                             "sat idle. That is why it looks milder than the bot's idea "
                             "deserves.",
    "glossary.time_in_market": "How often the bot had a position open at all. A low "
                               "number means it spent most of the time just waiting.",
    "glossary.return_at_work": "The same result, but measured only against the money "
                               "that was actually playing. A fairer verdict on the idea "
                               "itself: had the bot played the whole account, it would "
                               "have come out roughly here. An approximation, not an "
                               "oracle — and when the bot was in the market very rarely "
                               "we show “—”, because scaling that sliver up "
                               "to a whole account is guesswork.",
    "glossary.bh_fair": "Someone who put exactly as much money into the market as the "
                        "bot did, and then simply waited. That is the fair bar — "
                        "comparing against someone who went all in praises the bot "
                        "merely for being absent during the falls.",

    # ---------- humanize: cards ----------
    "card.position.long": "Bought {asset} for {amount}",
    "card.position.short": "Betting {amount} on {asset} falling",
    "card.position.now": "now {pnl} ({pct}%)",
    "card.holding.weight": "{weight}% of the portfolio (target {target}%)",

    # ---------- humanize: event timeline ----------
    "event.trade_closed": "{symbol} closed {how}",
    "event.generic": "event",

    # ---------- humanize: status lines ----------
    "status.bot.no_read": "the bot has not read the market yet",
    "status.bot.unknown_time": "time of the last reading is unknown",
    "status.bot.running": "running — last candle closed {when}, next one around {next}",
    "status.bot.stale": "may not be responding — last candle closed {when}",
    "status.conn.none": "no contact with the exchange",
    "status.conn.unknown_time": "time of last exchange contact is unknown",
    "status.conn.ok": "exchange contact: {ago}",
    "status.conn.stale": "no contact with the exchange for {ago} — waiting and retrying",
    "ago.just_now": "just now",
    "ago.minutes": "{minutes} min ago",
    "ago.hours": "{hours} h {minutes} min ago",
    # ---------- module names, shared by the router and the settings screen ----------
    "module.label": "Module",
    "module.crypto": "Crypto scalper",
    "module.portfolio": "Portfolio manager",
    "module.research": "Research",
    "module.settings": "Settings",

    # ---------- settings: sections ----------
    "cfg.section.strategy": "Strategy",
    "cfg.section.risk": "Risk",
    "cfg.section.costs": "Costs",
    "cfg.section.market": "Market and capital",
    "cfg.section.training": "Training",
    "cfg.section.portfolio": "Portfolio",
    "cfg.section.changed": "{title} ({n} changed)",

    # ---------- settings: fields ----------
    "cfg.field.strategy.prob_threshold.label": "Model confidence threshold",
    "cfg.field.strategy.prob_threshold.help": "The lowest probability at which the bot opens "
        "a position. Lower = more trades and more fees.",
    "cfg.field.strategy.tp_atr_mult.label": "Take-profit (× ATR)",
    "cfg.field.strategy.tp_atr_mult.help": "How far from the entry price the profit target "
        "sits, measured in units of volatility (ATR).",
    "cfg.field.strategy.sl_atr_mult.label": "Stop-loss (× ATR)",
    "cfg.field.strategy.sl_atr_mult.help": "How far away the safety catch sits. Less = cuts "
        "losses sooner, but also throws you out of good positions more often.",
    "cfg.field.strategy.horizon_bars.label": "Maximum holding time (candles)",
    "cfg.field.strategy.horizon_bars.help": "After this many candles the position closes "
        "whatever the result.",
    "cfg.field.strategy.rollover.label": "Extend at the deadline",
    "cfg.field.strategy.rollover.help": "When the maximum holding time runs out and the model "
        "still signals above the threshold, the bot extends the position (new brackets and "
        "deadline) instead of closing it and immediately reopening it for double the fee.",
    "cfg.field.strategy.atr_period.label": "ATR period",
    "cfg.field.strategy.atr_period.help": "How many candles back volatility is measured over.",
    "cfg.field.strategy.direction.label": "Direction",
    "cfg.field.strategy.direction.help": "long = bets on a rise only (what a spot account can "
        "do). long_short = bets on falls too; real shorts need a futures account.",
    "cfg.field.strategy.warmup_bars.label": "Warm-up (candles)",
    "cfg.field.strategy.warmup_bars.help": "How much history the bot must gather before it can "
        "compute features. Changing it needs a restart, because it sets the candle buffer size.",
    "cfg.field.risk.position_pct.label": "Position size (share of capital)",
    "cfg.field.risk.position_pct.help": "How much of the account goes into one position. "
        "0.10 = 10%.",
    "cfg.field.risk.max_open_positions.label": "Maximum open positions",
    "cfg.field.risk.max_open_positions.help": "Together with the setting above, this sets the "
        "maximum exposure. Crypto pairs are heavily correlated, so open positions usually "
        "behave alike. Note that this change is asymmetric — raising it takes effect on the "
        "very next candle, lowering it only once the surplus positions close on their own.",
    "cfg.field.risk.daily_loss_limit_pct.label": "Daily loss limit",
    "cfg.field.risk.daily_loss_limit_pct.help": "A safety catch: after too large a loss in one "
        "day, the bot stops opening new positions.",
    "cfg.field.risk.drawdown_alert_pct.label": "Drawdown alert threshold",
    "cfg.field.risk.drawdown_alert_pct.help": "How far below the equity peak the panel should "
        "start warning.",
    "cfg.field.costs.taker_fee.label": "Taker fee",
    "cfg.field.costs.taker_fee.help": "The fee on market orders. Binance spot defaults to "
        "0.001 = 0.1%.",
    "cfg.field.costs.maker_fee.label": "Maker fee",
    "cfg.field.costs.maker_fee.help": "The fee on limit orders resting in the book.",
    "cfg.field.costs.slippage_bps.label": "Slippage (basis points)",
    "cfg.field.costs.slippage_bps.help": "The adverse deviation in execution price we assume. "
        "2 bps = 0.02%.",
    "cfg.field.exchange.timeframe.label": "Candle interval",
    "cfg.field.exchange.timeframe.help": "How often the bot makes a decision. Changing it needs "
        "a restart and invalidates a model trained on a different interval.",
    "cfg.field.exchange.symbols.label": "Pairs",
    "cfg.field.exchange.symbols.help": "A comma-separated list of pairs. The cost model is "
        "honest for highly liquid pairs; thinner ones will trade worse than the backtest "
        "suggests.",
    "cfg.field.paper.initial_capital.label": "Starting capital (paper)",
    "cfg.field.paper.initial_capital.help": "Applies to new books. Existing books keep their "
        "state in state.json and will not change balance because of this edit.",
    "cfg.field.primary_variant.label": "Book on the main screen",
    "cfg.field.primary_variant.help": "Which A/B variant the panel calls “your portfolio”.",
    "cfg.field.model.train_window_days.label": "Training window (days)",
    "cfg.field.model.train_window_days.help": "How much history goes into training. It also "
        "sets the weekly download window, so a small value quietly caps how much data is ever "
        "collected.",
    "cfg.field.model.validation_days.label": "Validation window (days)",
    "cfg.field.model.validation_days.help": "How many days at the end of each fold are used to "
        "score it.",
    "cfg.field.model.n_folds.label": "Number of folds",
    "cfg.field.model.n_folds.help": "How many walk-forward validation steps to run.",
    "cfg.field.initial_capital.label": "Starting capital",
    "cfg.field.initial_capital.help": "Applies to a new portfolio book.",
    "cfg.field.rebalance.cadence_days.label": "Rebalance every (days)",
    "cfg.field.rebalance.cadence_days.help": "The least frequent rhythm allowed for restoring "
        "the proportions.",
    "cfg.field.rebalance.drift_threshold_pct.label": "Drift threshold (pct. points)",
    "cfg.field.rebalance.drift_threshold_pct.help": "How far the basket's proportions have "
        "wandered from the plan, in percentage points.",
    "cfg.field.trend.enabled.label": "Trend filter",
    "cfg.field.trend.enabled.help": "When on, an asset below its own moving average is moved "
        "into the safe asset. That is a risk premium, not a free lunch.",
    "cfg.field.trend.ma_days.label": "Moving average for the trend filter (days)",
    "cfg.field.trend.ma_days.help": "Classically 200 sessions.",

    # ---------- settings: on/off, buttons, messages ----------
    "cfg.bool.on": "on",
    "cfg.bool.off": "off",
    "cfg.save": "Save",
    "cfg.cancel": "Cancel",
    "cfg.reset_section": "Restore defaults in “{title}”",
    "cfg.nothing_changed": "Nothing changed.",
    "cfg.saved": "Saved:\n{changes}",
    "cfg.saved.hot": "⚡ Takes effect on the next candle — no restart needed.",
    "cfg.error.bad_value": "I do not understand the value in “{field}”.",
    "cfg.error.no_permission": "Not allowed to change settings.",
    "cfg.intro": "Changes go to `config.overrides.yaml`. The `config.yaml` file is left "
        "untouched as a documented baseline — “restore defaults” simply removes the override.",
    "cfg.markers": "{hot} — takes effect on the next candle · {restart} — needs an engine "
        "restart",
    "cfg.portfolio.daily_loop": "The portfolio loop runs daily, so every change takes effect on "
        "the next run anyway — there is no hot-reload here.",

    # ---------- settings: slots ----------
    "cfg.slots.head": "**{book}** · {taken} of {cap} slots taken",
    "cfg.slots.top_p": " (best {p})",
    "cfg.slots.queued": "{head}, queued with a signal: **{queued}**{top}. Each extra slot is "
        "one more position on the next candle, at {pct} of the account.",
    "cfg.slots.free": "{head} — nobody is queued, so raising the limit would change nothing "
        "today.",
    "cfg.slots.full": "{head} — the book is full, but no pair is above the threshold.",
    "cfg.slots.as_of": "The numbers are from each book's last candle.",

    # ---------- settings: engine drift ----------
    "cfg.drift.stuck": "The engine is trading on different settings from the ones this screen "
        "shows — and the candle at which it should have adopted them has already passed.",
    "cfg.drift.row": "- **{book}** · `{field}`: the engine has **{live}**, on disk {disk}",
    "cfg.drift.restart_fixes": "Restarting the engine will certainly square this up — it comes "
        "back with whatever is in the file.",
    "cfg.drift.pending": "⚡ The engine will adopt the new settings on the next candle. Until "
        "then it trades on the previous ones.",

    # ---------- settings: raising the exposure ceiling ----------
    "cfg.ceiling.title": "You are raising the exposure ceiling",
    "cfg.ceiling.from_to": "From **{before} of the account** to **{after} of the account** in "
        "the market at once.",
    "cfg.ceiling.warning": "Going back to a lower value **closes nothing** — positions opened "
        "under the higher limit live on until their target, their stop or their deadline. On "
        "9 Aug a limit raised for five hours managed to open four positions; they cost 7 USDT "
        "long after it had gone back to where it was.",
    "cfg.ceiling.save_anyway": "Save anyway",

    # ---------- settings: restart handshake ----------
    "cfg.restart.title": "Restart the engine?",
    "cfg.restart.startup_only": "The engine reads these settings only at startup:",
    "cfg.restart.explain": "The engine will save every book's state and exit cleanly. The "
        "container comes back up on its own (`restart: unless-stopped`), and open positions and "
        "cash return from `state.json`. Outside Docker you have to start it yourself.",
    "cfg.restart.do": "Restart",
    "cfg.restart.later": "Later",
    "cfg.restart.needed": "You saved settings that the engine reads only at startup.",
    "cfg.restart.button": "🔄 Restart the engine",
    "cfg.restart.sent": "Restart requested. The engine will go down within ~10 seconds and come "
        "back with the new settings.",

    # ---------- settings: change history ----------
    "cfg.history.title": "Change history",
    "cfg.history.empty": "Nothing has been changed yet — the bot is running on the values in "
        "config.yaml.",
    "cfg.history.marked_on_chart": "These moments are also marked with a dashed line on the "
        "equity chart, so you can see from when the result reflects different settings.",
    "cfg.history.col.time": "time",
    "cfg.history.col.field": "field",
    "cfg.history.col.old": "was",
    "cfg.history.col.new": "is",
    "cfg.history.col.actor": "who",

    # ---------- settings: A/B variants ----------
    "cfg.variants.title": "A/B variants",
    "cfg.variants.help": "Each row is a separate book trading the same candles. An empty cell = "
        "the value from the section above. Changing the list needs a restart.",
    "cfg.variants.save": "Save variants",
    "cfg.variants.reset": "Restore default variants",
    # ---------- layout switch ----------
    "layout.title": "Layout",
    "layout.auto": "auto",
    "layout.mobile": "phone",
    "layout.desktop": "desktop",
    "layout.help": "“auto” works the device out from the browser. Change it if it guessed "
        "wrong, or if you want to see the other layout. You can also add `?layout=mobile` to "
        "the address to keep the choice in a bookmark.",
    "layout.forced_by_url": "The layout is forced by the `?layout` parameter in the address — "
        "the switch above is inactive right now.",
    "layout.show_rest": "Show the rest ({n})",
    # ---------- app shell ----------
    "lang.pl": "PL",
    "lang.en": "EN",
    "app.version": "version",
    "app.educational": "educational project · paper trading · not investment advice",
    "panel.analytics": "Analytics",
    "panel.model": "Model",
    "panel.variants": "Variants",
    "panel.experiments": "Experiments",
    "panel.health": "Health",

    # ---------- charts ----------
    "chart.series.bot": "Your portfolio",
    "chart.series.bh_all": "All in the market",
    "chart.series.bh_fair": "Matched to the bot",
    "chart.value": "Value ($)",
    "chart.time": "Time",
    "chart.series": "Series",
    "chart.settings_change": "Settings change",
    "chart.fields": "Fields",

    # ---------- beginner screen ----------
    "home.you_have": "What you have (virtual $)",
    "home.since_start": "{change}% since the start",
    "home.split": "💵 free: {free} · 📈 in play: {invested} (**{pct}% of the money**)  ·  "
        "**paper** mode (practice, not real money)",
    "home.bot_status": "Bot status",
    "home.kill_switch_on": "🛑 The daily safety catch is on — the bot is not opening new "
        "positions right now.",
    "home.how_it_went": "How it went",
    "home.range": "Range",
    "home.range.7d": "7 days",
    "home.range.30d": "30 days",
    "home.range.all": "All",
    "home.benchmark_explainer": "Both grey lines are the same market, bought and held. The "
        "**light** one puts all the money into it — the bot beats that easily during falls, "
        "but not because it is clever: because it was not there. The **dark** one puts in "
        "exactly as much as the bot had in the market at each moment, and that is the fair "
        "comparison. Over this period the bot held an average of **{avg}% of the money** in "
        "the market (now: **{now}%**) — the less it holds, the closer the dark line sits to "
        "plain cash and the further from the light one.",
    "home.not_enough_data": "Not enough data for a chart — the bot is only starting to gather "
        "history.",
    "home.holdings": "What the bot is holding",
    "home.holdings.empty": "Nothing — the bot is waiting for an opportunity. 🕊️",
    "home.holdings.click": "Click an instrument to see its price.",
    "home.events": "Event log",
    "home.events.click": "Click an event to see the price at that moment.",
    "home.events.empty": "Nothing has happened yet.",

    # ---------- metric labels ----------
    "metric.return_total": "Return on all the money",
    "metric.return_at_work": "Return on money at work",
    "metric.sharpe": "Sharpe",
    "metric.max_drawdown": "Max drawdown",
    "metric.profit_factor": "Profit factor",
    "metric.win_rate": "Win rate",
    "metric.money_at_work": "Money at work",
    "metric.time_in_market": "Time in the market",
    "metric.kill_switch": "Kill-switch",
    "metric.drawdown": "Drawdown",

    # ---------- table columns ----------
    "col.symbol": "Pair",
    "col.trades": "Trades",
    "col.win_rate": "Win rate",
    "col.net_pnl": "Net result",
    "col.fees": "Fees",
    "col.threshold": "Threshold",
    "col.decision": "Decision",
    "col.variant": "Variant",
    "col.equity": "Equity",
    "col.max_dd_pct": "Max DD %",
    "col.at_work_pct": "At work %",
    "col.return_on_risked_pct": "Return on that %",
    "col.win_rate_pct": "Win rate %",

    # ---------- analytics tab ----------
    "analytics.no_trades": "No trades yet.",
    "analytics.per_pair": "Result per pair",
    "analytics.pnl_distribution": "Distribution of trade results",
    "analytics.pnl_axis": "PnL (USDT)",
    "analytics.count": "Count",
    "analytics.exit_reasons": "Exit reasons",

    # ---------- model tab ----------
    "model.why": "Why the bot is (not) trading",
    "model.why.help": "The model's probability and the decision for each pair's last candle. "
        "It enters when the probability is ≥ the threshold.",
    "model.no_signals": "No signals — the engine has not computed probabilities yet (until the "
        "warm-up window is over).",

    # ---------- variants tab ----------
    "variants.title": "Live comparison of variants",
    "variants.none": "No A/B variants. Add a `variants:` section to config.yaml to have "
        "several configurations trade the same data in parallel.",
    "variants.equity_axis": "Equity (USDT)",

    # ---------- experiments tab ----------
    "experiments.title": "Experiment log",
    "experiments.help": "Every backtest/sweep recorded once — so the same thing is not "
        "computed over and over.",
    "experiments.empty": "Empty. Run `python scripts/backtest.py` to add an entry.",

    # ---------- health tab ----------
    "health.title": "System health",
    "health.variant": "Variant: {name}",
    "health.ok": "OK",
    "health.attention": "ATTENTION",
    "health.active": "ACTIVE",
    "health.inactive": "inactive",
    "health.last_state": "Last state",
    "health.stale_pairs": "[{name}] stale data for: {pairs} (the engine may not be processing "
        "candles)",
    "health.refresher": "Refresher: {status} @ {when} — {detail}",
    "health.recent_alerts": "Recent alerts",
    "health.no_alerts": "No alerts.",

    # ---------- crypto module shell ----------
    "crypto.no_data": "No data — start the engine: `python -m trademon.engine`",
    "crypto.your_book": "Your portfolio: **{book}** (the other variants are under Details)",
    "crypto.details": "🔬 Details for the curious",
    "crypto.book_picker": "Book (variant)",
    # ---------- portfolio module ----------
    "portfolio.series.bh": "Buy and hold",
    "portfolio.range.1y": "1 year",
    "portfolio.range.5y": "5 years",
    "portfolio.range.all": "All",
    "portfolio.status.no_data": "no data — the bot has not started yet",
    "portfolio.status.running": "running — data from {when}",
    "portfolio.split": "💵 cash: {cash} · 📊 in play: {invested} (**{pct}% of the money**)  ·  "
        "**paper** mode (practice)",
    "portfolio.chart_explainer": "Blue above grey = rebalancing helps versus simply holding "
        "the basket. Here the comparison is fair by construction: both lines have all their "
        "money in the market.",
    "portfolio.not_enough_data": "Not enough data for a chart — the bot is only starting out.",
    "portfolio.no_allocation_yet": "Nothing yet — the bot is waiting for its first allocation.",
    "portfolio.weight_vs_target": "Weight now vs target",
    "portfolio.pct_of_portfolio": "% of the portfolio",
    "portfolio.now": "now",
    "portfolio.target": "target",
    "portfolio.worst_drift": "Largest deviation from the plan (drift): {drift} pct. points "
        "(rebalance at ≥ {threshold} points or every {days} days).",
    "portfolio.rebalance_history": "Rebalancing history",
    "portfolio.fees_total": "Fees in total: {fees}  ·  trades: {trades}",
    "portfolio.data_status": "Data status",
    "portfolio.no_config": "No `config/portfolio.yaml` — the portfolio module is not "
        "configured.",
    "portfolio.no_data": "No portfolio data — start the engine: `python -m trademon.portfolio`",
    "portfolio.basket": "Basket: **{basket}** · rebalance every {days} days or at drift ≥ "
        "{threshold} points · trend filter: {trend}",
    "panel.allocation": "Allocation",
    "panel.rebalances": "Rebalances",

    # ---------- price preview ----------
    "price.no_quotes": "No stored quotes for this instrument.",
    "price.no_quotes_for_chart": "No stored quotes for this instrument — there is nothing to "
        "draw a chart from.",
    "price.now": "now {price}",
    "price.span.24h": "24 h",
    "price.span.7d": "7 days",
    "price.click_for_chart": "Click to see the price chart.",
    "price.chart_for": "{symbol} price",
    "price.close": "✕ close",
    "price.range": "Price range",
    "price.range.7d": "7 days",
    "price.range.30d": "30 days",
    "price.range.90d": "90 days",
    "price.too_few_quotes": "Too few quotes in this range.",
    "price.rate": "Price ($)",
    "price.price": "Price ($)",
    "price.entry_price": "Entry price ($)",
    "price.this_event": "This event",
    "price.bot": "Bot",
    "price.mark.entry": "entry",
    "price.mark.exit": "exit",
    "price.mark.held": "still held",
    "price.note.triangles": "The triangles are the bot's trades: ▲ buy, ▼ sell. ",
    "price.note.circle": "The circle is a position the bot is **still holding**. ",
    "price.instrument_change": "The instrument's own price: **{change}%** over the selected "
        "range (this is not the bot's result — it held only part of the account and only for "
        "part of that time). {note}",

    # ---------- research screens ----------
    "research.intro": "Research tools — they **do not run a portfolio**. They answer “does "
        "this idea hold up?”, not “what do you have right now”.",
    "research.tab.crosssec": "📊 Cross-sectional ranking",
    "research.tab.screen": "🧭 Diversification screen",
    "research.unknown_date": "unknown date",
    "research.timeout": "Timed out (10 min).",
    "research.no_results": "No stored results for: {name}.",
    "research.run_to_see": "Run the study to see results here:",
    "research.last_run": "Last computed: **{when}**",
    "research.recompute": "Recompute on stored data",
    "research.done": "Done.",
    "research.failed": "It did not work.",
    "research.spinner.matrix": "Computing the matrix...",
    "research.spinner.correlations": "Computing correlations...",
    "research.sigmas": "{n} standard deviations from zero",
    "research.sigmas.help": "Below 2 deviations the result is indistinguishable from chance — "
        "however large the percentage is.",
    "research.sign.consistent": "consistent sign",
    "research.sign.consistently_negative": "consistently negative",
    "research.sign.flips": "the sign flips → that is noise",
    "research.window_line": "{icon} **{market} · {direction}** — clears the bar in "
        "{wins}/{total} windows, {tail}",
    "research.crosssec.title": "Cross-sectional ranking",
    "research.crosssec.name": "cross-sectional ranking",
    "research.crosssec.help": "Buy the strongest assets, sell the weakest — a bet on the "
        "**difference between assets**, not on the market's direction.",
    "research.crosssec.luck_question": "**Is the result distinguishable from luck?**",
    "research.crosssec.all_noise": "No variant reaches 2 standard deviations from zero. "
        "**These percentages are not an edge** — they sit within what chance produces.",
    "research.crosssec.all_windows": "**All windows** — does the sign hold?",
    "research.crosssec.hurdle_help": "The bar depends on exposure: the *long only* variant is "
        "measured against a buy&hold basket, *long-short* (market neutral) against cash.",
    "research.crosssec.survivorship": "**The main caveat: survivorship bias.** The crypto "
        "universe is the pairs that *made it* to today — no LUNA, no FTT. On top of that the "
        "long-short variant needs perpetual futures, and funding cost is not modelled at all. "
        "This measures a hypothesis; it is not a strategy.",
    "research.screen.title": "Diversification screen",
    "research.screen.name": "diversification screen",
    "research.screen.help": "A question about risk, not about forecasting: when the world "
        "market (**{benchmark}**) falls, what does *not* fall with it?",
    "research.screen.as_of": "⏳ This is a screen **as of {date}** — it shows only what was "
        "known then, not the state today. Computed {when}.",
    "research.screen.negatively_correlated": "Negatively correlated",
    "research.screen.n_of_m": "{n} of {m}",
    "research.screen.passes": "Passes the screen",
    "research.screen.passes.help": "Low correlation, stable over time, positive return.",
    "research.screen.negative_and_earning": "Negative and earning",
    "research.screen.negative_and_earning.help": "Assets that really are negatively correlated "
        "and do not lose money doing it.",
    "research.screen.none_negative": "Among the assets with a **positive return** there is not "
        "one that is negatively correlated with the world market. That is a result, not a "
        "missing result: the realistic goal is *low* correlation, not negative.",
    "research.screen.rolling_matters": "**The “3-year min/max” columns matter more than the "
        "average** — they show what the correlation did at the worst moment. An asset "
        "averaging +0.2 that jumps to +0.75 in a crisis did not protect the portfolio when it "
        "was needed.",
    "research.screen.regime_warning": "**This table describes a regime that has just ended.** "
        "Run on data up to 2016, the screen picked long-term bonds (TLT) as an exemplary "
        "diversifier — correlation −0.27 and never positive. Over the next decade TLT lost "
        "5.2% a year and jumped to +0.75 in the 2022 crisis. See for yourself: `--as-of` ten "
        "years ago.",
    "research.screen.as_of_input": "Recompute as of (YYYY-MM-DD)",
    "research.screen.as_of_placeholder": "e.g. 2016-07-30",

    # ---------- verdicts (stored tokens stay Polish; these are their labels) ----------
    "verdict.candidate.label": "CANDIDATE",
    "verdict.candidate.help": "low correlation, stable, positive return",
    "verdict.unstable.label": "UNSTABLE",
    "verdict.unstable.help": "low on average, but moves with the market in a crisis",
    "verdict.loses.label": "LOSES",
    "verdict.loses.help": "diversifies, but eats the portfolio (negative return)",
    "verdict.trap.label": "TRAP",
    "verdict.trap.help": "negatively correlated by construction — and pays for it by eroding "
        "capital",
    "verdict.correlated.label": "CORRELATED",
    "verdict.correlated.help": "moves with the market — does not diversify",

    # ---------- research table columns ----------
    "col.market": "market",
    "col.direction": "direction",
    "col.window": "window",
    "col.total_return_pct": "return %",
    "col.hurdle_pct": "hurdle %",
    "col.excess_vs_hurdle_pp": "excess pts",
    "col.sharpe": "Sharpe",
    "col.max_drawdown_pct": "drawdown %",
    "col.avg_net_exposure_pct": "net %",
    "col.corr": "correlation",
    "col.roll_min": "3-year min",
    "col.roll_max": "3-year max",
    "col.cagr_pct": "CAGR %",
    "col.months": "months",
    "col.asset": "Asset",
    "col.as_of": "as of",
    "col.verdict": "verdict",
    # ---------- engine alerts (journalled, webhooked, replayed in the panel) ----------
    "alert.config": "settings changed: {changes}",
    "alert.kill_switch": "daily loss limit reached — new entries are blocked",
    "alert.drawdown": "down {dd}% from the equity peak",
    "alert.trade_open": "{symbol} opened {side} @ {price} (p={prob})",
    "alert.trade_close": "{symbol} closed {side} ({reason}) PnL {pnl} USDT",
    "alert.trade_rollover": "{symbol} extended {side} @ {price} (p={prob}, instead of exiting "
        "on {reason})",
    "alert.connection.lost": "no connection to the exchange — retrying, not trading for now",
    "alert.connection.back": "the exchange connection is back — the bot is reading the market "
        "again",
    "alert.initial_allocation": "first allocation of the basket",
    "alert.rebalance": "rebalanced to target weights (drift {drift} points)",
    "alert.portfolio_drawdown": "down {dd}% from the portfolio's peak value",

    # ---------- config store ----------
    "store.forbidden_fields": "These fields cannot be changed from the panel: {fields}",
    "store.value_rejected": "Value rejected, nothing was saved:",
    # ---------- printed portfolio report ----------
    "report.trend.on": "ON",
    "report.trend.off": "off",
    "report.portfolio.title": "TRADEMON — PORTFOLIO REPORT (rebalancer)",
    "report.portfolio.period": "Period: {start} .. {end} ({bars} trading days)",
    "report.portfolio.basket": "Basket: {basket}   trend filter: {trend}",
    "report.portfolio.strategy": "  Strategy (rebalanced):  {ret}%   CAGR {cagr}%/yr   "
        "Sharpe {sharpe}   max DD {dd}%",
    "report.portfolio.benchmark": "  Benchmark (buy and hold): {ret}%   Sharpe {sharpe}   "
        "max DD {dd}%",
    "report.portfolio.excess": "  Edge over the benchmark: {excess} pct. points",
    "report.portfolio.volatility": "  Volatility (annualised): {vol}%",
    "report.portfolio.counts": "  Rebalances: {rebalances}   trades: {trades}   "
        "fees: {fees}",
    "report.portfolio.verdict.beat": "CONCLUSION: rebalancing BEAT simply holding the "
        "basket, after costs.",
    "report.portfolio.verdict.missed": "CONCLUSION: rebalancing did NOT beat simply holding "
        "the basket, after costs.",
    "report.portfolio.caveat": "Note: the value of rebalancing is discipline and risk "
        "control, not “alpha”. The result depends on the period; this is an educational "
        "tool, not investment advice.",

    # ---------- diversification screen (printed) ----------
    "screen.no_candidates": "No candidates with enough history.",
    "screen.negatives": "Assets NEGATIVELY correlated with {benchmark}: {n} of {total}.",
    "screen.none_negative.1": "  None — and that is precisely the result: among sensible "
        "assets",
    "screen.none_negative.2": "  negative correlation with the world market barely exists.",
    "screen.none_negative.3": "  The realistic goal is LOW correlation with a positive return.",
    "screen.keeper": "{symbol} (corr. {corr}, CAGR {cagr}%)",
    "screen.keepers": "Pass the screen ({n}): {names}",
    "screen.no_keepers.1": "Nothing passes the screen — no asset combines low",
    "screen.no_keepers.2": "correlation, stability of it, and a positive return.",
    "screen.unstable_item": "{symbol} (up to {roll_max})",
    "screen.unstable": "Low correlation ON AVERAGE, but they fail in a crisis: {names}",
    "screen.trap_item": "{symbol} ({cagr}%/yr)",
    "screen.traps": "Negative return — ballast that sinks the boat: {names}",

    # ---------- cross-sectional verdict (printed) ----------
    "hurdle.basket": "basket",
    "hurdle.cash": "cash",
    "verdict.sign.consistent": "CONSISTENT sign",
    "verdict.sign.negative": "CONSISTENTLY NEGATIVE",
    "verdict.sign.flips": "the sign FLIPS -> that is noise",
    "verdict.line": "{market} {direction}: beats {hurdle} in {wins}/{total} windows, excess "
        "from {lo} to {hi} pts (spread {spread} pts) — {tail}",

    # ---------- HTML backtest report ----------
    "report.html.title": "TraDaemon 👹💰 — backtest report",
    "report.html.subtitle": "Period: {start} .. {end} · timeframe {timeframe} · {pairs} pairs",
    "report.html.verdict": "VERDICT: {verdict}",
    "report.html.positive": "POSITIVE after costs",
    "report.html.negative": "NEGATIVE after costs",
    "report.html.avg_at_work": "At work (avg.)",

    # ---------- book backtest table (fixed-width) ----------
    "report.book.period": "period: {start} .. {end}  timeframe {timeframe}",
    "report.book.pairs": "pairs",
    "report.book.col.board": "board",
    "report.book.col.allocation": "allocation",
    "report.book.col.cap": "cap",
    "report.book.col.result": "result",
    "report.book.col.sharpe": "sharpe",
    "report.book.col.max_dd": "maxDD",
    "report.book.col.trades": "trades",
    "report.book.col.signals": "signals",
    "report.book.col.no_slot": "no slot",
    "report.book.col.in_market": "in market",
    # ---------- research CLI reports (shown in the panel's research tab) ----------
    "cli.crosssec.no_results": "No results — download the data first (--refresh).",
    "cli.crosssec.whole": "WHOLE",
    "cli.crosssec.title": "MODULE 3: CROSS-SECTIONAL RANKING — the same code on two markets",
    "cli.crosssec.hurdle_note": "The bar depends on exposure: long_only (~100% net) is "
        "measured against\na buy&hold basket, long_short (~0% net) against cash. Comparing "
        "a\nmarket-neutral book with a fully long basket is the same "
        "mismatched-exposure\nmistake that used to flatter Module 1.",
    "cli.crosssec.sign_question": "DOES THE SIGN HOLD ACROSS DISJOINT WINDOWS?",
    "cli.crosssec.luck_question": "IS THE RESULT DISTINGUISHABLE FROM LUCK? (whole periods)",
    "cli.crosssec.significance_line": "{market} {direction}: return {ret}% at {sigmas} "
        "deviations from zero — {tail}",
    "cli.crosssec.significant": "SIGNIFICANT",
    "cli.crosssec.not_significant": "INDISTINGUISHABLE from noise (needs ~2)",
    "cli.crosssec.whole_is_context": "The WHOLE window is context only — it overlaps windows "
        "1..N,\nso it is not independent confirmation.",
    "cli.screen.title": "DIVERSIFICATION SCREEN — what moves differently from {benchmark}?",
    "cli.screen.subtitle": "(correlations of monthly returns, {period})",
    "cli.screen.period.as_of": "{years} years to {as_of} — ONLY what was knowable then",
    "cli.screen.period.recent": "the last {years} years",
    "cli.screen.how_to_read": "HOW TO READ THIS",
    "cli.screen.rolling_matters": "The “3-year min/max” columns matter more than the average "
        "correlation:\nthey show what the correlation did at the worst moment. An asset "
        "averaging\n+0.2 that jumps to +0.75 in a crisis did not protect the portfolio when "
        "it was needed.",
    "cli.screen.conclusion": "CONCLUSION",
    "cli.screen.regime_warning": "NOTE: this table describes a regime that has JUST ENDED.\n"
        "Run `--as-of` ten years ago and see what the method would have picked then\n"
        "— it named long-term bonds, which went on to lose 5%/yr and stopped\n"
        "diversifying exactly during the 2022 crisis.",
    "col.sigmas_from_zero": "dev. from 0",
    "col.avg_gross_exposure_pct": "at work %",
    "col.n_rebalances": "rebalances",
    "col.fees_pct_of_capital": "costs %",
}
