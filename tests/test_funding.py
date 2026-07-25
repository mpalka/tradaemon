import numpy as np
import pandas as pd

from trademon.data.funding import perp_symbol
from trademon.features.engineering import (
    FUNDING_FEATURE_COLUMNS,
    active_feature_columns,
    compute_features,
)

from .conftest import make_ohlcv


def make_funding(n: int = 120, start="2025-12-01") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="8h", tz="UTC")
    rng = np.random.default_rng(1)
    return pd.DataFrame({"timestamp": ts, "funding_rate": rng.normal(1e-4, 5e-5, n)})


def test_perp_symbol_mapping():
    assert perp_symbol("BTC/USDT") == "BTC/USDT:USDT"
    assert perp_symbol("ETH/USDT:USDT") == "ETH/USDT:USDT"  # already a perp


def test_funding_features_present_and_active_columns():
    df = make_ohlcv(300, start_price=100.0)
    df["timestamp"] = pd.date_range("2025-12-01", periods=len(df), freq="4h", tz="UTC")
    feat = compute_features(df, funding=make_funding())
    assert set(FUNDING_FEATURE_COLUMNS) <= set(feat.columns)
    assert active_feature_columns(True)[-4:] == FUNDING_FEATURE_COLUMNS
    assert "funding_now" not in active_feature_columns(False)


def test_funding_features_no_lookahead():
    """A bar's funding features must not change when later funding arrives."""
    df = make_ohlcv(300, start_price=100.0)
    df["timestamp"] = pd.date_range("2025-12-01", periods=len(df), freq="4h", tz="UTC")
    funding = make_funding(120)
    full = compute_features(df, funding=funding)
    truncated = compute_features(df.iloc[:150].reset_index(drop=True),
                                 funding=funding.iloc[:80])
    np.testing.assert_allclose(
        full[FUNDING_FEATURE_COLUMNS].iloc[:150].to_numpy(float),
        truncated[FUNDING_FEATURE_COLUMNS].to_numpy(float),
        rtol=1e-9, atol=1e-12, equal_nan=True,
    )


def test_no_funding_yields_nan_columns():
    df = make_ohlcv(250, start_price=100.0)
    feat = compute_features(df, funding=pd.DataFrame(columns=["timestamp", "funding_rate"]))
    assert feat[FUNDING_FEATURE_COLUMNS].isna().all().all()
