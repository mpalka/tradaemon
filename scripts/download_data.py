"""Download 1m OHLCV history for the configured symbols into Parquet files.

Usage: python scripts/download_data.py --days 365
"""

import argparse
import logging

from tradaemon.config import load_config
from tradaemon.data.ingestion import download_symbol

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365, help="how many days back")
    parser.add_argument("--symbols", nargs="*", default=None, help="override config symbols")
    args = parser.parse_args()

    cfg = load_config()
    symbols = args.symbols or cfg.exchange.symbols
    for symbol in symbols:
        download_symbol(cfg, symbol, args.days)


if __name__ == "__main__":
    main()
