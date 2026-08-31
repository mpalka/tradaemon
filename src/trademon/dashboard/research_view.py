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

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from trademon import i18n
from trademon.config import load_config
from trademon.dashboard import layout
from trademon.i18n import t
from trademon.portfolio.config import load_portfolio_config
from trademon.portfolio.correlation import verdict_help, verdict_label

cfg = load_config()
REPORTS = cfg.paths.models_dir / "reports"
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Verdict colours, keyed by the token the screen writes into its CSV. Those tokens are
# stored data — every report already under `models/reports/` uses them — so they stay
# Polish and untranslated; only the label and the explanation below are translated.
# The point is that "low correlation" is not automatically good: TRACI and PUŁAPKA
# earn their diversification by losing money.
VERDICT_STYLE = {
    "KANDYDAT": "#0ca30c", "NIESTABILNY": "#c98a00",
    "TRACI": "#d03b3b", "PUŁAPKA": "#8a2be2", "SKORELOWANY": "#888888",
}
# The token -> words mapping lives in `portfolio.correlation`, next to the code that
# writes the tokens, so a CLI script can use it without importing Streamlit.
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
        return t("research.unknown_date")


def run_script(script: str, args: list[str]) -> tuple[bool, str]:
    """Re-run a study on cached data. Downloads are deliberately not triggered from
    the browser: refreshing dozens of tickers would freeze the panel for minutes."""
    try:
        # fixed script path, no shell — the only caller-supplied value is a date string
        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / script), *args],
            capture_output=True, text=True, timeout=600, cwd=PROJECT_ROOT, check=False,
            # The report is printed straight into `st.code` below, so it has to come
            # back in the language this viewer is reading — which a subprocess cannot
            # inherit from the session any other way.
            env={**os.environ, i18n.ENV_VAR: i18n.get_lang()})
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return False, t("research.timeout")


def _no_data(name: str, command: str) -> None:
    st.info(t("research.no_results", name=name))
    st.caption(t("research.run_to_see"))
    st.code(command, language="bash")


# ---------- cross-sectional ranking ----------

def tab_crosssec() -> None:
    st.subheader(t("research.crosssec.title"))
    st.caption(t("research.crosssec.help"))
    path = latest("crosssec")
    if path is None:
        _no_data(t("research.crosssec.name"),
                 "python scripts/crosssec_backtest.py --refresh")
        return
    df = pd.read_csv(path)
    st.caption(t("research.last_run", when=stamp_of(path)))

    full = df[df["window"] == 0]
    if len(full):
        st.markdown(t("research.crosssec.luck_question"))
        # One column per row would stack into a very long strip on a phone.
        cols = st.columns(min(len(full), 2) if layout.is_mobile() else len(full))
        for col, (_, r) in zip(cols, full.iterrows(), strict=False):
            sig = abs(r["sigmas_from_zero"]) >= SIGMA_BAR
            col.metric(f"{r['market']} · {r['direction']}",
                       f"{r['total_return_pct']:+.1f}%",
                       t("research.sigmas", n=f"{r['sigmas_from_zero']:+.2f}"),
                       delta_color="normal" if sig else "off",
                       help=t("research.sigmas.help"))
        if not (abs(full["sigmas_from_zero"]) >= SIGMA_BAR).any():
            st.warning(t("research.crosssec.all_noise"))

    st.markdown(t("research.crosssec.all_windows"))
    st.caption(t("research.crosssec.hurdle_help"))
    per_window = df[df["window"] > 0]
    names = {c: t(f"col.{c}") for c in
             ("market", "direction", "window", "total_return_pct", "hurdle_pct",
              "excess_vs_hurdle_pp", "sharpe", "max_drawdown_pct",
              "avg_net_exposure_pct")}
    view = per_window[list(names)].rename(columns=names)
    signed = [names[c] for c in ("total_return_pct", "hurdle_pct",
                                 "excess_vs_hurdle_pp", "avg_net_exposure_pct")]
    st.dataframe(view.style.format({c: "{:+.2f}" for c in signed}
                                   | {names["sharpe"]: "{:.2f}",
                                      names["max_drawdown_pct"]: "{:.1f}"}),
                 width="stretch", hide_index=True)

    for (market, direction), g in per_window.groupby(["market", "direction"]):
        wins = int((g["excess_vs_hurdle_pp"] > 0).sum())
        consistent = wins in (0, len(g))
        icon = "🟢" if consistent and wins else ("🔴" if consistent else "🎲")
        tail = t("research.sign.consistent") if consistent and wins else (
            t("research.sign.consistently_negative") if consistent
            else t("research.sign.flips"))
        st.markdown(t("research.window_line", icon=icon, market=market,
                      direction=direction, wins=wins, total=len(g), tail=tail))

    st.warning(t("research.crosssec.survivorship"))

    if st.button(t("research.recompute"), key="run_crosssec"):
        with st.spinner(t("research.spinner.matrix")):
            ok, out = run_script("crosssec_backtest.py", [])
        st.success(t("research.done")) if ok else st.error(t("research.failed"))
        st.code(out[-3000:], language="text")


