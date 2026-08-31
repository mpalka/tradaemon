"""Test B1 — does the payoff geometry, not the model, explain the ~0?

With TP = tp*ATR and SL = sl*ATR, a trade needs a win rate above
    break-even = sl / (tp + sl)
just to be flat before costs. The shipped config (1.5 / 2.0) demands 57.1%.
This sweeps the geometry: each cell relabels the triple barrier, retrains
long+short on pre-window bars only, and replays the held-out windows.

always_short is recomputed per cell, because changing the barriers changes the
control too. `przewaga` (realized win rate minus break-even) is the number to
read: positive means the geometry is reachable for this model.

Usage: python scripts/research/rr_grid.py [--windows 4]
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import time
import warnings

import pandas as pd

from tradaemon.config import load_config
from tradaemon.research.lab import (
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
pd.set_option("display.width", 250)

TP_GRID = [1.0, 1.5, 2.0, 3.0]
SL_GRID = [1.0, 1.5, 2.0]
# Futures VIP0 taker — the regime Test A showed is the realistic one.
COSTS = (0.0005, 0.0002, 2.0, "taker")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--every", type=int, default=1, help="use every Nth window (thins the sweep)")
    ap.add_argument("--min-train-bars", type=int, default=1200)
    ap.add_argument("--direction", default="long_short")
    args = ap.parse_args()

    cfg = load_config()
    pairs = load_pairs(cfg)
    horizon = cfg.strategy.horizon_bars
    windows = [Window(i * args.window_days, args.window_days)
               for i in range(0, args.windows, args.every)]
    windows = [w for w in windows if enough_history(pairs, w, args.min_train_bars)]
    rt = round_trip_pct(*COSTS)
    cells = len(TP_GRID) * len(SL_GRID)

    span = next(iter(pairs.values()))["timestamp"]
    print(f"pary: {len(pairs)} | historia {span.min():%Y-%m-%d}..{span.max():%Y-%m-%d} | "
          f"horyzont {horizon} | koszty futures taker (round trip {rt:.2f}%) | "
          f"direction={args.direction}")
    print(f"okien testowych: {len(windows)} | siatka: {len(TP_GRID)}x{len(SL_GRID)} = "
          f"{cells} kombinacji TP/SL -> {cells * len(windows) * 2} treningow\n")

    rows = []
    t0 = time.time()
    for tp, sl in itertools.product(TP_GRID, SL_GRID):
        breakeven = sl / (tp + sl) * 100.0
        per_window = {"model": [], "always_short": []}
        regimes = []
        for w in windows:
            bundles = train_for_geometry(pairs, cfg, tp, sl, horizon, w)
            c = with_costs(
                with_strategy(cfg, tp_atr_mult=tp, sl_atr_mult=sl,
                              direction=args.direction), *COSTS
            )
            per_window["model"].append(run_oos(pairs, bundles, c, w))
            per_window["always_short"].append(
                run_oos(pairs, control_bundles("always_short"), c, w)
            )
            regimes.append(regime_of(per_window["model"][-1]["buy_hold_pct"]))

        for kind, res in per_window.items():
            wins = [r["mean_return_pct"] for r in res]
            n_tr = sum(r["n_trades"] for r in res)
            wr = sum(r["win_rate_pct"] * r["n_trades"] for r in res) / max(n_tr, 1)
            row = {
                "typ": kind, "tp": tp, "sl": sl, "R:R": round(tp / sl, 2),
                "prog_win_%": round(breakeven, 1),
                "win_%": round(wr, 1),
                "przewaga_pp": round(wr - breakeven, 1),
                "transakcje": n_tr,
                "brutto/trade_%": round(
                    sum(r["avg_gross_pct"] * r["n_trades"] for r in res) / max(n_tr, 1), 4),
                "netto/trade_%": round(
                    sum(r["avg_net_pct"] * r["n_trades"] for r in res) / max(n_tr, 1), 4),
                "wynik_sr_%": round(sum(wins) / len(wins), 2),
                "wynik_min_%": round(min(wins), 2),
                "okien+": f"{sum(x > 0 for x in wins)}/{len(wins)}",
                "sharpe": round(sum(r["mean_sharpe"] for r in res) / len(res), 2),
            }
            # Same cell, split by what the market was doing — a cell that only
            # works in one regime is a bet on that regime, not a strategy.
            for rg in ("wzrosty", "bok", "spadki"):
                sel = [x for x, g in zip(wins, regimes, strict=True) if g == rg]
                row[f"{rg}_%"] = round(sum(sel) / len(sel), 2) if sel else None
            rows.append(row)
        print(f"  tp={tp} sl={sl}: model {rows[-2]['wynik_sr_%']:+.2f}% "
              f"(wzrosty {rows[-2]['wzrosty_%']} / spadki {rows[-2]['spadki_%']}) | "
              f"zawsze_short {rows[-1]['wynik_sr_%']:+.2f}%  "
              f"[{time.time() - t0:.0f}s]", flush=True)

    table = pd.DataFrame(rows)
    out = cfg.paths.models_dir / "reports" / "research_rr_grid.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))

    for kind, tytul in (("model", "MODEL"), ("always_short", "KONTROLA 'zawsze short'")):
        g = table[table["typ"] == kind].drop(columns=["typ"])
        print("\n" + "=" * 140)
        print(f"TEST B1 — {tytul} (srednia po {len(windows)} oknach, koszty futures taker)")
        print("=" * 140)
        print(g.sort_values("wynik_sr_%", ascending=False).to_string(index=False))

    m = table[table["typ"] == "model"].set_index(["tp", "sl"])["wynik_sr_%"]
    s = table[table["typ"] == "always_short"].set_index(["tp", "sl"])["wynik_sr_%"]
    print("\n" + "=" * 70)
    print("MODEL MINUS KONTROLA (punkty proc.) — czy model wnosi cokolwiek")
    print("ponad glupie 'zawsze short'. Ujemne = nie wnosi.")
    print("=" * 70)
    print((m - s).unstack("sl").round(2).to_string())
    print(f"\nzapisano: {out}")


if __name__ == "__main__":
    main()
