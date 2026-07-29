"""One daily close-price panel format for both markets, so the ranking logic never
has to know whether it is looking at crypto or ETFs.

Crypto comes from Binance via CCXT (public API, no key); ETFs from Yahoo via the
module-2 adapter. Both land in the same Parquet layout and come back as a DataFrame
indexed by date with one column per symbol.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from trademon.data import storage
from trademon.portfolio.data import download_etf
from trademon.portfolio.data import load_panel as load_yahoo_panel

log = logging.getLogger(__name__)

TIMEFRAME = "1d"
CRYPTO_SOURCE = "binance"


def crypto_path(data_dir: Path, symbol: str) -> Path:
    return storage.ohlcv_path(data_dir, CRYPTO_SOURCE, symbol, TIMEFRAME)


def download_crypto_daily(data_dir: Path, symbol: str, days: int = 2000) -> pd.DataFrame:
    """Fetch daily candles for one pair and merge into its Parquet file. Imported
    lazily so the module stays importable (and testable) without ccxt configured."""
    import ccxt

    from trademon.data.ingestion import fetch_ohlcv_range

    exchange = ccxt.binance({"enableRateLimit": True})
    now_ms = exchange.milliseconds()
    df = fetch_ohlcv_range(exchange, symbol, TIMEFRAME,
                           now_ms - days * 86_400_000, now_ms)
    path = crypto_path(data_dir, symbol)
    merged = storage.merge_ohlcv(storage.load_ohlcv(path), df)
    storage.save_ohlcv(merged, path)
    return merged


def load_crypto_panel(data_dir: Path, symbols: list[str]) -> pd.DataFrame:
    """Aligned daily close panel for crypto pairs, same shape as the Yahoo one."""
    series: dict[str, pd.Series] = {}
    for sym in symbols:
        df = storage.load_ohlcv(crypto_path(data_dir, sym))
        if not df.empty:
            series[sym] = df.set_index("timestamp")["close"].sort_index()
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index().ffill()


def load_market_panel(data_dir: Path, market: str, symbols: list[str],
                      min_names: int = 10) -> pd.DataFrame:
    """Daily close panel for `market`, restricted to the period where enough names
    have data.

    Cross-sectional ranking must not silently compare a 25-name universe in one
    period against a 3-name one in another, so instead of dropping every row with any
    gap (which would truncate the history to the youngest asset's listing date) this
    keeps rows with at least `min_names` names and ranks whatever is present.
    """
    if market == "crypto":
        panel = load_crypto_panel(data_dir, symbols)
    elif market == "etf":
        panel = load_yahoo_panel(data_dir, symbols)
    else:
        raise ValueError(f"unknown market {market!r} (expected 'crypto' or 'etf')")
    if panel.empty:
        return panel
    available = [s for s in symbols if s in panel.columns]
    panel = panel[available]
    return panel[panel.notna().sum(axis=1) >= min_names]


def refresh_market(data_dir: Path, market: str, symbols: list[str]) -> dict[str, int]:
    """Download/refresh daily history for a whole universe. Returns rows per symbol;
    a symbol that fails (delisted, renamed) is logged and skipped rather than
    aborting the study."""
    rows: dict[str, int] = {}
    for sym in symbols:
        try:
            df = (download_crypto_daily(data_dir, sym) if market == "crypto"
                  else download_etf(data_dir, sym))
            rows[sym] = len(df)
        except Exception as exc:  # noqa: BLE001 - one dead ticker must not abort the study
            log.warning("%s (%s): download failed, skipping — %s", sym, market, exc)
    return rows