# ---------- diversification screen ----------

def tab_screen() -> None:
    pcfg = load_portfolio_config()
    st.subheader(t("research.screen.title"))
    st.caption(t("research.screen.help", benchmark=pcfg.screen.benchmark))
    path = latest("screen")
    if path is None:
        _no_data(t("research.screen.name"), "python scripts/correlation_screen.py")
        return
    df = pd.read_csv(path)
    # An --as-of run is a snapshot of the past; showing it under today's date would
    # present a 2016-vintage answer as the current one.
    as_of = str(df["as_of"].iloc[0]) if "as_of" in df and len(df) else ""
    if as_of and as_of.lower() != "nan":
        st.warning(t("research.screen.as_of", date=as_of, when=stamp_of(path)))
    else:
        st.caption(t("research.last_run", when=stamp_of(path)))

    negatives = df[df["corr"] < 0]
    keepers = df[df["verdict"] == "KANDYDAT"]
    c = st.columns(3)
    c[0].metric(t("research.screen.negatively_correlated"),
                t("research.screen.n_of_m", n=len(negatives), m=len(df)))
    c[1].metric(t("research.screen.passes"), f"{len(keepers)}",
                help=t("research.screen.passes.help"))
    c[2].metric(t("research.screen.negative_and_earning"),
                f"{len(negatives[negatives['cagr_pct'] > 0])}",
                help=t("research.screen.negative_and_earning.help"))
    if negatives.empty or (negatives["cagr_pct"] > 0).sum() == 0:
        st.info(t("research.screen.none_negative"))

    st.markdown(t("research.screen.rolling_matters"))
    names = {c: t(f"col.{c}") for c in
             ("corr", "roll_min", "roll_max", "cagr_pct", "months", "verdict", "as_of")}
    # These are ETFs and funds, not trading pairs, so this table does not reuse
    # `col.symbol` — the crypto screens do.
    names["symbol"] = t("col.asset")
    view = df.rename(columns={k: v for k, v in names.items() if k in df.columns})
    # The verdict token stays in the CSV; only what the reader sees is translated.
    view[names["verdict"]] = view[names["verdict"]].map(verdict_label)
    label_colour = {verdict_label(k): v for k, v in VERDICT_STYLE.items()}

    def colour(v: str) -> str:
        return f"color: {label_colour.get(v, '')}; font-weight: 600"

    if layout.is_mobile():
        layout.cards(view, names["symbol"],
                     [names["verdict"], names["corr"], names["cagr_pct"]],
                     {names["corr"]: "+.2f", names["cagr_pct"]: "+.1f"})
    else:
        st.dataframe(
            view.style.map(colour, subset=[names["verdict"]]).format(
                {names["corr"]: "{:+.2f}", names["roll_min"]: "{:+.2f}",
                 names["roll_max"]: "{:+.2f}", names["cagr_pct"]: "{:+.1f}"}),
            width="stretch", hide_index=True, height=420)
    st.caption(" · ".join(f"**{verdict_label(k)}** = {verdict_help(k)}"
                          for k in VERDICT_STYLE))

    st.error(t("research.screen.regime_warning"))

    col = st.columns([2, 3])
    as_of = col[0].text_input(t("research.screen.as_of_input"), value="",
                              placeholder=t("research.screen.as_of_placeholder"),
                              key="asof")
    if col[1].button(t("research.recompute"), key="run_screen"):
        args = ["--no-download"] + (["--as-of", as_of] if as_of.strip() else [])
        with st.spinner(t("research.spinner.correlations")):
            ok, out = run_script("correlation_screen.py", args)
        st.success(t("research.done")) if ok else st.error(t("research.failed"))
        st.code(out[-3000:], language="text")


def render() -> None:
    st.caption(t("research.intro"))
    panels = {"crosssec": tab_crosssec, "screen": tab_screen}
    if layout.is_mobile():
        first = next(iter(panels))
        choice = st.segmented_control(t("module.research"), list(panels), default=first,
                                      format_func=lambda c: t(f"research.tab.{c}"),
                                      label_visibility="collapsed")
        panels[choice or first]()
    else:
        labels = [t(f"research.tab.{code}") for code in panels]
        for tab, render_panel in zip(st.tabs(labels), panels.values(), strict=True):
            with tab:
                render_panel()
