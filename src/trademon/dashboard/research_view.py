"""Research view: the two study tools that do not run a live book.

Modules 1 and 2 answer "how much do you have right now". These two answer a
different kind of question — "does this idea hold up?" — and produce a verdict, not
a position. They run on demand and write CSV reports, which this view reads back so
the findings are visible without a terminal.

Deliberately blunt: every table here is paired with what it does *not* prove. Both
studies came out indistinguishable from luck, and a dashboard that renders them as
green numbers would be lying by layout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from trademon.config import load_config
from trademon.portfolio.config import load_portfolio_config

cfg = load_config()
REPORTS = cfg.paths.models_dir / "reports"
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Verdict colours. The point is that "low correlation" is not automatically good:
# TRACI and PUŁAPKA earn their diversification by losing money.
VERDICT_STYLE = {
    "KANDYDAT": "#0ca30c", "NIESTABILNY": "#c98a00",
    "TRACI": "#d03b3b", "PUŁAPKA": "#8a2be2", "SKORELOWANY": "#888888",
}
VERDICT_HELP = {
    "KANDYDAT": "niska korelacja, stabilna, dodatni zwrot",
    "NIESTABILNY": "niska średnio, ale w kryzysie idzie razem z rynkiem",
    "TRACI": "dywersyfikuje, ale zjada portfel (ujemny zwrot)",
    "PUŁAPKA": "ujemna korelacja z konstrukcji — płaci za nią erozją kapitału",
    "SKORELOWANY": "porusza się razem z rynkiem — nie dywersyfikuje",
}
SIGMA_BAR = 2.0   # below this, a result is not distinguishable from luck


def latest(prefix: str) -> Path | None:
    """Newest CSV report for a given study, or None if it was never run."""
    if not REPORTS.exists():
        return None
    files = sorted(REPORTS.glob(f"{prefix}_*.csv"), reverse=True)
    return files[0] if files else None


def stamp_of(path: Path) -> str:
    """Human date from the report filename (crosssec_20260730_205218.csv)."""
    try:
        raw = path.stem.split("_", 1)[1]
        return pd.to_datetime(raw, format="%Y%m%d_%H%M%S").strftime("%d.%m.%Y %H:%M")
    except (ValueError, IndexError):
        return "nieznana data"


def run_script(script: str, args: list[str]) -> tuple[bool, str]:
    """Re-run a study on cached data. Downloads are deliberately not triggered from
    the browser: refreshing dozens of tickers would freeze the panel for minutes."""
    try:
        # fixed script path, no shell — the only caller-supplied value is a date string
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / script), *args],
            capture_output=True, text=True, timeout=600, cwd=PROJECT_ROOT, check=False)
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return False, "Przekroczono limit czasu (10 min)."


def _no_data(name: str, command: str) -> None:
    st.info(f"Brak zapisanych wyników dla: {name}.")
    st.caption("Uruchom badanie, żeby zobaczyć tu wyniki:")
    st.code(command, language="bash")


# ---------- cross-sectional ranking ----------

def tab_crosssec() -> None:
    st.subheader("Ranking przekrojowy")
    st.caption("Kupuj najsilniejsze aktywa, sprzedawaj najsłabsze — zakład na "
               "**różnicę między aktywami**, nie na kierunek rynku.")
    path = latest("crosssec")
    if path is None:
        _no_data("ranking przekrojowy", "python scripts/crosssec_backtest.py --refresh")
        return
    df = pd.read_csv(path)
    st.caption(f"Ostatnie przeliczenie: **{stamp_of(path)}**")

    full = df[df["window"] == 0]
    if len(full):
        st.markdown("**Czy wynik jest odróżnialny od szczęścia?**")
        cols = st.columns(len(full))
        for col, (_, r) in zip(cols, full.iterrows(), strict=False):
            sig = abs(r["sigmas_from_zero"]) >= SIGMA_BAR
            col.metric(f"{r['market']} · {r['direction']}",
                       f"{r['total_return_pct']:+.1f}%",
                       f"{r['sigmas_from_zero']:+.2f} odchyleń od zera",
                       delta_color="normal" if sig else "off",
                       help="Poniżej 2 odchyleń wynik jest nieodróżnialny od "
                            "przypadku — bez względu na to, jak duży jest procent.")
        if not (abs(full["sigmas_from_zero"]) >= SIGMA_BAR).any():
            st.warning("Żaden wariant nie osiąga 2 odchyleń od zera. **Te procenty nie "
                       "są przewagą** — mieszczą się w tym, co daje przypadek.")

    st.markdown("**Wszystkie okna** — czy znak się trzyma?")
    st.caption("Poprzeczka zależy od ekspozycji: wariant *tylko long* mierzy się "
               "z koszykiem kup&trzymaj, *long-short* (neutralny rynkowo) z gotówką.")
    per_window = df[df["window"] > 0]
    view = per_window[["market", "direction", "window", "total_return_pct",
                       "hurdle_pct", "excess_vs_hurdle_pp", "sharpe",
                       "max_drawdown_pct", "avg_net_exposure_pct"]].rename(columns={
        "market": "rynek", "direction": "kierunek", "window": "okno",
        "total_return_pct": "wynik %", "hurdle_pct": "poprzeczka %",
        "excess_vs_hurdle_pp": "nadwyżka pkt", "sharpe": "Sharpe",
        "max_drawdown_pct": "obsunięcie %", "avg_net_exposure_pct": "netto %"})
    st.dataframe(view.style.format({c: "{:+.2f}" for c in
                                    ["wynik %", "poprzeczka %", "nadwyżka pkt",
                                     "netto %"]}
                                   | {"Sharpe": "{:.2f}", "obsunięcie %": "{:.1f}"}),
                 use_container_width=True, hide_index=True)

    for (market, direction), g in per_window.groupby(["market", "direction"]):
        wins = int((g["excess_vs_hurdle_pp"] > 0).sum())
        consistent = wins in (0, len(g))
        icon = "🟢" if consistent and wins else ("🔴" if consistent else "🎲")
        tail = ("spójny znak" if consistent and wins else
                "spójnie ujemny" if consistent else "znak się zmienia → to szum")
        st.markdown(f"{icon} **{market} · {direction}** — bije poprzeczkę w "
                    f"{wins}/{len(g)} oknach, {tail}")

    st.warning("**Główne zastrzeżenie: błąd przetrwania.** Uniwersum krypto to pary, "
               "które *dotrwały* do dziś — bez LUNA, bez FTT. Do tego wariant "
               "long-short wymaga kontraktów wieczystych, a koszt funding nie jest "
               "w ogóle modelowany. To pomiar hipotezy, nie strategia.")

    if st.button("Przelicz na zapisanych danych", key="run_crosssec"):
        with st.spinner("Liczę macierz..."):
            ok, out = run_script("crosssec_backtest.py", [])
        st.success("Gotowe.") if ok else st.error("Nie udało się.")
        st.code(out[-3000:], language="text")


# ---------- diversification screen ----------

def tab_screen() -> None:
    pcfg = load_portfolio_config()
    st.subheader("Przesiew dywersyfikacji")
    st.caption(f"Pytanie o ryzyko, nie o prognozę: jeśli rynek światowy "
               f"(**{pcfg.screen.benchmark}**) spada, co *nie* spada razem z nim?")
    path = latest("screen")
    if path is None:
        _no_data("przesiew dywersyfikacji", "python scripts/correlation_screen.py")
        return
    df = pd.read_csv(path)
    # An --as-of run is a snapshot of the past; showing it under today's date would
    # present a 2016-vintage answer as the current one.
    as_of = str(df["as_of"].iloc[0]) if "as_of" in df and len(df) else ""
    if as_of and as_of.lower() != "nan":
        st.warning(f"⏳ To jest przesiew **na dzień {as_of}** — pokazuje tylko to, co "
                   f"było wiadome wtedy, a nie stan na dziś. Przeliczono "
                   f"{stamp_of(path)}.")
    else:
        st.caption(f"Ostatnie przeliczenie: **{stamp_of(path)}**")

    negatives = df[df["corr"] < 0]
    keepers = df[df["verdict"] == "KANDYDAT"]
    c = st.columns(3)
    c[0].metric("Ujemnie skorelowane", f"{len(negatives)} z {len(df)}")
    c[1].metric("Przechodzi przesiew", f"{len(keepers)}",
                help="Niska korelacja, stabilna w czasie, dodatni zwrot.")
    c[2].metric("Ujemne i zarabiające", f"{len(negatives[negatives['cagr_pct'] > 0])}",
                help="Aktywa naprawdę ujemnie skorelowane, które przy tym nie tracą.")
    if negatives.empty or (negatives["cagr_pct"] > 0).sum() == 0:
        st.info("Wśród aktywów o **dodatnim zwrocie** nie ma ani jednego ujemnie "
                "skorelowanego z rynkiem światowym. To jest wynik, nie brak wyniku: "
                "realny cel to *niska* korelacja, nie ujemna.")

    st.markdown("**Kolumny „min/max 3-let.” są ważniejsze niż średnia** — pokazują, "
                "co robiła korelacja w najgorszym momencie. Aktywo o średniej +0,2, "
                "które w kryzysie skacze do +0,75, nie ochroniło portfela wtedy, gdy "
                "było potrzebne.")
    view = df.rename(columns={"symbol": "aktywo", "corr": "korelacja",
                              "roll_min": "min 3-let.", "roll_max": "max 3-let.",
                              "cagr_pct": "CAGR %", "months": "mies.",
                              "verdict": "werdykt"})

    def colour(v: str) -> str:
        return f"color: {VERDICT_STYLE.get(v, '')}; font-weight: 600"

    st.dataframe(
        view.style.map(colour, subset=["werdykt"]).format(
            {"korelacja": "{:+.2f}", "min 3-let.": "{:+.2f}", "max 3-let.": "{:+.2f}",
             "CAGR %": "{:+.1f}"}),
        use_container_width=True, hide_index=True, height=420)
    st.caption(" · ".join(f"**{k}** = {v}" for k, v in VERDICT_HELP.items()))

    st.error("**Ta tabela opisuje reżim, który się właśnie skończył.** Przesiew "
             "uruchomiony na danych do 2016 wskazał obligacje długoterminowe (TLT) "
             "jako wzorowy dywersyfikator — korelacja −0,27 i nigdy dodatnia. "
             "Przez następną dekadę TLT straciło 5,2% rocznie i skoczyło do +0,75 "
             "w kryzysie 2022. Sprawdź sam: `--as-of` sprzed dziesięciu lat.")

    col = st.columns([2, 3])
    as_of = col[0].text_input("Przelicz na dzień (RRRR-MM-DD)", value="",
                              placeholder="np. 2016-07-30", key="asof")
    if col[1].button("Przelicz na zapisanych danych", key="run_screen"):
        args = ["--no-download"] + (["--as-of", as_of] if as_of.strip() else [])
        with st.spinner("Liczę korelacje..."):
            ok, out = run_script("correlation_screen.py", args)
        st.success("Gotowe.") if ok else st.error("Nie udało się.")
        st.code(out[-3000:], language="text")


def render() -> None:
    st.caption("Narzędzia badawcze — **nie prowadzą portfela**. Odpowiadają na "
               "pytanie „czy ten pomysł się broni?”, a nie „ile masz teraz”.")
    tabs = st.tabs(["📊 Ranking przekrojowy", "🧭 Przesiew dywersyfikacji"])
    with tabs[0]:
        tab_crosssec()
    with tabs[1]:
        tab_screen()
