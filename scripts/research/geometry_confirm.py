"""Confirm (or kill) the TP/SL geometry candidate that rr_grid surfaced.

rr_grid picked TP 1.5 / SL 1.5 as the best of 12 cells on 10 windows. Picking
the maximum of 12 numbers is not evidence — the winner is partly whichever cell
got the luckiest windows. So this script re-tests the candidate against the
shipped 1.5 / 2.0 and splits the report three ways:

  * wybor   — the 10 windows rr_grid searched over. Contaminated by selection;
              shown only so the two views can be compared.
  * KONTROLNE — the 19 windows rr_grid never saw. This is the honest test.
  * wszystkie — all 29, for completeness.

Because both geometries are evaluated on the same windows, the comparison is
paired: the statistic is the per-window difference, which cancels the market
conditions common to both and is far more sensitive than comparing two means.

Usage: python scripts/research/geometry_confirm.py [--windows 30]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import warnings

import pandas as pd
from scipy import stats

from trademon.config import load_config
from trademon.research.lab import (
    Window,
    control_bundles,
    enough_history,
    load_pairs,
    regime_of,
    round_trip_pct,
    run_oos,
    train_for_geometry,
    with_costs,
    with_strategy,
)

warnings.filterwarnings("ignore", message="X does not have valid feature names")
logging.basicConfig(level=logging.WARNING)
pd.set_option("display.width", 220)

COSTS = (0.0005, 0.0002, 2.0, "taker")
# (label, tp, sl). The shipped geometry first so differences read "candidate
# minus incumbent".
GEOMETRIES = [("obecne 1.5/2.0", 1.5, 2.0), ("kandydat 1.5/1.5", 1.5, 1.5)]
SELECTION_STEP = 3  # rr_grid ran with --every 3; those windows are contaminated


def paired_report(table: pd.DataFrame, direction: str, windows: list[str], tytul: str) -> dict:
    """Paired comparison of the two geometries over `windows`."""
    sub = table[(table["kierunek"] == direction) & (table["okno"].isin(windows))]
    piv = sub.pivot_table(index="okno", columns="wariant", values="wynik_%")
    a, b = GEOMETRIES[0][0], GEOMETRIES[1][0]
    if a not in piv or b not in piv:
        return {}
    diff = (piv[b] - piv[a]).dropna()
    t, p = stats.ttest_rel(piv[b].loc[diff.index], piv[a].loc[diff.index])

    print(f"\n--- {tytul} | kierunek {direction} | {len(diff)} okien ---")
    for name in (a, b):
        x = piv[name].dropna()
        print(f"  {name:<20} srednia {x.mean():+.3f}%  "
              f"okien na plusie {int((x > 0).sum())}/{len(x)}  "
              f"najgorsze {x.min():+.2f}%")
    print(f"  roznica (kandydat - obecne): {diff.mean():+.3f} pkt proc.  "
          f"lepszy w {int((diff > 0).sum())}/{len(diff)} oknach")
    print(f"  test parowany: t = {t:.2f}, p = {p:.3f}  -> "
          f"{'ISTOTNE' if p < 0.05 else 'NIEISTOTNE (nie do odroznienia od przypadku)'}")
    return {"widok": tytul, "kierunek": direction, "okien": len(diff),
            "obecne": round(float(piv[a].mean()), 4),
            "kandydat": round(float(piv[b].mean()), 4),
            "roznica": round(float(diff.mean()), 4),
            "lepszy_w": int((diff > 0).sum()), "t": round(float(t), 3),
            "p": round(float(p), 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=30)
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--min-train-bars", type=int, default=1200)
    args = ap.parse_args()

    cfg = load_config()
    pairs = load_pairs(cfg)
    horizon = cfg.strategy.horizon_bars
    all_idx = list(range(args.windows))
    windows = [(i, Window(i * args.window_days, args.window_days)) for i in all_idx]
    windows = [(i, w) for i, w in windows if enough_history(pairs, w, args.min_train_bars)]
    selection = {w.label() for i, w in windows if i % SELECTION_STEP == 0}
    holdout = {w.label() for i, w in windows if i % SELECTION_STEP != 0}

    print(f"pary: {len(pairs)} | okien: {len(windows)} "
          f"({len(selection)} uzytych do wyboru, {len(holdout)} kontrolnych) | "
          f"koszty futures taker (round trip {round_trip_pct(*COSTS):.2f}%)")

    rows, t0 = [], time.time()
    for label, tp, sl in GEOMETRIES:
        for _, w in windows:
            bundles = train_for_geometry(pairs, cfg, tp, sl, horizon, w)
            for direction in ("long", "long_short"):
                c = with_costs(with_strategy(cfg, tp_atr_mult=tp, sl_atr_mult=sl,
                                             direction=direction), *COSTS)
                r = run_oos(pairs, bundles, c, w)
                rows.append({
                    "wariant": label, "tp": tp, "sl": sl, "kierunek": direction,
                    "okno": w.label(), "rynek": regime_of(r["buy_hold_pct"]),
                    "zbior": "wybor" if w.label() in selection else "kontrolne",
                    "transakcje": r["n_trades"], "win_%": round(r["win_rate_pct"], 2),
                    "brutto/trade_%": round(r["avg_gross_pct"], 4),
                    "netto/trade_%": round(r["avg_net_pct"], 4),
                    "wynik_%": round(r["mean_return_pct"], 4),
                    "sharpe": round(r["mean_sharpe"], 3),
                })
        # Control uses this geometry's barriers, so it is refreshed per geometry.
        for _, w in windows:
            c = with_costs(with_strategy(cfg, tp_atr_mult=tp, sl_atr_mult=sl,
                                         direction="long_short"), *COSTS)
            r = run_oos(pairs, control_bundles("always_short"), c, w)
            rows.append({
                "wariant": label, "tp": tp, "sl": sl, "kierunek": "zawsze_short",
                "okno": w.label(), "rynek": regime_of(r["buy_hold_pct"]),
                "zbior": "wybor" if w.label() in selection else "kontrolne",
                "transakcje": r["n_trades"], "win_%": round(r["win_rate_pct"], 2),
                "brutto/trade_%": round(r["avg_gross_pct"], 4),
                "netto/trade_%": round(r["avg_net_pct"], 4),
                "wynik_%": round(r["mean_return_pct"], 4),
                "sharpe": round(r["mean_sharpe"], 3),
            })
        print(f"  {label}: policzone [{time.time() - t0:.0f}s]", flush=True)

    table = pd.DataFrame(rows)
    out = cfg.paths.models_dir / "reports" / "research_geometry_confirm.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))

    print("\n" + "=" * 110)
    print("POROWNANIE PAROWANE — kandydat 1.5/1.5 kontra obecne 1.5/2.0")
    print("=" * 110)
    verdicts = []
    for direction in ("long_short", "long"):
        for tytul, wins in (("KONTROLNE (nieuzywane do wyboru)", holdout),
                            ("wybor (skazone selekcja)", selection),
                            ("wszystkie okna", selection | holdout)):
            v = paired_report(table, direction, sorted(wins), tytul)
            if v:
                verdicts.append(v)

    print("\n" + "=" * 110)
    print("KAZDA GEOMETRIA KONTRA JEJ WLASNA KONTROLA 'zawsze short' (okna kontrolne)")
    print("=" * 110)
    hs = table[table["okno"].isin(holdout)]
    print(hs.groupby(["wariant", "kierunek"], sort=False)
          .agg(okien=("wynik_%", "size"), transakcje=("transakcje", "sum"),
               win_pct=("win_%", "mean"), brutto=("brutto/trade_%", "mean"),
               netto=("netto/trade_%", "mean"), wynik_sr=("wynik_%", "mean"),
               okien_dodatnich=("wynik_%", lambda s: int((s > 0).sum())),
               sharpe=("sharpe", "mean")).round(3).to_string())

    print("\n" + "=" * 110)
    print("PODZIAL WEDLUG RYNKU (okna kontrolne)")
    print("=" * 110)
    print(hs.pivot_table(index=["wariant", "kierunek"], columns="rynek",
                         values="wynik_%", aggfunc="mean").round(3).to_string())

    (out.parent / "research_geometry_verdict.json").write_text(
        json.dumps(verdicts, indent=2))
    print(f"\nzapisano: {out}")


if __name__ == "__main__":
    main()
