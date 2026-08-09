"""Compare universes and slot-allocation rules on the *book*, not pair by pair.

    python scripts/book_backtest.py --max-open 3 5

Runs a grid over {configured universe, configured + --add} x {fcfs, best_first} x
{--max-open ...} and prints one table. `scripts/backtest.py` cannot answer this:
it gives every pair its own wallet and unlimited slots, so a wider board can only
ever raise the average. Here the pairs compete, which is what the engine does.
"""

import argparse
import json
import logging

import pandas as pd

from trademon.backtest.book import render_book_report, run_book_backtest
from trademon.config import load_config
from trademon.models.train import load_bundles
from trademon.research.lab import load_pairs
from trademon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("book_backtest")

# The eight pairs under consideration: still top-liquidity on Binance USDT spot, so
# the 2 bps slippage assumption stays as honest as it is for the current ten.
DEFAULT_ADD = ["DOT/USDT", "TRX/USDT", "ATOM/USDT", "BCH/USDT",
               "XLM/USDT", "UNI/USDT", "ETC/USDT", "NEAR/USDT"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--add", nargs="*", default=DEFAULT_ADD,
                        help="pairs to append for the wide arm ('' for none)")
    parser.add_argument("--allocation", nargs="+", default=["fcfs", "best_first"],
                        choices=["fcfs", "best_first"])
    parser.add_argument("--max-open", nargs="+", type=int, default=None,
                        help="position caps to test (default: the configured one)")
    parser.add_argument("--days", type=int, default=None,
                        help="test only the last N days (default: all history)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="override strategy.prob_threshold")
    args = parser.parse_args()

    cfg = load_config()
    if args.threshold is not None:
        cfg = cfg.model_copy(update={
            "strategy": cfg.strategy.model_copy(update={"prob_threshold": args.threshold})
        })
    bundles = load_bundles(cfg.paths.models_dir)
    caps = args.max_open or [cfg.risk.max_open_positions]
    extra = [s for s in (args.add or []) if s and s not in cfg.exchange.symbols]

    universes = [("base", list(cfg.exchange.symbols))]
    if extra:
        universes.append(("wide", list(cfg.exchange.symbols) + extra))

    # Load every frame once; the arms are subsets of the same dict.
    all_symbols = sorted({s for _, u in universes for s in u})
    frames = load_pairs(cfg.model_copy(update={
        "exchange": cfg.exchange.model_copy(update={"symbols": all_symbols})
    }))
    missing = [s for s in all_symbols if s not in frames]
    if missing:
        log.warning("no data for %s — run scripts/download_data.py --symbols %s",
                    ", ".join(missing), " ".join(missing))

    trade_from = None
    if args.days:
        end = max(df["timestamp"].max() for df in frames.values())
        trade_from = end - pd.Timedelta(days=args.days)
        log.info("test window: %s .. %s", trade_from, end)

    results = []
    cache: dict = {}   # features/probabilities are the same in every cell of the grid
    for uname, universe in universes:
        ucfg_exchange = cfg.exchange.model_copy(update={"symbols": universe})
        sub = {s: frames[s] for s in universe if s in frames}
        for cap in caps:
            rcfg = cfg.model_copy(update={
                "exchange": ucfg_exchange,
                "risk": cfg.risk.model_copy(update={"max_open_positions": cap}),
            })
            for allocation in args.allocation:
                log.info("running %s universe (%d pairs), %s, cap %d...",
                         uname, len(sub), allocation, cap)
                r = run_book_backtest(sub, bundles, rcfg, allocation=allocation,
                                      trade_from=trade_from, cache=cache)
                r["summary"]["universe"] = uname
                results.append(r)

    report = render_book_report(results, cfg)
    print(report)

    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    (out_dir / f"book_{stamp}.txt").write_text(report)
    (out_dir / f"book_{stamp}.json").write_text(
        json.dumps([r["summary"] for r in results], indent=2, default=str)
    )
    log.info("report saved to %s", out_dir / f"book_{stamp}.txt")

    log_experiment(cfg.paths.runtime_dir, {
        "kind": "book_backtest",
        "timeframe": cfg.exchange.timeframe,
        "window_days": args.days,
        "strategy": cfg.strategy.model_dump(),
        "runs": [
            {k: s["summary"][k] for k in ("universe", "allocation", "max_open_positions",
                                          "n_symbols", "total_return_pct", "sharpe",
                                          "max_drawdown_pct", "n_trades", "signals",
                                          "slot_blocked")}
            for s in results
        ],
        "report": f"book_{stamp}.txt",
    })


if __name__ == "__main__":
    main()
