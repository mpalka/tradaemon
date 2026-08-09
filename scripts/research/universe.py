"""Does a wider board help the *book*, and does ranking the candidates help?

Two questions the existing tooling cannot answer:

* `scripts/backtest.py` and the promotion gate give every pair its own wallet and
  unlimited slots, so adding pairs can only raise the average. The book has one
  wallet and `max_open_positions` slots.
* a full-history run of `scripts/book_backtest.py` uses the shipped model, which
  was fitted on that same history — it scores in the tens of thousands of percent
  and means nothing.

So this script does what scripts/research/ exists for: a model per window, fitted
only on bars before it, and the arms measured on the window itself.

Four arms per window: {10 pairs, 18 pairs} x {fcfs, best_first}. The two universes
get **separate models**, each trained on its own pool of pairs, because widening
the board also widens the training set — that is part of the change, not a
confound to be held fixed.

    python scripts/research/universe.py --windows 4 --window-days 120
"""

import argparse
import json
import logging

import numpy as np
import pandas as pd

from trademon.backtest.book import run_book_backtest
from trademon.config import load_config
from trademon.research.lab import Window, buy_hold_pct, load_pairs, train_for_geometry
from trademon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("universe")

ADD = ["DOT/USDT", "TRX/USDT", "ATOM/USDT", "BCH/USDT",
       "XLM/USDT", "UNI/USDT", "ETC/USDT", "NEAR/USDT"]

# The narrow arm is pinned here, not read from config.exchange.symbols. It used to
# be read from there, and that made the study destroy itself the moment its own
# conclusion was adopted: with the wide board in config.yaml, "base" and "wide"
# became the same eighteen pairs and the script printed a tidy table of a thing
# compared with itself, all four rows identical to the last decimal. A comparison
# has to keep its own definition of what it is comparing.
BASE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "LINK/USDT", "AVAX/USDT", "LTC/USDT"]


def window_frames(pairs: dict[str, pd.DataFrame], window: Window,
                  warmup_bars: int) -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    """Frames cut to warmup + window, and the timestamp trading may start at.

    The pairs no longer share a row index once they are traded jointly, so the
    warmup prefix is expressed as a timestamp rather than test_slice's integer.
    """
    out = {}
    lo = hi = None
    for symbol, df in pairs.items():
        w_lo, w_hi = window.bounds(df)
        lo = w_lo if lo is None else min(lo, w_lo)
        hi = w_hi if hi is None else max(hi, w_hi)
    for symbol, df in pairs.items():
        idx = df.index[df["timestamp"] >= lo]
        if not len(idx):
            continue
        start = max(0, int(idx[0]) - warmup_bars)
        sub = df.iloc[start:]
        sub = sub[sub["timestamp"] <= hi].reset_index(drop=True)
        if len(sub) > warmup_bars:
            out[symbol] = sub
    return out, lo


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=int, default=4, help="how many OOS blocks")
    parser.add_argument("--window-days", type=int, default=120)
    parser.add_argument("--max-open", nargs="+", type=int, default=None)
    parser.add_argument("--base", nargs="+", default=BASE,
                        help="the narrow arm (default: the ten pairs traded before 0.1.11)")
    parser.add_argument("--add", nargs="+", default=ADD,
                        help="pairs the wide arm adds on top of --base")
    args = parser.parse_args()

    cfg = load_config()
    strat = cfg.strategy
    caps = args.max_open or [cfg.risk.max_open_positions]
    base_symbols = list(args.base)
    wide_symbols = base_symbols + [s for s in args.add if s not in base_symbols]
    if wide_symbols == base_symbols:
        raise SystemExit("--add adds nothing to --base: there is no comparison to run")

    all_pairs = load_pairs(cfg.model_copy(update={
        "exchange": cfg.exchange.model_copy(update={"symbols": wide_symbols})
    }))
    universes = {
        "base": {s: all_pairs[s] for s in base_symbols if s in all_pairs},
        "wide": {s: all_pairs[s] for s in wide_symbols if s in all_pairs},
    }
    log.info("universes: base=%d pairs, wide=%d pairs",
             len(universes["base"]), len(universes["wide"]))

    windows = [Window(i * args.window_days, args.window_days)
               for i in range(args.windows)]
    rows = []
    for window in windows:
        bh = float(np.mean([buy_hold_pct(df, window) for df in universes["base"].values()]))
        log.info("window %s (buy&hold %+.1f%%)", window.label(), bh)
        for uname, pairs in universes.items():
            log.info("  training on %d pairs, pre-window data only...", len(pairs))
            bundles = train_for_geometry(pairs, cfg, strat.tp_atr_mult,
                                         strat.sl_atr_mult, int(strat.horizon_bars), window)
            frames, trade_from = window_frames(pairs, window, strat.warmup_bars)
            ucfg = cfg.model_copy(update={
                "exchange": cfg.exchange.model_copy(update={"symbols": list(pairs)})
            })
            cache: dict = {}
            for cap in caps:
                rcfg = ucfg.model_copy(update={
                    "risk": cfg.risk.model_copy(update={"max_open_positions": cap})
                })
                for allocation in ("fcfs", "best_first"):
                    s = run_book_backtest(frames, bundles, rcfg, allocation=allocation,
                                          trade_from=trade_from, cache=cache)["summary"]
                    rows.append({
                        "window": window.label(), "buy_hold_pct": bh,
                        "universe": uname, "n_symbols": s["n_symbols"],
                        "allocation": allocation, "max_open": cap,
                        "return_pct": s["total_return_pct"], "sharpe": s["sharpe"],
                        "max_dd_pct": s["max_drawdown_pct"], "trades": s["n_trades"],
                        "slot_blocked": s["slot_blocked"],
                        "time_in_market_pct": s.get("time_in_market_pct", 0.0),
                    })
                    log.info("    %-4s %-10s cap %d: %+7.2f%% (%d transakcji)",
                             uname, allocation, cap, s["total_return_pct"], s["n_trades"])

    df = pd.DataFrame(rows)
    print()
    print("=" * 92)
    print("PLANSZA I PRZYDZIAŁ SLOTÓW — strict OOS, model trenowany osobno przed każdym oknem")
    print("=" * 92)
    print(df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    agg = (df.groupby(["universe", "allocation", "max_open"])
             .agg(sredni_wynik=("return_pct", "mean"),
                  mediana=("return_pct", "median"),
                  okna_dodatnie=("return_pct", lambda s: int((s > 0).sum())),
                  okien=("return_pct", "size"),
                  sredni_sharpe=("sharpe", "mean"),
                  transakcje=("trades", "sum"),
                  bez_slotu=("slot_blocked", "sum"))
             .reset_index())
    print()
    print("ŚREDNIA PO OKNACH")
    print(agg.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print("=" * 92)

    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "research_universe.json").write_text(
        json.dumps({"per_window": rows, "mean": agg.to_dict("records")},
                   indent=2, default=str)
    )
    log_experiment(cfg.paths.runtime_dir, {
        "kind": "universe_grid",
        "windows": [w.label() for w in windows],
        "strategy": strat.model_dump(),
        "mean": agg.to_dict("records"),
        "report": "research_universe.json",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
