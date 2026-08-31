"""Perpetual-futures funding rate history (Binance), the positioning signal
that pure spot OHLCV cannot see. Funding settles every 8h and is available for
~a year back (unlike open interest, which the free API caps at ~30 days).

A positive funding rate means longs pay shorts (crowded longs -> downside
risk); negative means the reverse. Extremes flag over-leveraged positioning.
"""

from __future__ import annotations

import logging
from pathlib import Path

import ccxt
import pandas as pd

log = logging.getLogger(__name__)

FUNDING_COLUMNS = ["timestamp", "funding_rate"]
PAGE_LIMIT = 1000


def perp_symbol(spot_symbol: str) -> str:
    """Map a spot symbol to its USDT-margined perpetual, e.g. BTC/USDT -> BTC/USDT:USDT."""
    return spot_symbol if ":" in spot_symbol else f"{spot_symbol}:{spot_symbol.split('/')[1]}"


def funding_path(data_dir: Path, exchange_id: str, symbol: str) -> Path:
    safe = symbol.replace("/", "-").replace(":", "_")
    return data_dir / f"{exchange_id}_{safe}_funding.parquet"


def _to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=FUNDING_COLUMNS)
    df = pd.DataFrame(
        {
            "timestamp": [r["timestamp"] for r in rows],
            "funding_rate": [float(r["fundingRate"]) for r in rows],
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def fetch_funding_history(
    exchange: ccxt.Exchange, symbol: str, since_ms: int, until_ms: int | None = None
) -> pd.DataFrame:
    until_ms = until_ms or exchange.milliseconds()
    perp = perp_symbol(symbol)
    rows: list[dict] = []
    cursor = since_ms
    while cursor < until_ms:
        batch = exchange.fetch_funding_rate_history(perp, since=cursor, limit=PAGE_LIMIT)
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1]["timestamp"]
        if last <= cursor and len(batch) < PAGE_LIMIT:
            break
        cursor = last + 1
    return _to_df(rows)


def download_funding(cfg, exchange: ccxt.Exchange, symbol: str, days: int) -> pd.DataFrame:
    """Download/refresh funding history for one symbol into its parquet file."""
    path = funding_path(cfg.paths.data_dir, cfg.exchange.id, symbol)
    existing = load_funding(path)
    now_ms = exchange.milliseconds()
    since_ms = now_ms - days * 86_400_000
    if not existing.empty:
        since_ms = max(since_ms, int(existing["timestamp"].max().timestamp() * 1000) + 1)
    new = fetch_funding_history(exchange, symbol, since_ms, now_ms)
    merged = (
        pd.concat([existing, new], ignore_index=True)
        .drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(path, index=False)
    log.info("%s: %d new funding points, total %d", symbol, len(new), len(merged))
    return merged


def load_funding(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=FUNDING_COLUMNS)
    return pd.read_parquet(path)
