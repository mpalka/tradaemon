"""Diversification screen: which assets actually move differently from world equities?

The premise is the opposite of modules 1 and 3 — nothing here tries to predict
anything. It asks a risk question: if the global equity market falls, what else in
the portfolio is not falling with it?

Two findings shape the design:

1. **Truly negative correlation to world equities barely exists** among assets with a
   positive expected return. The realistic goal is *low* correlation, not negative.
2. **A single 10-year correlation hides the only thing that matters.** Long bonds
   averaged +0.21 against world equities over the last decade while ranging from
   -0.47 to +0.75 on a rolling basis — they stopped diversifying in 2022, exactly
   when it counted. So the screen always reports the rolling range, not just the mean.

Anything with a negative expected return is ballast that sinks the boat: inverse and
volatility products score beautifully on correlation and lose money by construction.
The screen flags them rather than ranking them first.
"""

from __future__ import annotations

import pandas as pd

from tradaemon.i18n import t

MONTHS_PER_YEAR = 12
ROLL_MONTHS = 36          # three years — long enough to span a regime, short enough to move
MIN_MONTHS = 60           # below five years a correlation is not worth quoting

# A candidate has to clear both: a low average correlation is worthless if the
# correlation snaps positive in a crash, which is the only time it is needed.
MAX_MEAN_CORR = 0.40
MAX_PEAK_CORR = 0.60
# Structurally decaying products (inverse, volatility) — they earn their negative
# correlation by construction and give back more than they save.
DECAY_CORR = -0.30


def monthly_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """Month-end returns from a daily close panel."""
    return panel.resample("ME").last().pct_change().dropna(how="all")


def classify(mean_corr: float, peak_corr: float, cagr_pct: float) -> str:
    """Label a candidate the way a portfolio owner should read it."""
    if cagr_pct <= 0.0 and mean_corr <= DECAY_CORR:
        return "PUŁAPKA"        # negative by construction, decays while it waits
    if cagr_pct <= 0.0:
        return "TRACI"          # may diversify, but shrinks the portfolio meanwhile
    if mean_corr > MAX_MEAN_CORR:
        return "SKORELOWANY"
    if peak_corr > MAX_PEAK_CORR:
        return "NIESTABILNY"    # low on average, but joins the fall when it matters
    return "KANDYDAT"


def screen(panel: pd.DataFrame, benchmark: str, years: int = 10,
           roll_months: int = ROLL_MONTHS,
           as_of: pd.Timestamp | str | None = None) -> pd.DataFrame:
    """Rank every column of `panel` by how differently it moves from `benchmark`.

    Returns one row per candidate: mean monthly correlation over the window, the
    range that correlation took on a rolling `roll_months` basis, annualized return,
    and a verdict. Sorted by mean correlation, lowest first.

    `as_of` cuts the data off at a past date, so the screen sees only what was
    knowable then. Use it before believing any of this: run the screen as of ten
    years ago and check what it would have picked. It picked long bonds — the asset
    that went on to lose money and stop diversifying.
    """
    if benchmark not in panel.columns:
        raise KeyError(f"benchmark {benchmark!r} not in the panel "
                       f"(have {list(panel.columns)[:8]}...)")
    if as_of is not None:
        # accept both a naive "2016-07-30" from the CLI and an already-aware Timestamp
        cut = pd.Timestamp(as_of)
        if cut.tzinfo is None and panel.index.tz is not None:
            cut = cut.tz_localize(panel.index.tz)
        elif cut.tzinfo is not None and panel.index.tz is None:
            cut = cut.tz_localize(None)
        panel = panel[panel.index < cut]
        if panel.empty:
            return pd.DataFrame(columns=["symbol", "corr", "roll_min", "roll_max",
                                         "cagr_pct", "months", "verdict"])
    windowed = panel[panel.index >= panel.index.max() - pd.DateOffset(years=years)]
    monthly = monthly_returns(windowed)
    bench = monthly[benchmark]

    rows = []
    for sym in monthly.columns:
        if sym == benchmark:
            continue
        pair = pd.concat([monthly[sym], bench], axis=1).dropna()
        if len(pair) < MIN_MONTHS:
            continue
        asset, market = pair.iloc[:, 0], pair.iloc[:, 1]
        rolling = asset.rolling(roll_months).corr(market).dropna()
        span_years = len(asset) / MONTHS_PER_YEAR
        cagr = (((1.0 + asset).prod()) ** (1.0 / span_years) - 1.0) * 100.0
        mean_corr = float(asset.corr(market))
        peak = float(rolling.max()) if len(rolling) else mean_corr
        rows.append({
            "symbol": sym,
            "corr": mean_corr,
            "roll_min": float(rolling.min()) if len(rolling) else float("nan"),
            "roll_max": peak,
            "cagr_pct": cagr,
            "months": len(pair),
            "verdict": classify(mean_corr, peak, cagr),
        })
    columns = ["symbol", "corr", "roll_min", "roll_max", "cagr_pct", "months", "verdict"]
    if not rows:  # every candidate too young to quote — still hand back a usable frame
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values("corr").reset_index(drop=True)


