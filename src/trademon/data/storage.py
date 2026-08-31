"""OHLCV storage: one Parquet file per (exchange, symbol, timeframe)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

TIMEFRAME_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
    "1d": 86_400_000,
}


def ohlcv_path(data_dir: Path, exchange_id: str, symbol: str, timeframe: str) -> Path:
    safe_symbol = symbol.replace("/", "-")
    return data_dir / f"{exchange_id}_{safe_symbol}_{timeframe}.parquet"


def to_dataframe(raw: list[list[float]]) -> pd.DataFrame:
    """Convert raw CCXT OHLCV rows ([ms, o, h, l, c, v]) to a typed DataFrame."""
    df = pd.DataFrame(raw, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.astype({c: "float64" for c in OHLCV_COLUMNS[1:]})


def save_ohlcv(df: pd.DataFrame, path: Path) -> None:
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def load_ohlcv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    return pd.read_parquet(path)


def merge_ohlcv(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    merged = pd.concat([existing, new], ignore_index=True)
    return merged.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample 1m candles to a higher timeframe (e.g. '5m', '15m')."""
    rule = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h",
            "1d": "1D"}[timeframe]
    out = (
        df.set_index("timestamp")
        .resample(rule, label="left", closed="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["open"])
        .reset_index()
    )
    return out


def find_gaps(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Return rows describing gaps in candle continuity (start, end, missing count)."""
    if len(df) < 2:
        return pd.DataFrame(columns=["gap_start", "gap_end", "missing"])
    step = pd.Timedelta(milliseconds=TIMEFRAME_MS[timeframe])
    ts = df["timestamp"].sort_values().reset_index(drop=True)
    delta = ts.diff()
    gap_idx = delta[delta > step].index
    return pd.DataFrame(
        {
            "gap_start": ts[gap_idx - 1].values,
            "gap_end": ts[gap_idx].values,
            "missing": (delta[gap_idx] / step - 1).astype(int).values,
        }
    )
