"""Score the study on disjoint windows and report every one of them.

This exists because of a specific, repeated failure in this project: three separate
times a configuration looked profitable on one out-of-sample window and the edge
vanished on the next. A single headline number invites that mistake, so the runner
here produces a matrix — markets x directions x windows — and the report prints it
whole. Consistency of sign across windows is the finding; the best cell is not.
"""

from __future__ import annotations

import logging

import pandas as pd

from trademon.crosssec.backtest import run_crosssec_backtest
from trademon.crosssec.config import CrossSecConfig
from trademon.crosssec.panels import load_market_panel

log = logging.getLogger(__name__)

DIRECTIONS = ("long_only", "long_short")


def split_windows(panel: pd.DataFrame, n_windows: int, warmup: int,
                  min_tradable: int = 60) -> list[pd.DataFrame]:
    """Cut the panel into `n_windows` disjoint stretches, each carrying the warmup it
    needs so its first tradable day is a genuine out-of-sample decision.

    Falls back to a single window when the history cannot give every window at least
    `min_tradable` tradable bars: four windows of a handful of days each would look
    like independent evidence while carrying almost none.
    """
    usable = len(panel) - warmup
    if n_windows < 1 or usable < n_windows * min_tradable:
        return [panel]
    size = usable // n_windows
    out = []
    for k in range(n_windows):
        start = k * size                       # warmup bars are prepended below
        stop = start + warmup + size
        out.append(panel.iloc[start:stop])
    return out


def run_matrix(cfg: CrossSecConfig) -> pd.DataFrame:
    """Run every market x direction x window combination. One row per cell."""
    warmup = cfg.signal.lookback_days + cfg.signal.skip_days + 1
    rows: list[dict] = []
    for market in cfg.markets:
        panel = load_market_panel(cfg.paths.data_dir, market.name, market.symbols)
        if panel.empty:
            log.warning("%s: no price panel — run a data refresh first", market.name)
            continue
        log.info("%s: %d days, %d names (%s .. %s)", market.name, len(panel),
                 panel.shape[1], panel.index[0].date(), panel.index[-1].date())
        # a window worth scoring must hold several re-rankings, not one or two
        windows = split_windows(panel, cfg.n_windows, warmup,
                                min_tradable=max(60, 3 * cfg.rank.rebalance_days))
        if len(windows) == 1 and cfg.n_windows > 1:
            log.warning("%s: history too short for %d windows — scoring one window only",
                        market.name, cfg.n_windows)
        for direction in DIRECTIONS:
            for k, win in enumerate(windows, start=1):
                res = run_crosssec_backtest(win, cfg, direction, market.bars_per_year)
                s = res["summary"]
                if "error" in s:
                    log.warning("%s/%s window %d: %s", market.name, direction, k,
                                s["error"])
                    continue
                rows.append({"market": market.name, "direction": direction,
                             "window": k, **s})
            # the whole period, for context only — never as the verdict
            res = run_crosssec_backtest(panel, cfg, direction, market.bars_per_year)
            if "error" not in res["summary"]:
                rows.append({"market": market.name, "direction": direction,
                             "window": 0, **res["summary"]})
    return pd.DataFrame(rows)


HURDLE_LABEL = {"long_only": "koszyk", "long_short": "gotówkę"}


def verdict(matrix: pd.DataFrame) -> list[str]:
    """Read the matrix the way it should be read: does the sign hold up across
    windows, or does it straddle zero?

    Each direction is scored against the yardstick that matches its exposure —
    long_only against the equal-weight basket, long_short against cash.
    """
    lines = []
    for (market, direction), g in matrix[matrix["window"] > 0].groupby(
            ["market", "direction"]):
        exc = g["excess_vs_hurdle_pp"]
        wins = int((exc > 0).sum())
        spread = float(exc.max() - exc.min())
        consistent = wins == len(exc) or wins == 0
        lines.append(
            f"{market:6s} {direction:11s}: bije {HURDLE_LABEL[direction]:9s} "
            f"w {wins}/{len(exc)} oknach, nadwyżka od {exc.min():+.1f} do "
            f"{exc.max():+.1f} pkt (rozrzut {spread:.1f} pkt) — "
            + (("SPÓJNY znak" if wins else "SPÓJNIE UJEMNY") if consistent
               else "znak SIĘ ZMIENIA -> to szum")
        )
    return lines
