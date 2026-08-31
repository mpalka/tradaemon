"""TraDaemon dashboard — read-only lab view over the engine's runtime files.

Two modules share this dashboard: the crypto scalper and the portfolio manager.
Each opens on a **beginner screen** (plain language, no jargon) with the technical
tabs tucked behind a "details" expander. Every sentence comes from the message
catalogues in `trademon.locales`, so the viewer picks Polish or English per session.
The engine is the only writer; this only reads state.json / *.jsonl.
Run: streamlit run src/trademon/dashboard/app.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import altair as alt
import pandas as pd
import streamlit as st

from trademon import __version__, config_store, i18n
from trademon.backtest.metrics import (
    avg_exposure_pct,
    exposure_series,
    max_drawdown,
    periods_per_year,
    return_on_risked_pct,
    sharpe_ratio,
    time_in_market_pct,
)
from trademon.config import load_config
from trademon.dashboard import humanize, journals, layout, price_view
from trademon.data.storage import TIMEFRAME_MS
from trademon.i18n import t
from trademon.research.log import load_experiments

st.set_page_config(page_title="TraDaemon", page_icon="👹💰", layout="wide")

cfg = load_config()
runtime = cfg.paths.runtime_dir
ACCENT, BH_COLOR, GOOD, BAD = "#2a78d6", "#c2c2c2", "#0ca30c", "#d03b3b"
BH_FAIR_COLOR = "#5a5a5a"   # the like-for-like benchmark, so it reads stronger than the all-in one
# Window codes, not labels: the radio shows a translated caption but the lookup and
# the session state stay language-independent.
RANGES = {"7d": 7, "30d": 30, "all": None}

# Chart series labels, resolved per render because the legend is translated too. The
# bot plays with only a part of the account, so the all-in "buy & hold" is not a fair
# yardstick — both are drawn, the fair one more prominent. Keep the translations short
# and differing from the first word: the legend truncates, and two labels sharing an
# opening word render identically.
def series_names() -> tuple[str, str, str]:
    return t("chart.series.bot"), t("chart.series.bh_all"), t("chart.series.bh_fair")

# The engine stores UTC and the container runs in UTC; render in the viewer's zone.
try:
    DISPLAY_TZ: ZoneInfo | None = ZoneInfo(cfg.display_timezone)
except ZoneInfoNotFoundError:
    DISPLAY_TZ = None


def to_local(ts):
    """UTC/ISO timestamps -> local wall-clock (tz-naive), so Altair renders the
    same local time regardless of the browser's own timezone."""
    return humanize.to_local(ts, DISPLAY_TZ)


# ---------- data access ----------

def discover_books() -> dict[str, Path]:
    """A crypto 'book' is a portfolio with its own state. The default engine writes
    to runtime/ directly; A/B variants to runtime/<name>/. (Portfolio books live
    under runtime/portfolio/<name>/ and are handled by the portfolio view.)"""
    books: dict[str, Path] = {}
    if (runtime / "state.json").exists():
        books["default"] = runtime
    for sub in sorted(p for p in runtime.glob("*/") if p.is_dir()):
        if sub.name == "portfolio":
            continue
        if (sub / "state.json").exists():
            books[sub.name] = sub
    return books


def load_state(book_dir: Path) -> dict | None:
    path = book_dir / "state.json"
    return json.loads(path.read_text()) if path.exists() else None


def load_config_history() -> list[dict]:
    """Config edits made from the config screen; shared by the chart marker and the
    history panel. The journal lives next to the books, so it survives restarts."""
    return config_store.load_history(runtime)


def pnl_color(v: float) -> str:
    return f"color: {GOOD}" if v > 0 else (f"color: {BAD}" if v < 0 else "")


# ---------- derived metrics ----------

def book_equity_series(equity_df: pd.DataFrame) -> pd.DataFrame:
    """One equity point per timestamp (all pairs share the book's equity)."""
    if equity_df.empty:
        return pd.DataFrame(columns=["timestamp", "equity"])
    df = equity_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.groupby("timestamp", as_index=False)["equity"].last()


def book_exposure_series(equity_df: pd.DataFrame) -> pd.DataFrame:
    """Equity and free cash per timestamp — how much of the account was in the market."""
    if equity_df.empty or "cash" not in equity_df:
        return pd.DataFrame(columns=["timestamp", "equity", "cash"])
    df = equity_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.groupby("timestamp", as_index=False)[["equity", "cash"]].last()


