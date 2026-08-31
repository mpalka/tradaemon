"""Backtest the portfolio rebalancer on free daily ETF data (Yahoo Finance).

Usage: python scripts/portfolio_backtest.py [--no-download] [--years N] [--ter 0.1] [--trend]
Downloads/refreshes the configured basket, runs a cost-aware daily backtest against
a buy & hold benchmark, prints and saves a report, and records the run in the shared
experiment log so it is never re-derived.
"""

import argparse
import json
import logging

import pandas as pd

from tradaemon import i18n
from tradaemon.portfolio.backtest import render_portfolio_report, run_portfolio_backtest
from tradaemon.portfolio.config import load_portfolio_config
from tradaemon.portfolio.data import download_etf, load_panel
from tradaemon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("portfolio_backtest")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-download", action="store_true",
                        help="use cached data instead of refreshing from Stooq")
    parser.add_argument("--years", type=int, default=None,
                        help="limit the backtest to the last N years")
    parser.add_argument("--ter", type=float, default=0.0,
                        help="annual expense ratio %% to charge (default 0)")
    parser.add_argument("--trend", action="store_true",
                        help="enable the trend/momentum filter for this run")
    args = parser.parse_args()

    cfg = load_portfolio_config()
    i18n.init(getattr(cfg, "display_language", None))
    if args.trend:
        cfg = cfg.model_copy(update={"trend": cfg.trend.model_copy(update={"enabled": True})})

    if not args.no_download:
        log.info("refreshing %d symbols from Yahoo Finance...", len(cfg.symbols))
        for symbol in cfg.symbols:
            download_etf(cfg.paths.data_dir, symbol)

    panel = load_panel(cfg.paths.data_dir, cfg.symbols)
    if panel.empty:
        log.warning("no aligned price data — check the tickers in config/portfolio.yaml")
        return
    if args.years:
        cutoff = panel.index.max() - pd.Timedelta(days=365 * args.years)
        panel = panel[panel.index >= cutoff]

    result = run_portfolio_backtest(panel, cfg, annual_ter_pct=args.ter)
    report = render_portfolio_report(result)
    print(report)

    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    (out_dir / f"portfolio_{stamp}.txt").write_text(report)
    (out_dir / f"portfolio_{stamp}.json").write_text(
        json.dumps(result["summary"], indent=2, default=str))
    if len(result["trades"]):
        result["trades"].to_csv(out_dir / f"portfolio_rebalances_{stamp}.csv", index=False)
    log.info("report saved to %s (txt, json, rebalances csv)", out_dir)

    s = result["summary"]
    log_experiment(cfg.paths.runtime_dir, {
        "kind": "portfolio",
        "timeframe": "1d",
        "window_days": s["period"]["bars"],
        "pairs": len(s["symbols"]),
        "strategy": {"weights": s["target_weights"], "trend": cfg.trend.model_dump(),
                     "rebalance": cfg.rebalance.model_dump()},
        "mean_return_pct": s["total_return_pct"],
        "benchmark_return_pct": s["benchmark_return_pct"],
        "excess_return_pct": s["excess_return_pct"],
        "total_trades": s["n_transactions"],
        "report": f"portfolio_{stamp}.txt",
    })


if __name__ == "__main__":
    main()
