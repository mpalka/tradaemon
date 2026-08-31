"""Backtest the saved model on held-out (most recent) data.

Usage: python scripts/backtest.py [--days 14]
By default tests on the last `model.validation_days` from config — data the
walk-forward training folds treat as out-of-sample only if you trained with
an earlier cutoff; for a strict OOS test download fresh data after training.
"""

import argparse
import json
import logging

import numpy as np
import pandas as pd

from trademon import i18n
from trademon.backtest.runner import render_html_report, render_report, run_backtest
from trademon.config import load_config
from trademon.data import storage
from trademon.models.train import load_bundles
from trademon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("backtest")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="test window (last N days)")
    args = parser.parse_args()

    cfg = load_config()
    i18n.init(getattr(cfg, "display_language", None))
    days = args.days or cfg.model.validation_days
    bundles = load_bundles(cfg.paths.models_dir)

    results = []
    for symbol in cfg.exchange.symbols:
        path = storage.ohlcv_path(
            cfg.paths.data_dir, cfg.exchange.id, symbol, cfg.exchange.timeframe
        )
        df = storage.load_ohlcv(path)
        if df.empty:
            log.warning("%s: no data, skipping", symbol)
            continue
        cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
        df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
        results.append(run_backtest(df, bundles, cfg, symbol))

    if not results:
        log.warning("no data for any pair — run scripts/download_data.py first")
        return

    report = render_report(results, cfg)
    print(report)

    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    (out_dir / f"backtest_{stamp}.txt").write_text(report)
    (out_dir / f"backtest_{stamp}.json").write_text(
        json.dumps([r["summary"] for r in results], indent=2, default=str)
    )
    (out_dir / f"backtest_{stamp}.html").write_text(render_html_report(results, cfg))
    for r in results:
        sym = r["summary"]["symbol"].replace("/", "-")
        r["trades"].to_csv(out_dir / f"trades_{sym}_{stamp}.csv", index=False)
    log.info("report saved to %s (txt, json, html, per-pair csv)", out_dir)

    # Record this run in the experiment log so it is never re-derived.
    mean_ret = float(np.mean([r["summary"]["total_return_pct"] for r in results]))
    log_experiment(cfg.paths.runtime_dir, {
        "kind": "backtest",
        "timeframe": cfg.exchange.timeframe,
        "window_days": days,
        "pairs": len(results),
        "strategy": cfg.strategy.model_dump(),
        "mean_return_pct": mean_ret,
        "total_trades": int(sum(r["summary"]["n_trades"] for r in results)),
        "report": f"backtest_{stamp}.html",
    })


if __name__ == "__main__":
    main()