def money_at_work_pct(equity_df: pd.DataFrame) -> float:
    """Average share of the account that was actually in the market, in percent."""
    ex = book_exposure_series(equity_df)
    return avg_exposure_pct(ex["equity"], ex["cash"]) if len(ex) else 0.0


def buy_hold_curve(equity_df: pd.DataFrame, initial: float) -> pd.DataFrame:
    """Equal-weight buy&hold of all pairs from per-bar close prices logged
    alongside equity — the all-in benchmark, everything in the market from the
    first bar of the window.

    The bot never has the whole account in the market, so this line alone is not a
    fair yardstick — it "loses" every downturn the bot simply was not there for.
    `matched_exposure_curve` below is the like-for-like one.
    """
    if equity_df.empty or "close" not in equity_df:
        return pd.DataFrame()
    df = equity_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    wide = df.pivot_table(index="timestamp", columns="symbol", values="close").ffill()
    if wide.empty:
        return pd.DataFrame()
    ratio = wide.div(wide.iloc[0]).mean(axis=1)
    bh = initial * ratio
    return pd.DataFrame({"timestamp": bh.index, "equity": bh.values})


def matched_exposure_curve(equity_df: pd.DataFrame, initial: float) -> pd.DataFrame:
    """The same market ridden with the bot's own exposure, bar by bar: each bar earns
    the basket's return times the share of the account the bot had in the market
    going into it, the rest sitting in cash earning nothing.

    Compounded per bar rather than scaled by one average, because one average is
    wrong the moment the risk settings change mid-flight. A book that ran at 30% for
    three weeks and then at 90% averages ~40%, which describes neither half — and the
    average depends on the window, so switching 7 days / 30 days used to change the
    *benchmark* and not just the period. Here the shape inside any stretch of the
    curve is the same whichever window it is drawn in.

    Exposure is lagged one bar on purpose: the engine journals `cash`/`equity` at
    candle close, so the exposure stamped on bar *t* already knows how that bar went.
    Multiplying it by bar *t*'s return would let the benchmark trade on the future.

    Note that "return on money at work" next to the chart still divides by the
    window's *average* exposure (`return_on_risked_pct`) — a deliberately cruder
    approximation, so the two numbers are not meant to line up exactly.
    """
    if equity_df.empty or "close" not in equity_df or "cash" not in equity_df:
        return pd.DataFrame()
    df = equity_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    wide = df.pivot_table(index="timestamp", columns="symbol", values="close").ffill()
    if wide.empty:
        return pd.DataFrame()
    # Equal weight restored every bar — the weights of the buy&hold line above drift
    # with the prices, and there is nothing to drift here: exposure is re-read anyway.
    basket = wide.pct_change().mean(axis=1).fillna(0.0)
    ex = book_exposure_series(df).set_index("timestamp")
    expo = (exposure_series(ex["equity"], ex["cash"])
            .reindex(basket.index).ffill().fillna(0.0))
    growth = 1.0 + expo.shift(1).fillna(0.0) * basket
    curve = initial * growth.cumprod()
    return pd.DataFrame({"timestamp": curve.index, "equity": curve.values})


def with_live_point(equity_df: pd.DataFrame, state: dict) -> pd.DataFrame:
    """Append a synthetic 'now' row (per pair) from state.json so the curves reach
    the current mark-to-market equity — the same number shown in 'Ile masz' — and
    move on every refresh, instead of stepping only when a 4h candle closes. The
    engine journals equity at candle close; the ticker keeps state.json's equity
    and last_close current between closes, which is what this fills in."""
    ua, eq = state.get("updated_at"), state.get("equity")
    if not ua or eq is None or equity_df.empty or "timestamp" not in equity_df:
        return equity_df
    ts = pd.to_datetime(ua, utc=True)
    if ts <= pd.to_datetime(equity_df["timestamp"], utc=True).max():
        return equity_df  # a candle already closed at/after 'now'; no gap to fill
    # Match the journal's second-resolution ISO exactly — a stray microsecond field
    # would break the strict format pandas infers over the otherwise-uniform column.
    now_iso = ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    last_close = state.get("last_close", {})
    cash = float(state.get("cash", eq))
    hist_syms = list(equity_df["symbol"].unique()) if "symbol" in equity_df else []
    rows = [{"timestamp": now_iso, "symbol": s, "close": last_close[s],
             "equity": float(eq), "cash": cash}
            for s in hist_syms if s in last_close]
    if not rows:
        # Only per-pair rows are appended. A row without prices would extend the
        # bot's line past both benchmarks — buy_hold_curve pivots on `symbol` and
        # drops it — which is exactly how a dead engine used to render: a flat blue
        # tail running off to the right of the grey ones, looking like a bot that
        # was merely idle. There is nothing honest to draw there either, because
        # equity() without prices is the entry price restated, not a valuation.
        # The curves end where the data ends; bot_status above says the rest.
        return equity_df
    return pd.concat([equity_df, pd.DataFrame(rows)], ignore_index=True)


