"""Trademon dashboard — read-only lab view over the engine's runtime files.

Two modules share this dashboard: the crypto scalper and the portfolio manager.
Each opens on a **beginner screen** (plain Polish, no jargon) with the technical
tabs tucked behind "Szczegóły dla dociekliwych". The engine is the only writer;
this only reads state.json / *.jsonl. Run: streamlit run src/trademon/dashboard/app.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from trademon.backtest.metrics import max_drawdown, periods_per_year, sharpe_ratio
from trademon.config import load_config
from trademon.dashboard import humanize
from trademon.data.storage import TIMEFRAME_MS
from trademon.research.log import load_experiments

st.set_page_config(page_title="Trademon", page_icon="chart_with_upwards_trend", layout="wide")

cfg = load_config()
runtime = cfg.paths.runtime_dir
ACCENT, BH_COLOR, GOOD, BAD = "#2a78d6", "#999999", "#0ca30c", "#d03b3b"
RANGES = {"7 dni": 7, "30 dni": 30, "Całość": None}


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


def load_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.DataFrame([json.loads(x) for x in path.read_text().splitlines() if x.strip()])


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


def buy_hold_curve(equity_df: pd.DataFrame, initial: float) -> pd.DataFrame:
    """Equal-weight buy&hold of all pairs from per-bar close prices logged
    alongside equity — the benchmark the strategy must beat."""
    if equity_df.empty or "close" not in equity_df:
        return pd.DataFrame()
    df = equity_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    wide = df.pivot_table(index="timestamp", columns="symbol", values="close").ffill()
    if wide.empty:
        return pd.DataFrame()
    bh = initial * wide.div(wide.iloc[0]).mean(axis=1)
    return pd.DataFrame({"timestamp": bh.index, "equity": bh.values})


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


def equity_chart(strat: pd.DataFrame, bh: pd.DataFrame) -> alt.Chart:
    layers = [strat.assign(seria="Twój portfel")[["timestamp", "equity", "seria"]]]
    if len(bh):
        layers.append(bh.assign(seria="Kup i trzymaj")[["timestamp", "equity", "seria"]])
    data = pd.concat(layers, ignore_index=True)
    return (
        alt.Chart(data).mark_line().encode(
            x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%d.%m", grid=False)),
            y=alt.Y("equity:Q", title="Wartość ($)", scale=alt.Scale(zero=False, nice=False)),
            color=alt.Color("seria:N", title=None,
                            scale=alt.Scale(domain=["Twój portfel", "Kup i trzymaj"],
                                            range=[ACCENT, BH_COLOR])),
        ).properties(height=300)
    )


# ---------- beginner main screen (crypto) ----------

def render_beginner(state: dict, equity_df: pd.DataFrame, trades: pd.DataFrame,
                    alerts: pd.DataFrame) -> None:
    initial = cfg.paper.initial_capital
    eq = float(state.get("equity", initial))
    cash = float(state.get("cash", initial))
    invested = max(eq - cash, 0.0)
    change = (eq / initial - 1.0) * 100.0

    # 1) Ile masz
    top = st.columns([2, 3])
    with top[0]:
        st.metric("Ile masz (wirtualne $)", humanize.money2(eq), f"{change:+.2f}% od startu")
        st.caption(f"💵 wolne: {humanize.money2(cash)} · 📈 w pozycjach: "
                   f"{humanize.money2(invested)}  ·  tryb **paper** (ćwiczebny, nie prawdziwe pieniądze)")
    # 2) status bota
    with top[1]:
        tf = state.get("timeframe", cfg.exchange.timeframe)
        status = humanize.bot_status(state.get("last_candle_ts", {}),
                                     TIMEFRAME_MS.get(tf, 0), datetime.now(UTC))
        st.markdown(f"### {status['emoji']} Status bota")
        st.markdown(status["text"])
        if state.get("kill_switch"):
            st.warning("🛑 Bezpiecznik dzienny włączony — bot nie otwiera teraz nowych pozycji.")

    st.divider()

    # 3) Jak to szło
    st.subheader("Jak to szło")
    rng_label = st.radio("Zakres", list(RANGES), horizontal=True, label_visibility="collapsed")
    win = window_df(equity_df, RANGES[rng_label])
    strat_eq = book_equity_series(win)
    if len(strat_eq):
        bh = buy_hold_curve(win, initial)
        if len(bh):  # rebase benchmark to the strategy's value at the window start
            scale = strat_eq["equity"].iloc[0] / initial
            bh = bh.assign(equity=bh["equity"] * scale)
        st.altair_chart(equity_chart(strat_eq, bh), use_container_width=True)
        st.caption("Niebieska linia nad szarą = bot radzi sobie lepiej niż zwykłe trzymanie.")
    else:
        st.info("Za mało danych na wykres — bot dopiero zaczyna zbierać historię.")

    st.divider()

    # 4) Co bot teraz trzyma
    st.subheader("Co bot teraz trzyma")
    positions = state.get("positions", {})
    last_close = state.get("last_close", {})
    if not positions:
        st.info("Nic — bot czeka na okazję. 🕊️")
    else:
        cols = st.columns(min(len(positions), 3))
        for i, (sym, pos) in enumerate(positions.items()):
            card = humanize.position_card(pos, last_close.get(sym))
            with cols[i % len(cols)]:
                st.markdown(f"**{card['emoji']} {card['title']}**")
                tone = "green" if card["pnl"] > 0 else ("red" if card["pnl"] < 0 else "gray")
                st.markdown(f":{tone}[{card['detail']}]")

    st.divider()

    # 5) Dziennik zdarzeń
    st.subheader("Dziennik zdarzeń")
    if len(alerts):
        rows = alerts.sort_values("timestamp", ascending=False).head(15).to_dict("records")
        for rec in rows:
            e = humanize.event_line(rec)
            st.markdown(f"{e['emoji']} &nbsp;`{e['time']}` &nbsp; {e['text']}")
    else:
        st.caption("Jeszcze nic się nie wydarzyło.")


# ---------- detail tabs (unchanged logic, now behind an expander) ----------

def tab_metrics(equity_df: pd.DataFrame, trades: pd.DataFrame, state: dict) -> None:
    m = live_metrics(equity_df, trades, state.get("timeframe", cfg.exchange.timeframe))
    c = st.columns(4)
    c[0].metric("Sharpe", f"{m.get('sharpe', 0):.2f}", help=humanize.GLOSSARY["Sharpe"])
    c[1].metric("Max drawdown", f"{m.get('max_dd', 0):.2f}%",
                help=humanize.GLOSSARY["Max drawdown"])
    pf = m.get("profit_factor")
    c[2].metric("Profit factor", f"{pf:.2f}" if pf not in (None, float("inf")) else "—",
                help=humanize.GLOSSARY["Profit factor"])
    c[3].metric("Win rate", f"{m['win_rate']:.0f}%" if "win_rate" in m else "—",
                help=humanize.GLOSSARY["Win rate"])


def tab_analytics(trades: pd.DataFrame) -> None:
    if not len(trades):
        st.caption("Jeszcze żadnych transakcji.")
        return
    st.subheader("Wynik per para")
    per = trades.groupby("symbol").agg(
        transakcje=("pnl", "count"),
        win_rate=("pnl", lambda x: (x > 0).mean() * 100),
        pnl_netto=("pnl", "sum"),
        prowizje=("fees", "sum"),
    ).reset_index().sort_values("pnl_netto", ascending=False)
    st.dataframe(
        per.style.map(pnl_color, subset=["pnl_netto"]).format(
            {"win_rate": "{:.0f}%", "pnl_netto": "{:+.2f}", "prowizje": "{:.2f}"}),
        use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Rozkład wyników transakcji")
        hist = alt.Chart(trades).mark_bar().encode(
            x=alt.X("pnl:Q", bin=alt.Bin(maxbins=30), title="PnL (USDT)"),
            y=alt.Y("count()", title="Liczba"),
            color=alt.condition(alt.datum.pnl > 0, alt.value(GOOD), alt.value(BAD)),
        ).properties(height=240)
        st.altair_chart(hist, use_container_width=True)
    with col2:
        st.subheader("Powody wyjścia")
        if "exit_reason" in trades:
            reasons = trades["exit_reason"].value_counts().reset_index()
            reasons.columns = ["powód", "liczba"]
            bar = alt.Chart(reasons).mark_bar(color=ACCENT).encode(
                x=alt.X("liczba:Q", title="Liczba"),
                y=alt.Y("powód:N", title=None, sort="-x"),
            ).properties(height=240)
            st.altair_chart(bar, use_container_width=True)


def tab_model(state: dict) -> None:
    st.subheader("Dlaczego bot (nie) handluje")
    st.caption("Prawdopodobieństwo modelu i decyzja dla ostatniej świecy każdej pary. "
               "Wejście, gdy prawdopodobieństwo ≥ próg.")
    signals = state.get("signals", {})
    if not signals:
        st.caption("Brak sygnałów — silnik jeszcze nie policzył prawdopodobieństw "
                   "(do końca okna rozgrzewki).")
        return
    rows = [{
        "Para": sym, "p(long)": sig.get("p_long"), "Próg": sig.get("threshold"),
        "Decyzja": humanize.REASON_PL.get(sig.get("reason", ""), sig.get("reason", "")),
    } for sym, sig in signals.items()]
    df = pd.DataFrame(rows).sort_values("p(long)", ascending=False, na_position="last")
    st.dataframe(df.style.format({"p(long)": "{:.3f}", "Próg": "{:.2f}"}, na_rep="—"),
                 use_container_width=True, hide_index=True)


def tab_variants(books: dict[str, Path]) -> None:
    st.subheader("Porównanie wariantów na żywo")
    if len(books) < 2:
        st.info("Brak wariantów A/B. Dodaj sekcję `variants:` w config.yaml, aby kilka "
                "konfiguracji handlowało równolegle na tych samych danych.")
    initial = cfg.paper.initial_capital
    curves, metric_rows = [], []
    for name, bdir in books.items():
        state = load_state(bdir) or {}
        eq_df = load_jsonl(bdir / "equity.jsonl")
        trades = load_jsonl(bdir / "trades.jsonl")
        s = book_equity_series(eq_df)
        if len(s):
            curves.append(s.assign(wariant=name))
        m = live_metrics(eq_df, trades, state.get("timeframe", cfg.exchange.timeframe))
        metric_rows.append({
            "Wariant": name, "Kapitał": state.get("equity", initial),
            "Sharpe": m.get("sharpe"), "Max DD %": m.get("max_dd"),
            "Win rate %": m.get("win_rate"), "Transakcje": len(trades),
        })
    if curves:
        data = pd.concat(curves, ignore_index=True)
        chart = alt.Chart(data).mark_line().encode(
            x=alt.X("timestamp:T", title=None),
            y=alt.Y("equity:Q", title="Kapitał (USDT)", scale=alt.Scale(zero=False)),
            color=alt.Color("wariant:N", title="Wariant"),
        ).properties(height=320)
        st.altair_chart(chart, use_container_width=True)
    st.dataframe(pd.DataFrame(metric_rows).style.format(
        {"Kapitał": "{:,.2f}", "Sharpe": "{:.2f}", "Max DD %": "{:.2f}",
         "Win rate %": "{:.0f}"}, na_rep="—"), use_container_width=True, hide_index=True)


def tab_experiments() -> None:
    st.subheader("Dziennik eksperymentów")
    st.caption("Każdy backtest/sweep zapisany raz — żeby nie liczyć wielokrotnie tego samego.")
    exps = load_experiments(runtime)
    if not exps:
        st.caption("Pusto. Uruchom `python scripts/backtest.py`, aby dodać wpis.")
        return
    df = pd.json_normalize(exps).sort_values("timestamp", ascending=False)
    cols = [c for c in ["timestamp", "kind", "timeframe", "window_days", "pairs",
                        "mean_return_pct", "benchmark_return_pct", "total_trades", "report"]
            if c in df]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


def tab_health(books: dict[str, Path]) -> None:
    st.subheader("Zdrowie systemu")
    now = datetime.now(UTC)
    for name, bdir in books.items():
        state = load_state(bdir)
        if not state:
            continue
        tf = state.get("timeframe", cfg.exchange.timeframe)
        bar_ms = TIMEFRAME_MS.get(tf, 0)
        stale = []
        for sym, ts in state.get("last_candle_ts", {}).items():
            age_ms = (now - datetime.fromisoformat(ts)).total_seconds() * 1000
            if age_ms > bar_ms * 1.5 + 15 * 60_000:
                stale.append(sym)
        cols = st.columns(4)
        cols[0].metric(f"Wariant: {name}", "OK" if not stale else "UWAGA")
        cols[1].metric("Kill-switch", "AKTYWNY" if state.get("kill_switch") else "nieaktywny",
                       help=humanize.GLOSSARY["Kill-switch"])
        cols[2].metric("Drawdown", f"{state.get('drawdown_pct', 0):.2f}%",
                       help=humanize.GLOSSARY["Max drawdown"])
        cols[3].metric("Ostatni stan",
                       str(state.get("updated_at", "?"))[:19].replace("T", " "))
        if stale:
            st.warning(f"[{name}] przeterminowane dane dla: {', '.join(stale)} "
                       f"(silnik może nie przetwarzać świec)")

    status_path = runtime / "refresh_status.json"
    if status_path.exists():
        rs = json.loads(status_path.read_text())
        st.caption(f"Refresher: {rs.get('status', '?')} @ {rs.get('timestamp', '?')} "
                   f"— {rs.get('detail', '')}")

    st.subheader("Ostatnie alerty")
    frames = [load_jsonl(runtime / "alerts.jsonl")]
    frames += [load_jsonl(bdir / "alerts.jsonl") for bdir in books.values()]
    alerts = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(
        len(f) for f in frames) else pd.DataFrame()
    if len(alerts):
        alerts = alerts.drop_duplicates().sort_values("timestamp", ascending=False).head(30)
        st.dataframe(alerts[[c for c in ["timestamp", "kind", "message", "variant"]
                             if c in alerts]], use_container_width=True, hide_index=True)
    else:
        st.caption("Brak alertów.")


def render_crypto() -> None:
    books = discover_books()
    if not books:
        st.info("Brak danych — uruchom silnik: `python -m trademon.engine`")
        return

    # pick the 'primary' book to show on the main screen
    names = list(books)
    primary = cfg.primary_variant if cfg.primary_variant in books else names[0]
    book_dir = books[primary]
    state = load_state(book_dir) or {}
    equity_df = load_jsonl(book_dir / "equity.jsonl")
    trades = load_jsonl(book_dir / "trades.jsonl")
    alerts = load_jsonl(book_dir / "alerts.jsonl")

    if len(names) > 1:
        st.caption(f"Twój portfel: **{primary}** (pozostałe warianty w Szczegółach)")
    render_beginner(state, equity_df, trades, alerts)

    with st.expander("🔬 Szczegóły dla dociekliwych"):
        sel = st.selectbox("Księga (wariant)", names,
                           index=names.index(primary)) if len(names) > 1 else primary
        d = books[sel]
        s_state = load_state(d) or {}
        s_eq = load_jsonl(d / "equity.jsonl")
        s_tr = load_jsonl(d / "trades.jsonl")
        tab_metrics(s_eq, s_tr, s_state)
        t = st.tabs(["Analityka", "Model", "Warianty", "Eksperymenty", "Zdrowie"])
        with t[0]:
            tab_analytics(s_tr)
        with t[1]:
            tab_model(s_state)
        with t[2]:
            tab_variants(books)
        with t[3]:
            tab_experiments()
        with t[4]:
            tab_health(books)


# ---------- app ----------

# The module selector lives OUTSIDE the auto-refreshing fragment: switching it must
# trigger a full rerun (a widget inside a run_every fragment would drop the change).
st.title("Trademon")
_module = st.radio("Moduł", ["Krypto-scalper", "Zarządca portfela"],
                   horizontal=True, label_visibility="collapsed")


@st.fragment(run_every="15s")
def render() -> None:
    if _module == "Zarządca portfela":
        from trademon.dashboard import portfolio_view
        portfolio_view.render()
    else:
        render_crypto()


render()
