"""TraDaemon dashboard — read-only lab view over the engine's runtime files.

Two modules share this dashboard: the crypto scalper and the portfolio manager.
Each opens on a **beginner screen** (plain Polish, no jargon) with the technical
tabs tucked behind "Szczegóły dla dociekliwych". The engine is the only writer;
this only reads state.json / *.jsonl. Run: streamlit run src/trademon/dashboard/app.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import altair as alt
import pandas as pd
import streamlit as st

from trademon import __version__, config_store
from trademon.backtest.metrics import (
    avg_exposure_pct,
    max_drawdown,
    periods_per_year,
    return_on_risked_pct,
    sharpe_ratio,
    time_in_market_pct,
)
from trademon.config import load_config
from trademon.dashboard import humanize, journals, layout, price_view
from trademon.data.storage import TIMEFRAME_MS
from trademon.research.log import load_experiments

st.set_page_config(page_title="TraDaemon", page_icon="👹💰", layout="wide")

cfg = load_config()
runtime = cfg.paths.runtime_dir
ACCENT, BH_COLOR, GOOD, BAD = "#2a78d6", "#c2c2c2", "#0ca30c", "#d03b3b"
BH_FAIR_COLOR = "#5a5a5a"   # the like-for-like benchmark, so it reads stronger than the all-in one
RANGES = {"7 dni": 7, "30 dni": 30, "Całość": None}

# Chart series labels. The bot plays with only a part of the account, so the all-in
# "buy & hold" is not a fair yardstick — both are drawn, the fair one more prominent.
# Keep these short and differing from the first word: the legend truncates, and two
# labels both starting "Kup i trzymaj…" render identically.
S_BOT = "Twój portfel"
S_BH_ALL = "Wszystko w rynku"
S_BH_FAIR = "Tyle w rynku co bot"

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


def buy_hold_curve(equity_df: pd.DataFrame, initial: float,
                   exposure: float = 1.0) -> pd.DataFrame:
    """Equal-weight buy&hold of all pairs from per-bar close prices logged
    alongside equity — the benchmark the strategy must beat.

    `exposure` is the share of the account put in the market (the rest sits in cash
    earning nothing). The default 1.0 is the all-in benchmark; passing the bot's own
    average exposure compares like with like — otherwise the bot "wins" every
    downturn simply by not having been there.
    """
    if equity_df.empty or "close" not in equity_df:
        return pd.DataFrame()
    df = equity_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    wide = df.pivot_table(index="timestamp", columns="symbol", values="close").ffill()
    if wide.empty:
        return pd.DataFrame()
    ratio = wide.div(wide.iloc[0]).mean(axis=1)
    bh = initial * ((1.0 - exposure) + exposure * ratio)
    return pd.DataFrame({"timestamp": bh.index, "equity": bh.values})


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
        tooltip=[alt.Tooltip("timestamp:T", title="Zmiana ustawień", format="%d.%m.%Y %H:%M"),
                 alt.Tooltip("zmiany:N", title="Pola")],
    )


def equity_chart(strat: pd.DataFrame, bh: pd.DataFrame,
                 bh_fair: pd.DataFrame | None = None) -> alt.Chart:
    layers = [strat.assign(seria=S_BOT)[["timestamp", "equity", "seria"]]]
    if len(bh):
        layers.append(bh.assign(seria=S_BH_ALL)[["timestamp", "equity", "seria"]])
    if bh_fair is not None and len(bh_fair):
        layers.append(bh_fair.assign(seria=S_BH_FAIR)[["timestamp", "equity", "seria"]])
    data = pd.concat(layers, ignore_index=True)
    data["timestamp"] = to_local(data["timestamp"])
    lines = alt.Chart(data).mark_line().encode(
        x=alt.X("timestamp:T", title=None, axis=layout.time_axis()),
        y=alt.Y("equity:Q", title="Wartość ($)", scale=alt.Scale(zero=False, nice=False)),
        color=alt.Color("seria:N", title=None, legend=layout.legend(),
                        scale=alt.Scale(domain=[S_BOT, S_BH_ALL, S_BH_FAIR],
                                        range=[ACCENT, BH_COLOR, BH_FAIR_COLOR])),
        tooltip=[alt.Tooltip("timestamp:T", title="Czas", format="%d.%m.%Y %H:%M"),
                 alt.Tooltip("equity:Q", title="Wartość ($)", format=",.2f"),
                 alt.Tooltip("seria:N", title="Seria")],
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

    # 1) Ile masz
    top = st.columns([2, 3])
    with top[0]:
        st.metric("Ile masz (wirtualne $)", humanize.money2(eq), f"{change:+.2f}% od startu")
        now_at_work = (invested / eq * 100.0) if eq else 0.0
        st.caption(f"💵 wolne: {humanize.money2(cash)} · 📈 w grze: "
                   f"{humanize.money2(invested)} (**{now_at_work:.0f}% pieniędzy**)  ·  "
                   f"tryb **paper** (ćwiczebny, nie prawdziwe pieniądze)")
    # 2) status bota
    with top[1]:
        tf = state.get("timeframe", cfg.exchange.timeframe)
        status = humanize.bot_status(state.get("last_candle_ts", {}),
                                     TIMEFRAME_MS.get(tf, 0), datetime.now(UTC), DISPLAY_TZ)
        st.markdown(f"### {status['emoji']} Status bota")
        st.markdown(status["text"])
        if state.get("kill_switch"):
            st.warning("🛑 Bezpiecznik dzienny włączony — bot nie otwiera teraz nowych pozycji.")

    st.divider()

    # 3) Jak to szło
    st.subheader("Jak to szło")
    rng_label = st.radio("Zakres", list(RANGES), horizontal=True, label_visibility="collapsed")
    equity_df = with_live_point(equity_df, state)  # curve tracks 'Ile masz', not just closes
    win = window_df(equity_df, RANGES[rng_label])
    strat_eq = book_equity_series(win)
    if len(strat_eq):
        at_work = money_at_work_pct(win)
        scale = strat_eq["equity"].iloc[0] / initial  # rebase to the window start
        bh = buy_hold_curve(win, initial)
        bh_fair = buy_hold_curve(win, initial, exposure=at_work / 100.0)
        if len(bh):
            bh = bh.assign(equity=bh["equity"] * scale)
        if len(bh_fair):
            bh_fair = bh_fair.assign(equity=bh_fair["equity"] * scale)
        st.altair_chart(equity_chart(strat_eq, bh, bh_fair), width="stretch")
        st.caption(
            f"Obie szare linie to „kup i trzymaj\", czyli kupić raz i czekać. Bot trzymał "
            f"w rynku średnio **{at_work:.0f}% pieniędzy**, więc uczciwe porównanie to "
            f"**ciemna** linia — ktoś, kto włożył tyle samo co on. Jasną linię (wszystkie "
            f"pieniądze w rynku) bot łatwo bije w spadkach, ale nie dlatego, że jest mądry "
            f"— po prostu go tam nie było."
        )
        # The same result counted two ways: idle cash makes the first number look gentler.
        win_return = (strat_eq["equity"].iloc[-1] / strat_eq["equity"].iloc[0] - 1.0) * 100.0
        risked = return_on_risked_pct(win_return, at_work)
        c1, c2 = st.columns(2)
        c1.metric("Wynik od wszystkich pieniędzy", f"{win_return:+.2f}%",
                  help=humanize.GLOSSARY["wynik_calosc"])
        c2.metric("Wynik od pieniędzy w grze",
                  f"{risked:+.2f}%" if risked is not None else "—",
                  help=humanize.GLOSSARY["wynik_w_grze"])
    else:
        st.info("Za mało danych na wykres — bot dopiero zaczyna zbierać historię.")

    st.divider()

    # 4) Co bot teraz trzyma
    # Each instrument is clickable: the title opens its price chart below (hovering
    # shows the numbers). The choice is kept in session state rather than a popover,
    # which the 15s fragment refresh would keep closing — see price_view's docstring.
    st.subheader("Co bot teraz trzyma")
    price_view.styles()
    positions = state.get("positions", {})
    last_close = state.get("last_close", {})

    def prices_for(sym: str) -> pd.DataFrame:
        return price_view.crypto_prices(sym, equity_df)

    if not positions:
        st.info("Nic — bot czeka na okazję. 🕊️")
    else:
        st.caption("Kliknij instrument, aby zobaczyć jego kurs.")
        cols = st.columns(min(len(positions), 3))
        for i, (sym, pos) in enumerate(positions.items()):
            card = humanize.position_card(pos, last_close.get(sym))
            with cols[i % len(cols)]:
                price_view.preview_button(f"**{card['emoji']} {card['title']}**", sym,
                                          "crypto_pos", key=f"pos_{sym}",
                                          prices=prices_for(sym))
                tone = "green" if card["pnl"] > 0 else ("red" if card["pnl"] < 0 else "gray")
                st.markdown(f":{tone}[{card['detail']}]")
        price_view.render("crypto_pos", prices_for, trades, positions)

    st.divider()

    # 5) Dziennik zdarzeń
    st.subheader("Dziennik zdarzeń")
    if len(alerts):
        st.caption("Kliknij zdarzenie, aby zobaczyć kurs w tamtym momencie.")
        rows = journals.records(alerts.sort_values("timestamp", ascending=False).head(15))
        for n, rec in enumerate(rows):
            e = humanize.event_line(rec, DISPLAY_TZ)
            sym = rec.get("symbol")
            if sym:  # risk/config alerts carry no instrument — nothing to preview
                key = f"ev_{n}_{sym}"
                price_view.preview_button(f"{e['emoji']} `{e['time']}` {e['text']}", sym,
                                          "crypto_ev", key=key,
                                          at=rec.get("timestamp"), prices=prices_for(sym))
                # inside the loop: the chart belongs under the clicked line, not
                # under fifteen rows of other events where nobody looks for it
                price_view.render("crypto_ev", prices_for, trades, positions, item=key)
            else:
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
    c2 = st.columns(4)
    c2[0].metric("Pieniądze w grze", f"{m.get('at_work', 0):.0f}%",
                 help=humanize.GLOSSARY["Pieniądze w grze"])
    c2[1].metric("Czas w rynku", f"{m.get('in_market', 0):.0f}%",
                 help=humanize.GLOSSARY["Czas w rynku"])
    risked = m.get("return_on_risked")
    c2[2].metric("Wynik od pieniędzy w grze",
                 f"{risked:+.2f}%" if risked is not None else "—",
                 help=humanize.GLOSSARY["wynik_w_grze"])


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
    if layout.is_mobile():
        layout.cards(per, "symbol", ["pnl_netto", "win_rate", "transakcje"],
                     {"pnl_netto": "+.2f", "win_rate": ".0f", "transakcje": ".0f"},
                     color_by="pnl_netto")
    else:
        st.dataframe(
            per.style.map(pnl_color, subset=["pnl_netto"]).format(
                {"win_rate": "{:.0f}%", "pnl_netto": "{:+.2f}", "prowizje": "{:.2f}"}),
            width="stretch", hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Rozkład wyników transakcji")
        hist = alt.Chart(trades).mark_bar().encode(
            x=alt.X("pnl:Q", bin=alt.Bin(maxbins=30), title="PnL (USDT)"),
            y=alt.Y("count()", title="Liczba"),
            color=alt.condition(alt.datum.pnl > 0, alt.value(GOOD), alt.value(BAD)),
        ).properties(height=layout.chart_height(240))
        st.altair_chart(hist, width="stretch")
    with col2:
        st.subheader("Powody wyjścia")
        if "exit_reason" in trades:
            reasons = trades["exit_reason"].value_counts().reset_index()
            reasons.columns = ["powód", "liczba"]
            bar = alt.Chart(reasons).mark_bar(color=ACCENT).encode(
                x=alt.X("liczba:Q", title="Liczba"),
                y=alt.Y("powód:N", title=None, sort="-x"),
            ).properties(height=layout.chart_height(240))
            st.altair_chart(bar, width="stretch")


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
    if layout.is_mobile():
        layout.cards(df, "Para", ["p(long)", "Próg", "Decyzja"],
                     {"p(long)": ".3f", "Próg": ".2f"})
    else:
        st.dataframe(df.style.format({"p(long)": "{:.3f}", "Próg": "{:.2f}"}, na_rep="—"),
                     width="stretch", hide_index=True)


def tab_variants(books: dict[str, Path]) -> None:
    st.subheader("Porównanie wariantów na żywo")
    if len(books) < 2:
        st.info("Brak wariantów A/B. Dodaj sekcję `variants:` w config.yaml, aby kilka "
                "konfiguracji handlowało równolegle na tych samych danych.")
    initial = cfg.paper.initial_capital
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
            "Wariant": name, "Kapitał": state.get("equity", initial),
            "Sharpe": m.get("sharpe"), "Max DD %": m.get("max_dd"),
            "W grze %": m.get("at_work"), "Wynik od tego %": m.get("return_on_risked"),
            "Win rate %": m.get("win_rate"), "Transakcje": len(trades),
        })
    if curves:
        data = pd.concat(curves, ignore_index=True)
        chart = alt.Chart(data).mark_line().encode(
            x=alt.X("timestamp:T", title=None, axis=layout.time_axis()),
            y=alt.Y("equity:Q", title="Kapitał (USDT)", scale=alt.Scale(zero=False)),
            color=alt.Color("wariant:N", title="Wariant", legend=layout.legend("Wariant")),
        ).properties(height=layout.chart_height(320))
        st.altair_chart(chart, width="stretch")
    metrics_df = pd.DataFrame(metric_rows)
    if layout.is_mobile():
        # Eight columns do not fit; equity, Sharpe and drawdown are what the A/B
        # comparison is actually for.
        layout.cards(metrics_df, "Wariant", ["Kapitał", "Sharpe", "Max DD %", "Transakcje"],
                     {"Kapitał": ",.2f", "Sharpe": ".2f", "Max DD %": ".2f",
                      "Transakcje": ".0f"})
    else:
        st.dataframe(metrics_df.style.format(
            {"Kapitał": "{:,.2f}", "Sharpe": "{:.2f}", "Max DD %": "{:.2f}",
             "W grze %": "{:.0f}", "Wynik od tego %": "{:+.2f}",
             "Win rate %": "{:.0f}"}, na_rep="—"), width="stretch", hide_index=True)


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
    if layout.is_mobile():
        layout.cards(df[cols], "kind",
                     ["timestamp", "mean_return_pct", "benchmark_return_pct", "total_trades"],
                     {"mean_return_pct": "+.2f", "benchmark_return_pct": "+.2f",
                      "total_trades": ".0f"},
                     color_by="mean_return_pct")
    else:
        st.dataframe(df[cols], width="stretch", hide_index=True)


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
            # ts is the last closed candle's OPEN time; it finalized bar_ms later.
            # Overdue only once a whole extra bar past that close has elapsed.
            overdue_ms = (now - datetime.fromisoformat(ts)).total_seconds() * 1000 - bar_ms
            if overdue_ms > bar_ms + 15 * 60_000:
                stale.append(sym)
        cols = st.columns(4)
        cols[0].metric(f"Wariant: {name}", "OK" if not stale else "UWAGA")
        cols[1].metric("Kill-switch", "AKTYWNY" if state.get("kill_switch") else "nieaktywny",
                       help=humanize.GLOSSARY["Kill-switch"])
        cols[2].metric("Drawdown", f"{state.get('drawdown_pct', 0):.2f}%",
                       help=humanize.GLOSSARY["Max drawdown"])
        cols[3].metric("Ostatni stan", humanize._fmt_time(state.get("updated_at"), DISPLAY_TZ))
        if stale:
            st.warning(f"[{name}] przeterminowane dane dla: {', '.join(stale)} "
                       f"(silnik może nie przetwarzać świec)")

    status_path = runtime / "refresh_status.json"
    if status_path.exists():
        rs = json.loads(status_path.read_text())
        st.caption(f"Refresher: {rs.get('status', '?')} @ {rs.get('timestamp', '?')} "
                   f"— {rs.get('detail', '')}")

    st.subheader("Ostatnie alerty")
    frames = [journals.load_jsonl(runtime / "alerts.jsonl")]
    frames += [journals.load_jsonl(bdir / "alerts.jsonl") for bdir in books.values()]
    alerts = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(
        len(f) for f in frames) else pd.DataFrame()
    if len(alerts):
        alerts = alerts.drop_duplicates().sort_values("timestamp", ascending=False).head(30)
        alert_cols = [c for c in ["timestamp", "kind", "message", "variant"] if c in alerts]
        if layout.is_mobile():
            # Alerts already carry a Polish sentence; the timeline reads better than a grid.
            for rec in journals.records(alerts.head(layout.max_cards() * 2)):
                e = humanize.event_line(rec, DISPLAY_TZ)
                st.markdown(f"{e['emoji']} &nbsp;`{e['time']}` &nbsp; {e['text']}")
        else:
            st.dataframe(alerts[alert_cols], width="stretch", hide_index=True)
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
    equity_df = journals.load_jsonl(book_dir / "equity.jsonl")
    trades = journals.load_jsonl(book_dir / "trades.jsonl")
    alerts = journals.load_jsonl(book_dir / "alerts.jsonl")

    if len(names) > 1:
        st.caption(f"Twój portfel: **{primary}** (pozostałe warianty w Szczegółach)")
    render_beginner(state, equity_df, trades, alerts)

    # Desktop tabs switch client-side, but the mobile segmented control triggers a
    # rerun — which would slam the expander shut on every panel change. Reading the
    # control's stored value *before* the expander renders keeps it open once used.
    details_key = "crypto_details_panel"
    with st.expander("🔬 Szczegóły dla dociekliwych",
                     expanded=bool(st.session_state.get(details_key))):
        sel = st.selectbox("Księga (wariant)", names,
                           index=names.index(primary)) if len(names) > 1 else primary
        d = books[sel]
        s_state = load_state(d) or {}
        s_eq = journals.load_jsonl(d / "equity.jsonl")
        s_tr = journals.load_jsonl(d / "trades.jsonl")
        tab_metrics(s_eq, s_tr, s_state)
        panels = {
            "Analityka": lambda: tab_analytics(s_tr),
            "Model": lambda: tab_model(s_state),
            "Warianty": lambda: tab_variants(books),
            "Eksperymenty": tab_experiments,
            "Zdrowie": lambda: tab_health(books),
        }
        if layout.is_mobile():
            # Five tabs in a row scroll off a 390px screen with no hint that more
            # exist; a segmented control wraps onto as many lines as it needs.
            choice = st.segmented_control("Szczegóły", list(panels), default="Analityka",
                                          label_visibility="collapsed", key=details_key)
            panels[choice or "Analityka"]()
        else:
            for tab, render_panel in zip(st.tabs(list(panels)), panels.values(),
                                         strict=True):
                with tab:
                    render_panel()


# ---------- app ----------

# The module selector lives OUTSIDE the auto-refreshing fragment: switching it must
# trigger a full rerun (a widget inside a run_every fragment would drop the change).
st.title("TraDaemon 👹💰")
# Here rather than per module: the deploy on the NAS rebuilds the image from git, and this
# is the only way to tell from the browser whether the running container is the fresh one.
st.caption(f"wersja {__version__}")
MODULES = ["Krypto-scalper", "Zarządca portfela", "Badania", "Ustawienia"]
# segmented_control wraps onto several lines when the labels do not fit, where a
# horizontal radio would overflow the viewport at 390px.
_module = st.segmented_control("Moduł", MODULES, default=MODULES[0],
                               label_visibility="collapsed") or MODULES[0]


@st.fragment(run_every=layout.refresh_interval())
def render_live() -> None:
    """The two modules that hold positions — auto-refreshed."""
    if _module == "Zarządca portfela":
        from trademon.dashboard import portfolio_view
        portfolio_view.render()
    else:
        render_crypto()


def render() -> None:
    if _module == "Ustawienia":
        # Writing config must never sit inside a run_every fragment: an auto-rerun
        # mid-edit would discard whatever is typed into the form.
        from trademon.dashboard import config_view
        config_view.render()
    elif _module == "Badania":
        # Studies produce a report, not a position: nothing here changes every 15s,
        # and auto-refresh would fight the buttons and the date input.
        from trademon.dashboard import research_view
        research_view.render()
    else:
        render_live()


render()