def window_df(df: pd.DataFrame, days: int | None) -> pd.DataFrame:
    if df.empty or days is None or "timestamp" not in df:
        return df
    ts = pd.to_datetime(df["timestamp"])
    return df[ts >= ts.max() - pd.Timedelta(days=days)]


def live_metrics(equity_df: pd.DataFrame, trades: pd.DataFrame, timeframe: str) -> dict:
    eq = book_equity_series(equity_df)
    m: dict = {}
    if len(eq) > 1:
        s = eq.set_index("timestamp")["equity"]
        m["sharpe"] = sharpe_ratio(s, periods_per_year(timeframe))
        m["max_dd"] = max_drawdown(s) * 100.0
        # Return above is measured on the whole account; most of it never traded.
        ex = book_exposure_series(equity_df)
        m["at_work"] = avg_exposure_pct(ex["equity"], ex["cash"]) if len(ex) else 0.0
        m["in_market"] = time_in_market_pct(ex["equity"], ex["cash"]) if len(ex) else 0.0
        total_return = (s.iloc[-1] / s.iloc[0] - 1.0) * 100.0
        m["return_on_risked"] = return_on_risked_pct(total_return, m["at_work"])
    if len(trades):
        pnl = trades["pnl"]
        wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
        m["win_rate"] = (pnl > 0).mean() * 100.0
        m["profit_factor"] = (
            float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
        )
        hold = pd.to_datetime(trades["exit_time"]) - pd.to_datetime(trades["entry_time"])
        m["avg_hold_h"] = hold.dt.total_seconds().mean() / 3600.0
    return m


def config_change_marks(start, end) -> alt.Chart | None:
    """Dashed rules where the configuration changed.

    Changing a parameter mid-flight makes everything after it a different strategy on
    the same curve. Without the seam drawn, comparing a book before and after an edit
    silently averages two experiments — the marker is what keeps the chart honest.
    """
    rows = load_config_history()
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["timestamp"] = to_local(df["timestamp"])
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
    if df.empty:
        return None
    df = (df.groupby("timestamp", as_index=False)
            .agg(zmiany=("field", lambda s: ", ".join(sorted(set(s))))))
    return alt.Chart(df).mark_rule(color=humanize.MUTED, strokeDash=[4, 4]).encode(
        x=alt.X("timestamp:T"),
        tooltip=[alt.Tooltip("timestamp:T", title=t("chart.settings_change"),
                             format="%d.%m.%Y %H:%M"),
                 alt.Tooltip("zmiany:N", title=t("chart.fields"))],
    )


def equity_chart(strat: pd.DataFrame, bh: pd.DataFrame,
                 bh_fair: pd.DataFrame | None = None) -> alt.Chart:
    s_bot, s_bh_all, s_bh_fair = series_names()
    value_title = t("chart.value")
    layers = [strat.assign(seria=s_bot)[["timestamp", "equity", "seria"]]]
    if len(bh):
        layers.append(bh.assign(seria=s_bh_all)[["timestamp", "equity", "seria"]])
    if bh_fair is not None and len(bh_fair):
        layers.append(bh_fair.assign(seria=s_bh_fair)[["timestamp", "equity", "seria"]])
    data = pd.concat(layers, ignore_index=True)
    data["timestamp"] = to_local(data["timestamp"])
    lines = alt.Chart(data).mark_line().encode(
        x=alt.X("timestamp:T", title=None, axis=layout.time_axis()),
        y=alt.Y("equity:Q", title=value_title, scale=alt.Scale(zero=False, nice=False)),
        color=alt.Color("seria:N", title=None, legend=layout.legend(),
                        scale=alt.Scale(domain=[s_bot, s_bh_all, s_bh_fair],
                                        range=[ACCENT, BH_COLOR, BH_FAIR_COLOR])),
        tooltip=[alt.Tooltip("timestamp:T", title=t("chart.time"), format="%d.%m.%Y %H:%M"),
                 alt.Tooltip("equity:Q", title=value_title, format=",.2f"),
                 alt.Tooltip("seria:N", title=t("chart.series"))],
    )
    marks = config_change_marks(data["timestamp"].min(), data["timestamp"].max())
    chart = alt.layer(lines, marks) if marks is not None else lines
    return chart.properties(height=layout.chart_height())


