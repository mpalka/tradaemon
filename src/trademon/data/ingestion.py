"""Historical OHLCV download via CCXT (public endpoints, no API key needed)."""

from __future__ import annotations

import logging
import time

import ccxt
import pandas as pd

from trademon.config import Config
from trademon.data import storage

log = logging.getLogger(__name__)

PAGE_LIMIT = 1000  # Binance max candles per request


def make_exchange(cfg: Config, authenticated: bool = False) -> ccxt.Exchange:
    params: dict = {"enableRateLimit": True}
    if authenticated:
        if not cfg.api_key or not cfg.api_secret:
            raise RuntimeError(
                "Live mode requires EXCHANGE_API_KEY / EXCHANGE_API_SECRET in the environment"
            )
        params["apiKey"] = cfg.api_key
        params["secret"] = cfg.api_secret
    exchange_cls = getattr(ccxt, cfg.exchange.id)
    return exchange_cls(params)


def fetch_ohlcv_range(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int | None = None,
) -> pd.DataFrame:
    """Paginated fetch of closed candles in [since_ms, until_ms)."""
    until_ms = until_ms or exchange.milliseconds()
    step_ms = storage.TIMEFRAME_MS[timeframe]
    rows: list[list[float]] = []
    cursor = since_ms
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=PAGE_LIMIT)
        if not batch:
            break
        rows.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor and len(batch) < PAGE_LIMIT:
            break
        cursor = last_ts + step_ms
        if len(rows) % 50_000 < PAGE_LIMIT:
            log.info("%s: fetched %d candles (up to %s)", symbol, len(rows),
                     pd.Timestamp(last_ts, unit="ms", tz="UTC"))
    df = storage.to_dataframe(rows)
    # Drop the still-open current candle.
    cutoff = pd.Timestamp((until_ms // step_ms) * step_ms, unit="ms", tz="UTC")
    return df[df["timestamp"] < cutoff].reset_index(drop=True)


def download_symbol(cfg: Config, symbol: str, days: int) -> pd.DataFrame:
    """Download/refresh history for one symbol, merge into its Parquet file."""
    exchange = make_exchange(cfg)
    timeframe = cfg.exchange.timeframe
    path = storage.ohlcv_path(cfg.paths.data_dir, cfg.exchange.id, symbol, timeframe)
    existing = storage.load_ohlcv(path)

    now_ms = exchange.milliseconds()
    target_since_ms = now_ms - days * 86_400_000
    step_ms = storage.TIMEFRAME_MS[timeframe]

    t0 = time.time()
    chunks = []
    if existing.empty:
        chunks.append(fetch_ohlcv_range(exchange, symbol, timeframe, target_since_ms, now_ms))
    else:
        first_ms = int(existing["timestamp"].min().timestamp() * 1000)
        last_ms = int(existing["timestamp"].max().timestamp() * 1000)
        if target_since_ms < first_ms - step_ms:  # backfill older history
            chunks.append(
                fetch_ohlcv_range(exchange, symbol, timeframe, target_since_ms, first_ms)
            )
        chunks.append(fetch_ohlcv_range(exchange, symbol, timeframe, last_ms + step_ms, now_ms))
    new = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    merged = storage.merge_ohlcv(existing, new)
    storage.save_ohlcv(merged, path)

    gaps = storage.find_gaps(merged, timeframe)
    log.info(
        "%s: %d new candles in %.1fs, total %d, gaps: %d",
        symbol, len(new), time.time() - t0, len(merged), len(gaps),
    )
    if not gaps.empty:
        log.warning("%s: data gaps detected:\n%s", symbol, gaps.head(10).to_string(index=False))
    return merged
