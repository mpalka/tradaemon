"""Test B2 — structure-placed barriers plus an expected-value entry gate.

Barriers come from price structure (swing low / recent high), so R:R varies per
setup instead of being a constant of the config. Labels are recomputed against
those barriers, a model is fit on pre-window bars only, and entries are gated on
EV = p*R - (1-p) - cost_R rather than on P(win) alone.

Rows to compare:
  * `prob only`      — structure barriers, production-style probability gate.
                       Isolates the effect of moving the barriers.
  * `EV >= x`        — adds the expected-value gate. Isolates the effect of the
                       gate on top of the barriers.
  * `always_short`   — the bear-market control, same barriers, same costs.

Usage: python scripts/research/ev_gate.py [--windows 4]
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings

import numpy as np
import pandas as pd

from tradaemon.config import load_config
from tradaemon.features.engineering import FEATURE_COLUMNS, compute_features
from tradaemon.research.lab import (
    Window,
    buy_hold_pct,
    enough_history,
    fit_bundle,
    load_pairs,
    regime_of,
    round_trip_pct,
    test_slice,
    train_slice,
    with_costs,
    with_strategy,
)
from tradaemon.research.structure import barrier_labels, prepare, run_structure_backtest

warnings.filterwarnings("ignore", message="X does not have valid feature names")
logging.basicConfig(level=logging.WARNING)
pd.set_option("display.width", 250)

COSTS = (0.0005, 0.0002, 2.0, "taker")  # futures VIP0 taker
BARRIER_KW = {"swing_bars": 12, "level_bars": 60}

# name, min_ev, min_r, prob_threshold, size_by_risk
VARIANTS = [
    ("prob only (bez bramki EV)", None, 0.0, 0.55, False),
    ("EV >= 0.0",                 0.0,  0.0, 0.50, False),
    ("EV >= 0.1",                 0.1,  0.0, 0.50, False),
    ("EV >= 0.2",                 0.2,  0.0, 0.50, False),
    ("EV >= 0.3",                 0.3,  0.0, 0.50, False),
    ("EV >= 0.1, R >= 1.5",       0.1,  1.5, 0.50, False),
    # Exposure experiment, not an edge experiment: equal risk per trade instead
    # of equal notional. Compare its Sharpe, not its return.
    ("EV >= 0.1 + sizing po ryzyku 1%", 0.1, 0.0, 0.50, True),
]


def train_structure_models(pairs, cfg, window, horizon):
    feats, lab = {"long": [], "short": []}, {"long": [], "short": []}
    for df in pairs.values():
        sub = train_slice(df, window)
        bars = prepare(sub, cfg, **BARRIER_KW)
        f = compute_features(sub, cfg.strategy.atr_period)
        for d in ("long", "short"):
            feats[d].append(f)
            lab[d].append(pd.Series(barrier_labels(
                sub, bars[f"{d}_tp"].to_numpy(float), bars[f"{d}_sl"].to_numpy(float),
                horizon, d)))
    return {
        d: fit_bundle(pd.concat(feats[d], ignore_index=True),
                      pd.concat(lab[d], ignore_index=True), {"direction": d})
        for d in ("long", "short")
    }


def evaluate(pairs, cfg, bundles, window, variant) -> dict:
    name, min_ev, min_r, thr, by_risk = variant
    per_pair, frames = [], []
    for symbol, df in pairs.items():
        sub, trade_from = test_slice(df, window, cfg.strategy.warmup_bars)
        bars = prepare(sub, cfg, **BARRIER_KW)
        f = compute_features(sub, cfg.strategy.atr_period)
        ok = f[FEATURE_COLUMNS].notna().all(axis=1).to_numpy()
        probs = {}
        for d in ("long", "short"):
            p = np.full(len(sub), np.nan)
            if ok.any():
                b = bundles[d]
                p[ok] = (np.full(ok.sum(), b.metadata["const"])
                         if "const" in b.metadata else b.predict_proba(f[ok]))
            probs[d] = p
        r = run_structure_backtest(
            sub, bundles, cfg, symbol, bars, probs["long"], probs["short"],
            min_ev=min_ev, min_r=min_r, prob_threshold=thr,
            size_by_risk=by_risk, trade_from=trade_from,
        )
        per_pair.append(r["summary"])
        if len(r["trades"]):
            frames.append(r["trades"])

    trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out = {
        "wariant": name,
        "transakcje": int(sum(s["n_trades"] for s in per_pair)),
        "wynik_%": float(np.mean([s["total_return_pct"] for s in per_pair])),
        "par+": int(sum(s["total_return_pct"] > 0 for s in per_pair)),
        "sharpe": float(np.mean([s["sharpe"] for s in per_pair])),
    }
    if len(trades):
        notional = trades["qty"] * trades["entry_price"]
        out.update(
            win_pct=float((trades["pnl"] > 0).mean() * 100.0),
            R_sr=float(trades["r_planned"].mean()),
            EV_sr=float(trades["ev_planned"].mean()),
            short_pct=float((trades["side"] == "short").mean() * 100.0),
            brutto_trade=float(((trades["pnl"] + trades["fees"]) / notional).mean() * 100.0),
            netto_trade=float((trades["pnl"] / notional).mean() * 100.0),
        )
    else:
        out.update(win_pct=0.0, R_sr=0.0, EV_sr=0.0, short_pct=0.0,
                   brutto_trade=0.0, netto_trade=0.0)
    return out


class Const:
    """Control bundle with a fixed probability (duck-types ModelBundle)."""
    def __init__(self, value):
        self.feature_columns = FEATURE_COLUMNS
        self.metadata = {"const": value}

    def predict_proba(self, features):
        return np.full(len(features), self.metadata["const"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--window-days", type=int, default=60)
    ap.add_argument("--min-train-bars", type=int, default=1200)
    args = ap.parse_args()

    cfg = with_costs(with_strategy(load_config(), direction="long_short"), *COSTS)
    pairs = load_pairs(cfg)
    horizon = cfg.strategy.horizon_bars
    windows = [Window(i * args.window_days, args.window_days) for i in range(args.windows)]
    windows = [w for w in windows if enough_history(pairs, w, args.min_train_bars)]
    regimes = {
        w.label(): regime_of(
            float(np.mean([buy_hold_pct(df, w) for df in pairs.values()]))
        )
        for w in windows
    }

    span = next(iter(pairs.values()))["timestamp"]
    print(f"pary: {len(pairs)} | historia {span.min():%Y-%m-%d}..{span.max():%Y-%m-%d} | "
          f"okien testowych: {len(windows)} | horyzont {horizon} | "
          f"koszty futures taker (round trip {round_trip_pct(*COSTS):.2f}%)")
    print(f"bariery: SL = dolek {BARRIER_KW['swing_bars']} swiec, "
          f"TP = szczyt {BARRIER_KW['level_bars']} swiec\n")

    rows = []
    for w in windows:
        print(f"okno {w.label()}: trenuje na barierach strukturalnych...", end="", flush=True)
        bundles = train_structure_models(pairs, cfg, w, horizon)
        print(f" (n={bundles['long'].metadata['n_samples']}, "
              f"base long {bundles['long'].metadata['base_rate']:.3f} / "
              f"short {bundles['short'].metadata['base_rate']:.3f})", flush=True)
        for v in VARIANTS:
            rows.append({"okno": w.label(), "rynek": regimes[w.label()],
                         **evaluate(pairs, cfg, bundles, w, v)})
            print(f"    {rows[-1]['wariant']:<32} {rows[-1]['wynik_%']:+6.2f}%  "
                  f"({rows[-1]['transakcje']} tr, R sr {rows[-1]['R_sr']:.2f})", flush=True)
        ctrl = {"long": Const(0.0), "short": Const(1.0)}
        rows.append({"okno": w.label(), "rynek": regimes[w.label()],
                     **evaluate(pairs, cfg, ctrl, w,
                                ("zawsze short (kontrola)", None, 0.0, 0.5, False))})
        print(f"    {rows[-1]['wariant']:<32} {rows[-1]['wynik_%']:+6.2f}%  "
              f"({rows[-1]['transakcje']} tr)", flush=True)

    table = pd.DataFrame(rows)
    out = cfg.paths.models_dir / "reports" / "research_ev_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, default=str))

    def summarize(frame: pd.DataFrame) -> pd.DataFrame:
        return (frame.groupby("wariant", sort=False)
                .agg(okien=("wynik_%", "size"), transakcje=("transakcje", "sum"),
                     R_sr=("R_sr", "mean"), win_pct=("win_pct", "mean"),
                     short_pct=("short_pct", "mean"),
                     brutto_trade=("brutto_trade", "mean"),
                     netto_trade=("netto_trade", "mean"),
                     wynik_sr=("wynik_%", "mean"), wynik_min=("wynik_%", "min"),
                     wynik_max=("wynik_%", "max"),
                     okien_dodatnich=("wynik_%", lambda s: int((s > 0).sum())),
                     sharpe=("sharpe", "mean"))
                .round(3).reset_index())

    print("\n" + "=" * 130)
    print(f"TEST B2 — bariery strukturalne + bramka EV ({len(windows)} okien testowych)")
    print("=" * 130)
    print(summarize(table).to_string(index=False))

    print("\n" + "=" * 130)
    print("PODZIAL WEDLUG TEGO, CO ROBIL RYNEK")
    print("=" * 130)
    for rynek in ("wzrosty", "bok", "spadki"):
        sub = table[table["rynek"] == rynek]
        if sub.empty:
            continue
        print(f"\n### rynek: {rynek}  ({sub['okno'].nunique()} okien)")
        print(summarize(sub).to_string(index=False))
    print(f"\nzapisano: {out}")


if __name__ == "__main__":
    main()