# ---------- beginner main screen (crypto) ----------

def render_beginner(state: dict, equity_df: pd.DataFrame, trades: pd.DataFrame,
                    alerts: pd.DataFrame) -> None:
    initial = cfg.paper.initial_capital
    eq = float(state.get("equity", initial))
    cash = float(state.get("cash", initial))
    invested = max(eq - cash, 0.0)
    change = (eq / initial - 1.0) * 100.0
    # Read here, shown twice: next to "Ile masz" and again under the chart, where it
    # answers why the fair benchmark can sit far from the all-in one.
    now_at_work = (invested / eq * 100.0) if eq else 0.0

    # 1) What you have
    top = st.columns([2, 3])
    with top[0]:
        st.metric(t("home.you_have"), humanize.money2(eq),
                  t("home.since_start", change=f"{change:+.2f}"))
        st.caption(humanize.md(t("home.split", free=humanize.money2(cash),
                                 invested=humanize.money2(invested),
                                 pct=f"{now_at_work:.0f}")))
    # 2) status bota
    with top[1]:
        tf = state.get("timeframe", cfg.exchange.timeframe)
        status = humanize.bot_status(state.get("last_candle_ts", {}),
                                     TIMEFRAME_MS.get(tf, 0), datetime.now(UTC), DISPLAY_TZ)
        st.markdown(f"### {status['emoji']} {t('home.bot_status')}")
        st.markdown(status["text"])
        # The candle clock above is coarse by nature — on 4h bars it stays green
        # for hours after the exchange goes quiet. This line is the live one.
        conn = humanize.connection_status(state.get("updated_at"), datetime.now(UTC))
        colour = humanize.GOOD if conn["ok"] else humanize.BAD
        # &nbsp; on purpose: Streamlit's markdown drops a plain space that sits
        # between an emoji and an inline tag, gluing the two together.
        st.markdown(f"{conn['emoji']}&nbsp;<span style='color:{colour}'>{conn['text']}</span>",
                    unsafe_allow_html=True)
        if state.get("kill_switch"):
            st.warning(t("home.kill_switch_on"))

    st.divider()

    # 3) How it went
    st.subheader(t("home.how_it_went"))
    rng_label = st.radio(t("home.range"), list(RANGES), horizontal=True,
                         format_func=lambda code: t(f"home.range.{code}"),
                         label_visibility="collapsed")
    equity_df = with_live_point(equity_df, state)  # curve tracks 'Ile masz', not just closes
    win = window_df(equity_df, RANGES[rng_label])
    strat_eq = book_equity_series(win)
    if len(strat_eq):
        at_work = money_at_work_pct(win)
        scale = strat_eq["equity"].iloc[0] / initial  # rebase to the window start
        bh = buy_hold_curve(win, initial)
        bh_fair = matched_exposure_curve(win, initial)
        if len(bh):
            bh = bh.assign(equity=bh["equity"] * scale)
        if len(bh_fair):
            bh_fair = bh_fair.assign(equity=bh_fair["equity"] * scale)
        st.altair_chart(equity_chart(strat_eq, bh, bh_fair), width="stretch")
        st.caption(t("home.benchmark_explainer", avg=f"{at_work:.0f}",
                     now=f"{now_at_work:.0f}"))
        # The same result counted two ways: idle cash makes the first number look gentler.
        win_return = (strat_eq["equity"].iloc[-1] / strat_eq["equity"].iloc[0] - 1.0) * 100.0
        risked = return_on_risked_pct(win_return, at_work)
        c1, c2 = st.columns(2)
        c1.metric(t("metric.return_total"), f"{win_return:+.2f}%",
                  help=humanize.glossary("return_total"))
        c2.metric(t("metric.return_at_work"),
                  f"{risked:+.2f}%" if risked is not None else "—",
                  help=humanize.glossary("return_at_work"))
    else:
        st.info(t("home.not_enough_data"))

    st.divider()

    # 4) Co bot teraz trzyma
    # Each instrument is clickable: the title opens its price chart below (hovering
    # shows the numbers). The choice is kept in session state rather than a popover,
    # which the 15s fragment refresh would keep closing — see price_view's docstring.
    st.subheader(t("home.holdings"))
    price_view.styles()
    positions = state.get("positions", {})
    last_close = state.get("last_close", {})

    # Both wrappers scope a cache to this one render: the event journal below asks
    # for the same eleven-ish pairs across sixty rows, and every row needs a tooltip.
    prices_for = price_view.memoized(lambda sym: price_view.crypto_prices(sym, equity_df))
    tooltip = price_view.tooltips(prices_for)

    if not positions:
        st.info(t("home.holdings.empty"))
    else:
        st.caption(t("home.holdings.click"))
        cols = st.columns(min(len(positions), 3))
        for i, (sym, pos) in enumerate(positions.items()):
            card = humanize.position_card(pos, last_close.get(sym))
            with cols[i % len(cols)]:
                price_view.preview_button(f"**{card['emoji']} {card['title']}**", sym,
                                          "crypto_pos", key=f"pos_{sym}",
                                          tooltip=tooltip(sym))
                tone = "green" if card["pnl"] > 0 else ("red" if card["pnl"] < 0 else "gray")
                st.markdown(f":{tone}[{card['detail']}]")
        price_view.render("crypto_pos", prices_for, trades, positions)

    st.divider()

    # 5) Event log
    st.subheader(t("home.events"))
    if len(alerts):
        st.caption(t("home.events.click"))
        # Sixty, not thirty: a book with five slots can close five positions and
        # open five more on one candle, so thirty rows is three candles — half a
        # day on 4h bars. A list that short gives the same "nothing older
        # happened" impression the backdated timestamps used to give. Sixty is
        # roughly a day, which is the span someone checking in actually asks about.
        rows = journals.records(alerts.sort_values("timestamp", ascending=False).head(60))
        for n, rec in enumerate(rows):
            e = humanize.event_line(rec, DISPLAY_TZ)
            sym = rec.get("symbol")
            if sym:  # risk/config alerts carry no instrument — nothing to preview
                key = f"ev_{n}_{sym}"
                price_view.preview_button(f"{e['emoji']} `{e['time']}` {e['text']}", sym,
                                          "crypto_ev", key=key,
                                          at=rec.get("timestamp"), tooltip=tooltip(sym))
                # inside the loop: the chart belongs under the clicked line, not
                # under fifteen rows of other events where nobody looks for it
                price_view.render("crypto_ev", prices_for, trades, positions, item=key)
            else:
                st.markdown(f"{e['emoji']} &nbsp;`{e['time']}` &nbsp; {e['text']}")
    else:
        st.caption(t("home.events.empty"))


