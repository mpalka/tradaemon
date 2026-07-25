"""Paper engine for the portfolio manager: once a day, refresh daily ETF prices,
feed the latest closed day to the book, persist. Slow by design — rebalancing is
idempotent within a day, so a periodic loop is safe (re-running the same day is a
no-op). Run: `python -m trademon.portfolio` (or `--once` for a single step).
"""

from __future__ import annotations

import logging
import time

from trademon.engine.state import RuntimeStore
from trademon.portfolio.book import PortfolioBook
from trademon.portfolio.config import PortfolioConfig, load_portfolio_config
from trademon.portfolio.data import download_etf, load_panel

log = logging.getLogger(__name__)

SLEEP_SECONDS = 6 * 3600  # re-check a few times a day; same-day rebalance is a no-op


class PortfolioEngine:
    def __init__(self, cfg: PortfolioConfig, book: PortfolioBook | None = None):
        self.cfg = cfg
        self.book = book or PortfolioBook(
            cfg.book_name, cfg, RuntimeStore(cfg.runtime_dir / cfg.book_name))

    def refresh_data(self) -> None:
        for symbol in self.cfg.symbols:
            try:
                download_etf(self.cfg.paths.data_dir, symbol)
            except Exception:
                log.exception("%s: daily data refresh failed (keeping cached)", symbol)

    def step(self) -> None:
        panel = load_panel(self.cfg.paths.data_dir, self.cfg.symbols)
        if panel.empty:
            log.warning("no aligned price data yet — run a data refresh first")
            return
        last_date = panel.index[-1].to_pydatetime()
        prices = {s: float(panel.iloc[-1][s]) for s in self.cfg.symbols}
        self.book.on_day(last_date, prices, panel)
        log.info("processed %s: equity=%.2f", last_date.date(), self.book.equity())

    def run_once(self) -> None:
        self.book.restore()
        self.refresh_data()
        self.step()

    def backfill(self) -> None:
        """Replay the full real daily history once, so a fresh book's equity curve
        reflects how this exact strategy would have run since the basket's start.
        Not synthetic — the actual historical daily closes through the same logic."""
        self.refresh_data()
        panel = load_panel(self.cfg.paths.data_dir, self.cfg.symbols)
        if panel.empty:
            log.warning("no data to backfill")
            return
        for i, ts in enumerate(panel.index):
            prices = {s: float(panel.iloc[i][s]) for s in self.cfg.symbols}
            self.book.on_day(ts.to_pydatetime(), prices, panel.iloc[: i + 1])
        log.info("backfilled %d days: equity=%.2f", len(panel), self.book.equity())

    def run(self) -> None:
        self.book.restore()
        log.info("portfolio engine running (paper): book '%s' on %s",
                 self.book.name, self.cfg.symbols)
        while True:
            try:
                self.refresh_data()
                self.step()
            except Exception:
                log.exception("portfolio step failed, retrying next cycle")
            time.sleep(SLEEP_SECONDS)


def main(argv: list[str] | None = None) -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Trademon portfolio manager (paper)")
    parser.add_argument("--once", action="store_true",
                        help="run a single daily step and exit")
    parser.add_argument("--backfill", action="store_true",
                        help="replay full real daily history once (fresh book), then exit")
    args = parser.parse_args(argv)

    cfg = load_portfolio_config()
    engine = PortfolioEngine(cfg)
    if args.backfill:
        engine.backfill()
    elif args.once:
        engine.run_once()
    else:
        engine.run()


if __name__ == "__main__":
    main()