# Stored token -> catalogue suffix. The tokens themselves are data: every CSV under
# `models/reports/` already holds them, and both the panel and the screen script match
# on them, so they are never translated — only these labels are.
VERDICT_KEYS = {
    "KANDYDAT": "candidate", "NIESTABILNY": "unstable", "TRACI": "loses",
    "PUŁAPKA": "trap", "SKORELOWANY": "correlated",
}


def verdict_label(token: str) -> str:
    """The word a reader sees for a stored verdict token."""
    key = VERDICT_KEYS.get(token)
    return t(f"verdict.{key}.label") if key else token


def verdict_help(token: str) -> str:
    """One line saying what that verdict means, and why it is not always good news."""
    key = VERDICT_KEYS.get(token)
    return t(f"verdict.{key}.help") if key else ""


def summarize_screen(result: pd.DataFrame, benchmark: str) -> list[str]:
    """The reading of the table, in plain language.

    The `verdict` column holds stored tokens (`KANDYDAT`, `PUŁAPKA`, …) that every
    saved report already uses, so they are matched as data and never translated.
    """
    if result.empty:
        return [t("screen.no_candidates")]
    negatives = result[result["corr"] < 0]
    keepers = result[result["verdict"] == "KANDYDAT"]
    lines = [t("screen.negatives", benchmark=benchmark, n=len(negatives),
               total=len(result))]
    if negatives.empty:
        lines.append(t("screen.none_negative.1"))
        lines.append(t("screen.none_negative.2"))
        lines.append(t("screen.none_negative.3"))
    if len(keepers):
        best = ", ".join(t("screen.keeper", symbol=r.symbol, corr=f"{r.corr:+.2f}",
                           cagr=f"{r.cagr_pct:+.1f}")
                         for r in keepers.itertuples())
        lines.append(t("screen.keepers", n=len(keepers), names=best))
    else:
        lines.append(t("screen.no_keepers.1"))
        lines.append(t("screen.no_keepers.2"))
    unstable = result[result["verdict"] == "NIESTABILNY"]
    if len(unstable):
        names = ", ".join(t("screen.unstable_item", symbol=r.symbol,
                            roll_max=f"{r.roll_max:+.2f}")
                          for r in unstable.itertuples())
        lines.append(t("screen.unstable", names=names))
    traps = result[result["verdict"].isin(["PUŁAPKA", "TRACI"])]
    if len(traps):
        names = ", ".join(t("screen.trap_item", symbol=r.symbol,
                            cagr=f"{r.cagr_pct:+.1f}")
                          for r in traps.itertuples())
        lines.append(t("screen.traps", names=names))
    return lines
