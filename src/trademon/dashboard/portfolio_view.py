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
from trademon.portfolio.config import PortfolioConfig, load_portfolio_config
from trademon.portfolio.data import load_panel

ACCENT, BH_COLOR = "#2a78d6", "#999999"
RANGES = {"1 rok": 365, "5 lat": 365 * 5, "Całość": None}
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
    layers = [strat.assign(seria="Twój portfel")[["timestamp", "equity", "seria"]]]
    if len(bench):
        layers.append(bench.assign(seria="Kup i trzymaj")[["timestamp", "equity", "seria"]])
    data = pd.concat(layers, ignore_index=True)
    return alt.Chart(data).mark_line().encode(
        x=alt.X("timestamp:T", title=None,
                axis=alt.Axis(format="%m.%Y", grid=False,
                              tickCount=4 if layout.is_mobile() else 6)),
        y=alt.Y("equity:Q", title="Wartość ($)", scale=alt.Scale(zero=False, nice=False)),
        color=alt.Color("seria:N", title=None, legend=layout.legend(),
                        scale=alt.Scale(domain=["Twój portfel", "Kup i trzymaj"],
                                        range=[ACCENT, BH_COLOR])),
    ).properties(height=layout.chart_height())


def _status(state: dict) -> dict:
    tss = state.get("last_candle_ts", {})
    if not tss:
        return {"emoji": "🔴", "text": "brak danych — bot jeszcze nie ruszył"}
    latest = max(tss.values())
    try:
        age_days = (datetime.now(UTC) - datetime.fromisoformat(latest)).days
    except ValueError:
        return {"emoji": "🔴", "text": "nieznany czas ostatnich danych"}
    when = str(latest)[:10]
    if age_days <= FRESH_DAYS:
        return {"emoji": "🟢", "text": f"działa — dane z {when}"}
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
        st.caption(f"💵 gotówka: {humanize.money2(cash)} · 📊 w grze: "
                   f"{humanize.money2(invested)} (**{at_work:.0f}% pieniędzy**)  ·  "
                   f"tryb **paper** (ćwiczebny)")
    with top[1]:
        stt = _status(state)
        st.markdown(f"### {stt['emoji']} Status bota")
        st.markdown(stt["text"])
        last_reb = state.get("last_rebalance")
        if last_reb:
            st.caption(f"Ostatni rebalans: {str(last_reb)[:10]}")

    st.divider()
    st.subheader("Jak to szło")
    rng = st.radio("Zakres", list(RANGES), horizontal=True, label_visibility="collapsed")
    strat = _window(_equity_series(equity_df), RANGES[rng])
    if len(strat):
        bench = _window(benchmark_curve(pcfg), RANGES[rng])
        if len(bench):  # rebase benchmark to the strategy's value at the window start
            bench = bench.reset_index(drop=True)
            scale = strat["equity"].iloc[0] / bench["equity"].iloc[0]
            bench = bench.assign(equity=bench["equity"] * scale)
        st.altair_chart(_chart(strat, bench), width="stretch")
        st.caption("Niebieska nad szarą = rebalansowanie pomaga vs zwykłe trzymanie koszyka. "
                   "Tu porównanie jest uczciwe z natury: obie linie mają w rynku "
                   "wszystkie pieniądze.")
    else:
        st.info("Za mało danych na wykres — bot dopiero zaczyna.")

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

    def prices_for(sym: str) -> pd.DataFrame:
        return price_view.portfolio_prices(pcfg.paths.data_dir, sym)

    if not active:
        st.info("Jeszcze nic — bot czeka na pierwszą alokację.")
    else:
        st.caption("Kliknij instrument, aby zobaczyć jego kurs.")
        cols = st.columns(min(len(active), 3))
        for i, (sym, qty) in enumerate(active.items()):
            value = qty * last_close.get(sym, 0.0)
            card = humanize.holding_card(sym, value, weights.get(sym, 0.0),
                                         targets.get(sym, 0.0))
            with cols[i % len(cols)]:
                price_view.preview_button(f"**{card['emoji']} {card['title']}**", sym,
                                          "port_pos", key=f"port_pos_{sym}",
                                          prices=prices_for(sym))
                st.markdown(card["detail"])
        price_view.render("port_pos", prices_for, trades)

    st.divider()
    st.subheader("Dziennik zdarzeń")
    if len(alerts):
        rows = alerts.sort_values("timestamp", ascending=False).head(15).to_dict("records")
        for n, rec in enumerate(rows):
            e = humanize.event_line(rec)
            sym = rec.get("symbol")
            if sym:  # basket-level rebalances name no instrument; those stay text
                key = f"port_ev_{n}_{sym}"
                price_view.preview_button(f"{e['emoji']} `{e['time']}` {e['text']}", sym,
                                          "port_ev", key=key,
                                          at=rec.get("timestamp"), prices=prices_for(sym))
                price_view.render("port_ev", prices_for, trades, item=key)
            else:
                st.markdown(f"{e['emoji']} &nbsp;`{e['time']}` &nbsp; {e['text']}")
    else:
        st.caption("Jeszcze nic się nie wydarzyło.")


