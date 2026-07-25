import numpy as np
import pandas as pd
import pytest

from trademon.config import Config
from trademon.features.engineering import FEATURE_COLUMNS


def make_ohlcv(n: int = 500, seed: int = 7, start_price: float = 100.0) -> pd.DataFrame:
    """Synthetic 1m OHLCV random walk with plausible high/low envelopes."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.001, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    spread = np.abs(rng.normal(0, 0.0008, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.uniform(10, 100, n)
    ts = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "open": open_, "high": high, "low": low,
         "close": close, "volume": volume}
    )


class FakeBundle:
    """Model stub that always signals 'enter'."""

    feature_columns = FEATURE_COLUMNS

    def __init__(self, prob: float = 0.99):
        self.prob = prob

    def predict_proba(self, features) -> np.ndarray:
        return np.full(len(features), self.prob)


@pytest.fixture
def cfg() -> Config:
    c = Config()
    c.strategy.warmup_bars = 200  # regime features need a 180-bar lookback
    c.strategy.horizon_bars = 10
    return c


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    return make_ohlcv()
