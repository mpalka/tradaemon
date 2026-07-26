"""Test A — how much of the edge is the fee schedule eating?

For each rolling out-of-sample window: fit long+short on the bars before it,
then replay the window under several cost regimes. The model, the strategy and
the bars are identical across rows within a window; only the cost model changes,
so the spread between rows is pure cost drag.

The controls matter more than usual here: the sample period is a bear market
(buy&hold ~ -60% over 300 days), so a short-capable strategy beats buy&hold for
free. always_short is the benchmark the model actually has to clear.

Usage: python scripts/research/fee_grid.py [--windows 4] [--window-days 60]
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings

import pandas as pd

from trademon.config import load_config
from trademon.research.lab import (
    COST_SCENARIOS,
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
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s: %(message)s")

pd.set_option("display.width", 200)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--min-train-bars", type=int, default=1200)
    ap.add_argument("--directions", default="long,long_short")
    args = ap.parse_args()

    cfg = load_config()
    pairs = load_pairs(cfg)
    strat = cfg.strategy
    windows = [Window(i * args.window_days, args.window_days) for i in range(args.windows)]
    skipped = [w for w in windows if not enough_history(pairs, w, args.min_train_bars)]
    windows = [w for w in windows if w not in skipped]

    span = next(iter(pairs.values()))["timestamp"]
    print(f"pary: {len(pairs)} | timeframe {cfg.exchange.timeframe} | "
          f"historia {span.min():%Y-%m-%d} .. {span.max():%Y-%m-%d}")
    print(f"strategia: TP {strat.tp_atr_mult} ATR / SL {strat.sl_atr_mult} ATR / "
          f"horyzont {strat.horizon_bars} / prog {strat.prob_threshold}")
    print(f"okien testowych: {len(windows)} po {args.window_days} dni "
          f"({len(windows) * args.window_days} dni lacznie)"
          + (f", pominieto {len(skipped)} (za malo historii do nauki)" if skipped else ""))

    rows = []
    for w in windows:
        print(f"okno {w.label()}: trenuje...", end="", flush=True)
        bundles = train_for_geometry(
            pairs, cfg, strat.tp_atr_mult, strat.sl_atr_mult, strat.horizon_bars, w
        )
        n = bundles["long"].metadata["n_samples"]

        def record(direction: str, name: str, res: dict, rt: float, kind: str,
                   okno: str = w.label()) -> None:
            rows.append({
                "okno": okno, "rynek": regime_of(res["buy_hold_pct"]),
                "kierunek": direction, "wariant": name, "typ": kind,
                "round_trip_%": round(rt, 3),
                "transakcje": res["n_trades"],
                "short_%": round(res["short_share_pct"]),
                "win_%": round(res["win_rate_pct"], 1),
                "brutto/trade_%": round(res["avg_gross_pct"], 4),
                "koszt/trade_%": round(res["avg_cost_pct"], 4),
                "netto/trade_%": round(res["avg_net_pct"], 4),
                "wynik_%": round(res["mean_return_pct"], 2),
                "b&h_%": round(res["buy_hold_pct"], 1),
                "par+": f"{res['pairs_positive']}/{res['pairs']}",
                "sharpe": round(res["mean_sharpe"], 2),
            })

        for direction in args.directions.split(","):
            base = with_strategy(cfg, direction=direction)
            for name, taker, maker, slip, style in COST_SCENARIOS:
                c = with_costs(base, taker, maker, slip, style)
                record(direction, name, run_oos(pairs, bundles, c, w),
                       round_trip_pct(taker, maker, slip, style), "model")
                print(".", end="", flush=True)

        # Controls under the two cost regimes that bracket the decision.
        for ctrl in ("always_long", "always_short", "random"):
            cb = control_bundles(ctrl)
            for label, taker, maker, slip, style in (
                ("spot taker (obecny config)", 0.0010, 0.0010, 2.0, "taker"),
                ("futures taker VIP0", 0.0005, 0.0002, 2.0, "taker"),
            ):
                c = with_costs(with_strategy(cfg, direction="long_short",
                                             prob_threshold=0.55), *(taker, maker, slip, style))
                record(ctrl, label, run_oos(pairs, cb, c, w),
                       round_trip_pct(taker, maker, slip, style), "kontrola")
                print("c", end="", flush=True)
        print(f" (n_train={n})")

    table = pd.DataFrame(rows)
    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "research_fee_grid.json").write_text(json.dumps(rows, indent=2))

    counts = table.drop_duplicates("okno")["rynek"].value_counts().to_dict()
    print("\n" + "=" * 118)
    print("JAK ZACHOWYWAL SIE RYNEK W OKNACH TESTOWYCH")
    print("=" * 118)
    print("  " + " | ".join(f"{k}: {v} okien" for k, v in counts.items()))
    per_window = (table.drop_duplicates("okno")[["okno", "rynek", "b&h_%"]]
                  .sort_values("okno"))
    print(per_window.to_string(index=False))

    def summarize(frame: pd.DataFrame) -> pd.DataFrame:
        return (frame.groupby(["typ", "kierunek", "wariant"], sort=False)
                .agg(okien=("wynik_%", "size"),
                     transakcje=("transakcje", "sum"),
                     brutto_trade_pct=("brutto/trade_%", "mean"),
                     netto_trade_pct=("netto/trade_%", "mean"),
                     wynik_sr_pct=("wynik_%", "mean"),
                     wynik_min_pct=("wynik_%", "min"),
                     wynik_max_pct=("wynik_%", "max"),
                     okien_dodatnich=("wynik_%", lambda s: int((s > 0).sum())),
                     sharpe=("sharpe", "mean"))
                .round(3).reset_index())

    print("\n" + "=" * 118)
    print("PODSUMOWANIE OGOLNE — srednia po wszystkich oknach")
    print("=" * 118)
    print(summarize(table).to_string(index=False))

    print("\n" + "=" * 118)
    print("PODZIAL WEDLUG TEGO, CO ROBIL RYNEK — czy strategia dziala tylko w spadkach?")
    print("=" * 118)
    for rynek in ("wzrosty", "bok", "spadki"):
        sub = table[table["rynek"] == rynek]
        if sub.empty:
            continue
        print(f"\n### rynek: {rynek}  ({sub['okno'].nunique()} okien, "
              f"sredni buy&hold {sub.drop_duplicates('okno')['b&h_%'].mean():+.1f}%)")
        print(summarize(sub).to_string(index=False))

    print(f"\nzapisano: {out_dir / 'research_fee_grid.json'}")


if __name__ == "__main__":
    main()
