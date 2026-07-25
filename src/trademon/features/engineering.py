"""Feature engineering on 1m OHLCV. Every feature uses only past data
(rolling / ewm / shift), so a feature value at bar t never changes when
future bars arrive — verified by tests/test_features.py."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR in price units."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


def compute_funding_features(
    df: pd.DataFrame, funding: pd.DataFrame
) -> pd.DataFrame:
    """Funding-rate features aligned as-of each OHLCV bar (no look-ahead).

    Rolling stats are computed on the 8h funding series, then merged onto the
    bars with merge_asof(direction="backward") so a bar only ever sees funding
    that had already settled by its timestamp.
    """
    out = pd.DataFrame(index=df.index)
    if funding is None or funding.empty:
        for col in FUNDING_FEATURE_COLUMNS:
            out[col] = np.nan
        return out

    fr = funding.sort_values("timestamp").reset_index(drop=True).copy()
    rate = fr["funding_rate"]
    fr["funding_now"] = rate
    fr["funding_mean9"] = rate.rolling(9).mean()          # ~3 days of funding
    std9 = rate.rolling(9).std()
    fr["funding_z"] = (rate - fr["funding_mean9"]) / std9.replace(0.0, np.nan)
    fr["funding_cum9"] = rate.rolling(9).sum()

    bars = df[["timestamp"]].reset_index()
    merged = pd.merge_asof(
        bars.sort_values("timestamp"),
        fr[["timestamp", *FUNDING_FEATURE_COLUMNS]],
        on="timestamp", direction="backward",
    ).set_index("index").reindex(df.index)
    for col in FUNDING_FEATURE_COLUMNS:
        out[col] = merged[col].values
    return out


def compute_features(
    df: pd.DataFrame, atr_period: int = 14, funding: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Return a feature DataFrame aligned with df (same index).

    Rows within the warmup window contain NaNs — callers must drop them
    (cfg.strategy.warmup_bars covers the longest lookback used here).
    """
    close = df["close"]
    logc = np.log(close)
    feat = pd.DataFrame(index=df.index)

    for lag in (1, 3, 5, 15, 30, 60):
        feat[f"ret_{lag}"] = logc.diff(lag)

    ret1 = logc.diff(1)
    feat["vol_15"] = ret1.rolling(15).std()
    feat["vol_60"] = ret1.rolling(60).std()
    feat["vol_ratio"] = feat["vol_15"] / feat["vol_60"]

    feat["rsi_14"] = compute_rsi(close, 14)
    feat["atr_norm"] = compute_atr(df, atr_period) / close

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    feat["ema_9_21"] = ema9 / ema21 - 1.0
    feat["close_ema50"] = close / ema50 - 1.0

    vol = df["volume"]
    vol_mean = vol.rolling(60).mean()
    vol_std = vol.rolling(60).std()
    feat["volume_z"] = (vol - vol_mean) / vol_std.replace(0.0, np.nan)

    bar_range = (df["high"] - df["low"]).replace(0.0, np.nan)
    feat["range_norm"] = (df["high"] - df["low"]) / close
    feat["range_norm_15"] = feat["range_norm"].rolling(15).mean()
    feat["body_ratio"] = (df["close"] - df["open"]) / bar_range

    hour = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60.0
    feat["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    feat["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    feat["dow"] = df["timestamp"].dt.dayofweek.astype(float)

    # Regime context: longer lookbacks that describe the market backdrop
    # rather than the last few bars. Windows are in bars — on the 4h
    # timeframe 42 bars ~ 1 week, 180 bars ~ 30 days.
    sma42 = close.rolling(42).mean()
    sma180 = close.rolling(180).mean()
    feat["trend_42"] = close / sma42 - 1.0
    feat["trend_180"] = close / sma180 - 1.0
    feat["mom_42"] = logc.diff(42)
    feat["mom_180"] = logc.diff(180)
    feat["vol_regime"] = ret1.rolling(42).std() / ret1.rolling(180).std()
    feat["dd_180"] = close / close.rolling(180).max() - 1.0

    if funding is not None:
        for col, series in compute_funding_features(df, funding).items():
            feat[col] = series

    return feat


FEATURE_COLUMNS: list[str] = [
    "ret_1", "ret_3", "ret_5", "ret_15", "ret_30", "ret_60",
    "vol_15", "vol_60", "vol_ratio",
    "rsi_14", "atr_norm",
    "ema_9_21", "close_ema50",
    "volume_z",
    "range_norm", "range_norm_15", "body_ratio",
    "hour_sin", "hour_cos", "dow",
    "trend_42", "trend_180", "mom_42", "mom_180", "vol_regime", "dd_180",
]

FUNDING_FEATURE_COLUMNS: list[str] = [
    "funding_now", "funding_mean9", "funding_z", "funding_cum9",
]


def active_feature_columns(use_funding: bool) -> list[str]:
    """Feature list for training; the model bundle stores its own copy so
    backtest/engine read it from there at inference time."""
    return FEATURE_COLUMNS + (FUNDING_FEATURE_COLUMNS if use_funding else [])
