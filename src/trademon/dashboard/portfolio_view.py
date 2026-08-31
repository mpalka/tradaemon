"""Portfolio-manager view for the dashboard (module 2).

Beginner screen (plain Polish) + technical tabs behind an expander, mirroring the
crypto view. Reads the portfolio book's runtime files (runtime/portfolio/<name>/)
and reconstructs the buy & hold benchmark from the stored daily price panel.
Self-contained on purpose — it must not import app.py (which auto-runs on import).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from trademon.dashboard import humanize, journals, layout, price_view
from trademon.i18n import t
from trademon.portfolio.config import PortfolioConfig, load_portfolio_config
from trademon.portfolio.data import load_panel

ACCENT, BH_COLOR = "#2a78d6", "#999999"
RANGES = {"1y": 365, "5y": 365 * 5, "all": None}
FRESH_DAYS = 4  # daily data over weekends/holidays — allow a few days before "stale"


def _load_state(book_dir: Path) -> dict | None:
    path = book_dir / "state.json"
    return json.loads(path.read_text()) if path.exists() else None


def discover_books(pcfg: PortfolioConfig) -> dict[str, Path]:
    root = pcfg.runtime_dir
    books: dict[str, Path] = {}
    if root.exists():
        for sub in sorted(p for p in root.glob("*/") if p.is_dir()):
            if (sub / "state.json").exists():
                books[sub.name] = sub
    return books


def _equity_series(equity_df: pd.DataFrame) -> pd.DataFrame:
    if equity_df.empty:
        return pd.DataFrame(columns=["timestamp", "equity"])
    df = equity_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.groupby("timestamp", as_index=False)["equity"].last()


def benchmark_curve(pcfg: PortfolioConfig) -> pd.DataFrame:
    """Weighted buy & hold of the target basket from the stored daily price panel."""
    panel = load_panel(pcfg.paths.data_dir, pcfg.symbols)
    if panel.empty:
        return pd.DataFrame()
    weights = pd.Series(pcfg.base_weights)
    norm = panel.div(panel.iloc[0])
    bench = (norm * weights).sum(axis=1) * pcfg.initial_capital
    bench.index = pd.to_datetime(bench.index)
    return pd.DataFrame({"timestamp": bench.index, "equity": bench.values})


def _window(df: pd.DataFrame, days: int | None) -> pd.DataFrame:
    if df.empty or days is None or "timestamp" not in df:
        return df
    ts = pd.to_datetime(df["timestamp"])
    return df[ts >= ts.max() - pd.Timedelta(days=days)]


def _chart(strat: pd.DataFrame, bench: pd.DataFrame) -> alt.Chart:
    s_bot, s_bh = t("chart.series.bot"), t("portfolio.series.bh")
    layers = [strat.assign(seria=s_bot)[["timestamp", "equity", "seria"]]]
    if len(bench):
        layers.append(bench.assign(seria="Kup i trzymaj")[["timestamp", "equity", "seria"]])
    data = pd.concat(layers, ignore_index=True)
    return alt.Chart(data).mark_line().encode(
        x=alt.X("timestamp:T", title=None,
                axis=alt.Axis(format="%m.%Y", grid=False,
                              tickCount=4 if layout.is_mobile() else 6)),
        y=alt.Y("equity:Q", title=t("chart.value"), scale=alt.Scale(zero=False, nice=False)),
        color=alt.Color("seria:N", title=None, legend=layout.legend(),
                        scale=alt.Scale(domain=[s_bot, s_bh],
                                        range=[ACCENT, BH_COLOR])),
    ).properties(height=layout.chart_height())


def _status(state: dict) -> dict:
    tss = state.get("last_candle_ts", {})
    if not tss:
        return {"emoji": "🔴", "text": t("portfolio.status.no_data")}
    latest = max(tss.values())
    try:
        age_days = (datetime.now(UTC) - datetime.fromisoformat(latest)).days
    except ValueError:
        return {"emoji": "🔴", "text": "nieznany czas ostatnich danych"}
    when = str(latest)[:10]
    if age_days <= FRESH_DAYS:
        return {"emoji": "🟢", "text": t("portfolio.status.running", when=when)}
    return {"emoji": "🔴", "text": f"nie odpowiada — ostatnie dane z {when}"}


# ---------- beginner screen ----------

def _render_beginner(pcfg: PortfolioConfig, state: dict, equity_df: pd.DataFrame,
                     alerts: pd.DataFrame, trades: pd.DataFrame) -> None:
    initial = pcfg.initial_capital
    eq = float(state.get("equity", initial))
    cash = float(state.get("cash", initial))
    invested = max(eq - cash, 0.0)
    change = (eq / initial - 1.0) * 100.0

    top = st.columns([2, 3])
    with top[0]:
        st.metric("Ile masz (wirtualne $)", humanize.money2(eq), f"{change:+.2f}% od startu")
        # Unlike the scalper, this module is in the market with everything it has —
        # so its result and its "kup i trzymaj" benchmark compare like with like.
        at_work = (invested / eq * 100.0) if eq else 0.0
        st.caption(humanize.md(t("portfolio.split", cash=humanize.money2(cash),
                                 invested=humanize.money2(invested),
                                 pct=f"{at_work:.0f}")))
    with top[1]:
        stt = _status(state)
        st.markdown(f"### {stt['emoji']} Status bota")
        st.markdown(stt["text"])
        last_reb = state.get("last_rebalance")
        if last_reb:
            st.caption(f"Ostatni rebalans: {str(last_reb)[:10]}")

    st.divider()
    st.subheader(t("home.how_it_went"))
    rng = st.radio(t("home.range"), list(RANGES), horizontal=True,
                   format_func=lambda code: t(f"portfolio.range.{code}"),
                   label_visibility="collapsed")
    strat = _window(_equity_series(equity_df), RANGES[rng])
    if len(strat):
        bench = _window(benchmark_curve(pcfg), RANGES[rng])
        if len(bench):  # rebase benchmark to the strategy's value at the window start
            bench = bench.reset_index(drop=True)
            scale = strat["equity"].iloc[0] / bench["equity"].iloc[0]
            bench = bench.assign(equity=bench["equity"] * scale)
        st.altair_chart(_chart(strat, bench), width="stretch")
        st.caption(t("portfolio.chart_explainer"))
    else:
        st.info(t("portfolio.not_enough_data"))

    st.divider()
    # Same click-to-see-the-price interaction as the crypto screen; the prices come
    # from the daily Yahoo files instead of the crypto candles.
    st.subheader("Co bot teraz trzyma")
    price_view.styles()
    holdings = state.get("holdings", {})
    last_close = state.get("last_close", {})
    weights = state.get("weights", {})
    targets = state.get("target_weights", pcfg.base_weights)
    active = {s: q for s, q in holdings.items() if q and last_close.get(s)}

    # Scoped to this render, as on the crypto screen: the holdings and the event
    # journal below name the same few tickers, each of which needs a tooltip.
    prices_for = price_view.memoized(
        lambda sym: price_view.portfolio_prices(pcfg.paths.data_dir, sym))
    tooltip = price_view.tooltips(prices_for)

    if not active:
        st.info(t("portfolio.no_allocation_yet"))
    else:
        st.caption(t("home.holdings.click"))
        cols = st.columns(min(len(active), 3))
        for i, (sym, qty) in enumerate(active.items()):
            value = qty * last_close.get(sym, 0.0)
            card = humanize.holding_card(sym, value, weights.get(sym, 0.0),
                                         targets.get(sym, 0.0))
            with cols[i % len(cols)]:
                price_view.preview_button(f"**{card['emoji']} {card['title']}**", sym,
                                          "port_pos", key=f"port_pos_{sym}",
                                          tooltip=tooltip(sym))
                st.markdown(card["detail"])
        price_view.render("port_pos", prices_for, trades)

    st.divider()
    st.subheader(t("home.events"))
    if len(alerts):
        rows = journals.records(alerts.sort_values("timestamp", ascending=False).head(15))
        for n, rec in enumerate(rows):
            e = humanize.event_line(rec)
            sym = rec.get("symbol")
            if sym:  # basket-level rebalances name no instrument; those stay text
                key = f"port_ev_{n}_{sym}"
                price_view.preview_button(f"{e['emoji']} `{e['time']}` {e['text']}", sym,
                                          "port_ev", key=key,
                                          at=rec.get("timestamp"), tooltip=tooltip(sym))
                price_view.render("port_ev", prices_for, trades, item=key)
            else:
                st.markdown(f"{e['emoji']} &nbsp;`{e['time']}` &nbsp; {e['text']}")
    else:
        st.caption(t("home.events.empty"))


# ---------- detail tabs ----------

def _tab_allocation(state: dict, pcfg: PortfolioConfig) -> None:
    weights = state.get("weights", {})
    targets = state.get("target_weights", pcfg.base_weights)
    now_label, target_label = t("portfolio.now"), t("portfolio.target")
    rows = []
    for s in pcfg.symbols:
        rows.append({"asset": s, "kind": now_label, "weight": weights.get(s, 0.0) * 100})
        rows.append({"asset": s, "kind": target_label, "weight": targets.get(s, 0.0) * 100})
    df = pd.DataFrame(rows)
    st.subheader(t("portfolio.weight_vs_target"))
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("weight:Q", title=t("portfolio.pct_of_portfolio")),
        y=alt.Y("asset:N", title=None),
        color=alt.Color("kind:N", title=None,
                        scale=alt.Scale(domain=[now_label, target_label],
                                        range=[ACCENT, BH_COLOR])),
        yOffset="kind:N",
    ).properties(height=(40 if layout.is_mobile() else 60) + 40 * len(pcfg.symbols))
    st.altair_chart(chart, width="stretch")
    drift = {s: (weights.get(s, 0.0) - targets.get(s, 0.0)) * 100 for s in pcfg.symbols}
    worst = max(drift.values(), key=abs, default=0.0) if drift else 0.0
    st.caption(t("portfolio.worst_drift", drift=f"{worst:+.1f}",
                 threshold=f"{pcfg.rebalance.drift_threshold_pct:.0f}",
                 days=pcfg.rebalance.cadence_days))


def _tab_rebalances(trades: pd.DataFrame) -> None:
    st.subheader(t("portfolio.rebalance_history"))
    if not len(trades):
        st.caption(t("analytics.no_trades"))
        return
    df = trades.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d")
    cols = [c for c in ["timestamp", "symbol", "side", "qty", "price", "value", "fee", "kind"]
            if c in df]
    df = df[cols].sort_values("timestamp", ascending=False)
    if layout.is_mobile():
        layout.cards(df, "symbol", ["timestamp", "side", "value"],
                     {"value": ",.2f"})
    else:
        st.dataframe(df, width="stretch", hide_index=True)
    st.caption(humanize.md(t("portfolio.fees_total",
                             fees=humanize.money2(df["fee"].sum()), trades=len(df))))


def _tab_health(state: dict, alerts: pd.DataFrame) -> None:
    st.subheader(t("panel.health"))
    stt = _status(state)
    c = st.columns(3)
    c[0].metric(t("portfolio.data_status"),
                t("health.ok") if stt["emoji"] == "🟢" else t("health.attention"))
    c[1].metric(t("metric.drawdown"), f"{state.get('drawdown_pct', 0):.2f}%",
                help=humanize.glossary("max_drawdown"))
    c[2].metric(t("health.last_state"),
                str(state.get("updated_at", "?"))[:19].replace("T", " "))
    if len(alerts):
        recent = alerts.sort_values("timestamp", ascending=False).head(30)
        if layout.is_mobile():
            for rec in journals.records(recent.head(layout.max_cards() * 2)):
                e = humanize.event_line(rec)
                st.markdown(f"{e['emoji']} &nbsp;`{e['time']}` &nbsp; {e['text']}")
        else:
            st.dataframe(
                recent[[x for x in ["timestamp", "kind", "message"] if x in alerts]],
                width="stretch", hide_index=True)


# ---------- entry ----------

def render() -> None:
    try:
        pcfg = load_portfolio_config()
    except FileNotFoundError:
        st.info(t("portfolio.no_config"))
        return
    books = discover_books(pcfg)
    if not books:
        st.info(t("portfolio.no_data"))
        return

    names = list(books)
    primary = pcfg.book_name if pcfg.book_name in books else names[0]
    book_dir = books[primary]
    state = _load_state(book_dir) or {}
    equity_df = journals.load_jsonl(book_dir / "equity.jsonl")
    trades = journals.load_jsonl(book_dir / "trades.jsonl")
    alerts = journals.load_jsonl(book_dir / "alerts.jsonl")

    basket = ", ".join(f"{k} {v:.0%}" for k, v in pcfg.base_weights.items())
    st.caption(t("portfolio.basket", basket=basket, days=pcfg.rebalance.cadence_days,
                 threshold=f"{pcfg.rebalance.drift_threshold_pct:.0f}",
                 trend=t("cfg.bool.on" if pcfg.trend.enabled else "cfg.bool.off")))
    _render_beginner(pcfg, state, equity_df, alerts, trades)

    # See the note in app.py: the mobile segmented control reruns the script, so the
    # expander has to be told to stay open once a panel has been picked.
    details_key = "portfolio_details_panel"
    with st.expander(t("crypto.details"),
                     expanded=bool(st.session_state.get(details_key))):
        panels = {
            "allocation": lambda: _tab_allocation(state, pcfg),
            "rebalances": lambda: _tab_rebalances(trades),
            "health": lambda: _tab_health(state, alerts),
        }
        if layout.is_mobile():
            choice = st.segmented_control(t("crypto.details"), list(panels),
                                          default="allocation",
                                          format_func=lambda c: t(f"panel.{c}"),
                                          label_visibility="collapsed", key=details_key)
            panels[choice or "allocation"]()
        else:
            labels = [t(f"panel.{code}") for code in panels]
            for tab, render_panel in zip(st.tabs(labels), panels.values(),
                                         strict=True):
                with tab:
                    render_panel()