# ---------- detail tabs (unchanged logic, now behind an expander) ----------

def tab_metrics(equity_df: pd.DataFrame, trades: pd.DataFrame, state: dict) -> None:
    m = live_metrics(equity_df, trades, state.get("timeframe", cfg.exchange.timeframe))
    c = st.columns(4)
    c[0].metric(t("metric.sharpe"), f"{m.get('sharpe', 0):.2f}",
                help=humanize.glossary("sharpe"))
    c[1].metric(t("metric.max_drawdown"), f"{m.get('max_dd', 0):.2f}%",
                help=humanize.glossary("max_drawdown"))
    pf = m.get("profit_factor")
    c[2].metric(t("metric.profit_factor"),
                f"{pf:.2f}" if pf not in (None, float("inf")) else "—",
                help=humanize.glossary("profit_factor"))
    c[3].metric(t("metric.win_rate"), f"{m['win_rate']:.0f}%" if "win_rate" in m else "—",
                help=humanize.glossary("win_rate"))
    c2 = st.columns(4)
    c2[0].metric(t("metric.money_at_work"), f"{m.get('at_work', 0):.0f}%",
                 help=humanize.glossary("money_at_work"))
    c2[1].metric(t("metric.time_in_market"), f"{m.get('in_market', 0):.0f}%",
                 help=humanize.glossary("time_in_market"))
    risked = m.get("return_on_risked")
    c2[2].metric(t("metric.return_at_work"),
                 f"{risked:+.2f}%" if risked is not None else "—",
                 help=humanize.glossary("return_at_work"))