# ---------- detail tabs ----------

def _tab_allocation(state: dict, pcfg: PortfolioConfig) -> None:
    weights = state.get("weights", {})
    targets = state.get("target_weights", pcfg.base_weights)
    rows = []
    for s in pcfg.symbols:
        rows.append({"Aktywo": s, "typ": "teraz", "waga": weights.get(s, 0.0) * 100})
        rows.append({"Aktywo": s, "typ": "cel", "waga": targets.get(s, 0.0) * 100})
    df = pd.DataFrame(rows)
    st.subheader("Waga teraz vs cel")
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("waga:Q", title="% portfela"),
        y=alt.Y("Aktywo:N", title=None),
        color=alt.Color("typ:N", title=None,
                        scale=alt.Scale(domain=["teraz", "cel"], range=[ACCENT, BH_COLOR])),
        yOffset="typ:N",
    ).properties(height=(40 if layout.is_mobile() else 60) + 40 * len(pcfg.symbols))
    st.altair_chart(chart, width="stretch")
    drift = {s: (weights.get(s, 0.0) - targets.get(s, 0.0)) * 100 for s in pcfg.symbols}
    worst = max(drift.values(), key=abs, default=0.0) if drift else 0.0
    st.caption(f"Największe odchylenie od planu (drift): {worst:+.1f} pkt proc. "
               f"(rebalans przy ≥ {pcfg.rebalance.drift_threshold_pct:.0f} pkt "
               f"lub co {pcfg.rebalance.cadence_days} dni).")


def _tab_rebalances(trades: pd.DataFrame) -> None:
    st.subheader("Historia rebalansów")
    if not len(trades):
        st.caption("Jeszcze żadnych transakcji.")
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
    st.caption(f"Łącznie prowizji: {df['fee'].sum():.2f} $  ·  transakcji: {len(df)}")


def _tab_health(state: dict, alerts: pd.DataFrame) -> None:
    st.subheader("Zdrowie")
    stt = _status(state)
    c = st.columns(3)
    c[0].metric("Status danych", "OK" if stt["emoji"] == "🟢" else "UWAGA")
    c[1].metric("Drawdown", f"{state.get('drawdown_pct', 0):.2f}%",
                help=humanize.GLOSSARY["Max drawdown"])
    c[2].metric("Ostatni stan", str(state.get("updated_at", "?"))[:19].replace("T", " "))
    if len(alerts):
        recent = alerts.sort_values("timestamp", ascending=False).head(30)
        if layout.is_mobile():
            for rec in recent.head(layout.max_cards() * 2).to_dict("records"):
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
        st.info("Brak `config/portfolio.yaml` — moduł portfela nie jest skonfigurowany.")
        return
    books = discover_books(pcfg)
    if not books:
        st.info("Brak danych portfela — uruchom silnik: `python -m trademon.portfolio`")
        return

    names = list(books)
    primary = pcfg.book_name if pcfg.book_name in books else names[0]
    book_dir = books[primary]
    state = _load_state(book_dir) or {}
    equity_df = journals.load_jsonl(book_dir / "equity.jsonl")
    trades = journals.load_jsonl(book_dir / "trades.jsonl")
    alerts = journals.load_jsonl(book_dir / "alerts.jsonl")

    basket = ", ".join(f"{k} {v:.0%}" for k, v in pcfg.base_weights.items())
    st.caption(f"Koszyk: **{basket}** · rebalans co {pcfg.rebalance.cadence_days} dni "
               f"lub przy drift ≥ {pcfg.rebalance.drift_threshold_pct:.0f} pkt · "
               f"filtr trendu: {'włączony' if pcfg.trend.enabled else 'wyłączony'}")
    _render_beginner(pcfg, state, equity_df, alerts, trades)

    # See the note in app.py: the mobile segmented control reruns the script, so the
    # expander has to be told to stay open once a panel has been picked.
    details_key = "portfolio_details_panel"
    with st.expander("🔬 Szczegóły dla dociekliwych",
                     expanded=bool(st.session_state.get(details_key))):
        panels = {
            "Alokacja": lambda: _tab_allocation(state, pcfg),
            "Rebalanse": lambda: _tab_rebalances(trades),
            "Zdrowie": lambda: _tab_health(state, alerts),
        }
        if layout.is_mobile():
            choice = st.segmented_control("Szczegóły", list(panels), default="Alokacja",
                                          label_visibility="collapsed", key=details_key)
            panels[choice or "Alokacja"]()
        else:
            for tab, render_panel in zip(st.tabs(list(panels)), panels.values(),
                                         strict=True):
                with tab:
                    render_panel()