def tab_analytics(trades: pd.DataFrame) -> None:
    if not len(trades):
        st.caption(t("analytics.no_trades"))
        return
    st.subheader(t("analytics.per_pair"))
    # Aggregate under stable English names, then translate the headers on the way out:
    # the frame is also what `layout.cards` and the styler address by column.
    per = trades.groupby("symbol").agg(
        trades=("pnl", "count"),
        win_rate=("pnl", lambda x: (x > 0).mean() * 100),
        net_pnl=("pnl", "sum"),
        fees=("fees", "sum"),
    ).reset_index().sort_values("net_pnl", ascending=False)
    cols = {c: t(f"col.{c}") for c in ("symbol", "trades", "win_rate", "net_pnl", "fees")}
    per = per.rename(columns=cols)
    if layout.is_mobile():
        layout.cards(per, cols["symbol"],
                     [cols["net_pnl"], cols["win_rate"], cols["trades"]],
                     {cols["net_pnl"]: "+.2f", cols["win_rate"]: ".0f",
                      cols["trades"]: ".0f"},
                     color_by=cols["net_pnl"])
    else:
        st.dataframe(
            per.style.map(pnl_color, subset=[cols["net_pnl"]]).format(
                {cols["win_rate"]: "{:.0f}%", cols["net_pnl"]: "{:+.2f}",
                 cols["fees"]: "{:.2f}"}),
            width="stretch", hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(t("analytics.pnl_distribution"))
        hist = alt.Chart(trades).mark_bar().encode(
            x=alt.X("pnl:Q", bin=alt.Bin(maxbins=30), title=t("analytics.pnl_axis")),
            y=alt.Y("count()", title=t("analytics.count")),
            color=alt.condition(alt.datum.pnl > 0, alt.value(GOOD), alt.value(BAD)),
        ).properties(height=layout.chart_height(240))
        st.altair_chart(hist, width="stretch")
    with col2:
        st.subheader(t("analytics.exit_reasons"))
        if "exit_reason" in trades:
            reasons = trades["exit_reason"].value_counts().reset_index()
            reasons.columns = ["reason", "count"]
            reasons["reason"] = reasons["reason"].map(humanize.exit_reason)
            bar = alt.Chart(reasons).mark_bar(color=ACCENT).encode(
                x=alt.X("count:Q", title=t("analytics.count")),
                y=alt.Y("reason:N", title=None, sort="-x"),
            ).properties(height=layout.chart_height(240))
            st.altair_chart(bar, width="stretch")


def tab_model(state: dict) -> None:
    st.subheader(t("model.why"))
    st.caption(t("model.why.help"))
    signals = state.get("signals", {})
    if not signals:
        st.caption(t("model.no_signals"))
        return
    c_pair, c_thr, c_dec = t("col.symbol"), t("col.threshold"), t("col.decision")
    rows = [{
        c_pair: sym, "p(long)": sig.get("p_long"), c_thr: sig.get("threshold"),
        c_dec: humanize.reason(sig.get("reason", "")),
    } for sym, sig in signals.items()]
    df = pd.DataFrame(rows).sort_values("p(long)", ascending=False, na_position="last")
    if layout.is_mobile():
        layout.cards(df, c_pair, ["p(long)", c_thr, c_dec],
                     {"p(long)": ".3f", c_thr: ".2f"})
    else:
        st.dataframe(df.style.format({"p(long)": "{:.3f}", c_thr: "{:.2f}"}, na_rep="—"),
                     width="stretch", hide_index=True)


def tab_variants(books: dict[str, Path]) -> None:
    st.subheader(t("variants.title"))
    if len(books) < 2:
        st.info(t("variants.none"))
    initial = cfg.paper.initial_capital
    c_variant, c_equity, c_sharpe = t("col.variant"), t("col.equity"), t("metric.sharpe")
    c_dd, c_at_work = t("col.max_dd_pct"), t("col.at_work_pct")
    c_on_risked, c_win, c_trades = (t("col.return_on_risked_pct"), t("col.win_rate_pct"),
                                    t("col.trades"))
    curves, metric_rows = [], []
    for name, bdir in books.items():
        state = load_state(bdir) or {}
        eq_df = journals.load_jsonl(bdir / "equity.jsonl")
        trades = journals.load_jsonl(bdir / "trades.jsonl")
        s = book_equity_series(eq_df)
        if len(s):
            curves.append(s.assign(wariant=name))
        m = live_metrics(eq_df, trades, state.get("timeframe", cfg.exchange.timeframe))
        metric_rows.append({
            c_variant: name, c_equity: state.get("equity", initial),
            c_sharpe: m.get("sharpe"), c_dd: m.get("max_dd"),
            c_at_work: m.get("at_work"), c_on_risked: m.get("return_on_risked"),
            c_win: m.get("win_rate"), c_trades: len(trades),
        })
    if curves:
        data = pd.concat(curves, ignore_index=True)
        chart = alt.Chart(data).mark_line().encode(
            x=alt.X("timestamp:T", title=None, axis=layout.time_axis()),
            y=alt.Y("equity:Q", title=t("variants.equity_axis"), scale=alt.Scale(zero=False)),
            color=alt.Color("wariant:N", title=c_variant, legend=layout.legend(c_variant)),
        ).properties(height=layout.chart_height(320))
        st.altair_chart(chart, width="stretch")
    metrics_df = pd.DataFrame(metric_rows)
    if layout.is_mobile():
        # Eight columns do not fit; equity, Sharpe and drawdown are what the A/B
        # comparison is actually for.
        layout.cards(metrics_df, c_variant, [c_equity, c_sharpe, c_dd, c_trades],
                     {c_equity: ",.2f", c_sharpe: ".2f", c_dd: ".2f", c_trades: ".0f"})
    else:
        st.dataframe(metrics_df.style.format(
            {c_equity: "{:,.2f}", c_sharpe: "{:.2f}", c_dd: "{:.2f}",
             c_at_work: "{:.0f}", c_on_risked: "{:+.2f}",
             c_win: "{:.0f}"}, na_rep="—"), width="stretch", hide_index=True)


def tab_experiments() -> None:
    st.subheader(t("experiments.title"))
    st.caption(t("experiments.help"))
    exps = load_experiments(runtime)
    if not exps:
        st.caption(t("experiments.empty"))
        return
    df = pd.json_normalize(exps).sort_values("timestamp", ascending=False)
    cols = [c for c in ["timestamp", "kind", "timeframe", "window_days", "pairs",
                        "mean_return_pct", "benchmark_return_pct", "total_trades", "report"]
            if c in df]
    if layout.is_mobile():
        layout.cards(df[cols], "kind",
                     ["timestamp", "mean_return_pct", "benchmark_return_pct", "total_trades"],
                     {"mean_return_pct": "+.2f", "benchmark_return_pct": "+.2f",
                      "total_trades": ".0f"},
                     color_by="mean_return_pct")
    else:
        st.dataframe(df[cols], width="stretch", hide_index=True)


def tab_health(books: dict[str, Path]) -> None:
    st.subheader(t("health.title"))
    now = datetime.now(UTC)
    for name, bdir in books.items():
        state = load_state(bdir)
        if not state:
            continue
        tf = state.get("timeframe", cfg.exchange.timeframe)
        bar_ms = TIMEFRAME_MS.get(tf, 0)
        stale = []
        for sym, ts in state.get("last_candle_ts", {}).items():
            # ts is the last closed candle's OPEN time; it finalized bar_ms later.
            # Overdue only once a whole extra bar past that close has elapsed.
            overdue_ms = (now - datetime.fromisoformat(ts)).total_seconds() * 1000 - bar_ms
            if overdue_ms > bar_ms + 15 * 60_000:
                stale.append(sym)
        cols = st.columns(4)
        cols[0].metric(t("health.variant", name=name),
                       t("health.ok") if not stale else t("health.attention"))
        cols[1].metric(t("metric.kill_switch"),
                       t("health.active") if state.get("kill_switch") else t("health.inactive"),
                       help=humanize.glossary("kill_switch"))
        cols[2].metric(t("metric.drawdown"), f"{state.get('drawdown_pct', 0):.2f}%",
                       help=humanize.glossary("max_drawdown"))
        cols[3].metric(t("health.last_state"),
                       humanize._fmt_time(state.get("updated_at"), DISPLAY_TZ))
        if stale:
            st.warning(t("health.stale_pairs", name=name, pairs=", ".join(stale)))

    status_path = runtime / "refresh_status.json"
    if status_path.exists():
        rs = json.loads(status_path.read_text())
        st.caption(t("health.refresher", status=rs.get("status", "?"),
                     when=rs.get("timestamp", "?"), detail=rs.get("detail", "")))

    st.subheader(t("health.recent_alerts"))
    frames = [journals.load_jsonl(runtime / "alerts.jsonl")]
    frames += [journals.load_jsonl(bdir / "alerts.jsonl") for bdir in books.values()]
    alerts = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(
        len(f) for f in frames) else pd.DataFrame()
    if len(alerts):
        alerts = alerts.drop_duplicates().sort_values("timestamp", ascending=False).head(30)
        alert_cols = [c for c in ["timestamp", "kind", "message", "variant"] if c in alerts]
        if layout.is_mobile():
            # Alerts already carry a whole sentence; the timeline reads better than a grid.
            for rec in journals.records(alerts.head(layout.max_cards() * 2)):
                e = humanize.event_line(rec, DISPLAY_TZ)
                st.markdown(f"{e['emoji']} &nbsp;`{e['time']}` &nbsp; {e['text']}")
        else:
            st.dataframe(alerts[alert_cols], width="stretch", hide_index=True)
    else:
        st.caption(t("health.no_alerts"))


def render_crypto() -> None:
    books = discover_books()
    if not books:
        st.info(t("crypto.no_data"))
        return

    # pick the 'primary' book to show on the main screen
    names = list(books)
    primary = cfg.primary_variant if cfg.primary_variant in books else names[0]
    book_dir = books[primary]
    state = load_state(book_dir) or {}
    equity_df = journals.load_jsonl(book_dir / "equity.jsonl")
    trades = journals.load_jsonl(book_dir / "trades.jsonl")
    alerts = journals.load_jsonl(book_dir / "alerts.jsonl")

    if len(names) > 1:
        st.caption(t("crypto.your_book", book=primary))
    render_beginner(state, equity_df, trades, alerts)

    # Desktop tabs switch client-side, but the mobile segmented control triggers a
    # rerun — which would slam the expander shut on every panel change. Reading the
    # control's stored value *before* the expander renders keeps it open once used.
    details_key = "crypto_details_panel"
    with st.expander(t("crypto.details"),
                     expanded=bool(st.session_state.get(details_key))):
        sel = st.selectbox(t("crypto.book_picker"), names,
                           index=names.index(primary)) if len(names) > 1 else primary
        d = books[sel]
        s_state = load_state(d) or {}
        s_eq = journals.load_jsonl(d / "equity.jsonl")
        s_tr = journals.load_jsonl(d / "trades.jsonl")
        tab_metrics(s_eq, s_tr, s_state)
        # Keyed by code, labelled by translation: the mobile control stores its choice
        # in session state, and a stored label would stop matching after a switch.
        panels = {
            "analytics": lambda: tab_analytics(s_tr),
            "model": lambda: tab_model(s_state),
            "variants": lambda: tab_variants(books),
            "experiments": tab_experiments,
            "health": lambda: tab_health(books),
        }
        if layout.is_mobile():
            # Five tabs in a row scroll off a 390px screen with no hint that more
            # exist; a segmented control wraps onto as many lines as it needs.
            choice = st.segmented_control(t("crypto.details"), list(panels),
                                          default="analytics",
                                          format_func=lambda c: t(f"panel.{c}"),
                                          label_visibility="collapsed", key=details_key)
            panels[choice or "analytics"]()
        else:
            labels = [t(f"panel.{code}") for code in panels]
            for tab, render_panel in zip(st.tabs(labels), panels.values(), strict=True):
                with tab:
                    render_panel()


# ---------- app ----------

# Both selectors live OUTSIDE the auto-refreshing fragment: switching either must
# trigger a full rerun (a widget inside a run_every fragment would drop the change).
def _pick_language() -> None:
    """Seed the session's language, then let the viewer change it.

    `?lang=` wins on the first run of a session so a link can carry the choice; after
    that the widget owns the value. `display_language` from config.yaml is the
    fallback, which is also what the engine and the printed reports use.
    """
    if i18n.SESSION_KEY not in st.session_state:
        st.session_state[i18n.SESSION_KEY] = (
            i18n.normalize(st.query_params.get("lang"))
            or i18n.normalize(cfg.display_language)
            or i18n.DEFAULT_LANG)
    st.segmented_control(
        "Language", list(i18n.LANGS), key=i18n.SESSION_KEY,
        format_func=lambda code: t(f"lang.{code}"), label_visibility="collapsed")


_head = st.columns([4, 1])
with _head[1]:
    _pick_language()
with _head[0]:
    st.title("TraDaemon 👹💰")
    # Version here rather than per module: a deploy rebuilds the image from git, and this
    # is the only way to tell from the browser whether the running container is the fresh one.
    st.caption(f"{t('app.version')} {__version__} · {t('app.educational')}")

MODULES = ["crypto", "portfolio", "research", "settings"]
# segmented_control wraps onto several lines when the labels do not fit, where a
# horizontal radio would overflow the viewport at 390px.
_module = st.segmented_control(t("module.label"), MODULES, default=MODULES[0],
                               format_func=lambda code: t(f"module.{code}"),
                               label_visibility="collapsed") or MODULES[0]


@st.fragment(run_every=layout.refresh_interval())
def render_live() -> None:
    """The two modules that hold positions — auto-refreshed."""
    if _module == "portfolio":
        from trademon.dashboard import portfolio_view
        portfolio_view.render()
    else:
        render_crypto()


def render() -> None:
    if _module == "settings":
        # Writing config must never sit inside a run_every fragment: an auto-rerun
        # mid-edit would discard whatever is typed into the form.
        from trademon.dashboard import config_view
        config_view.render()
    elif _module == "research":
        # Studies produce a report, not a position: nothing here changes every 15s,
        # and auto-refresh would fight the buttons and the date input.
        from trademon.dashboard import research_view
        research_view.render()
    else:
        render_live()


render()
