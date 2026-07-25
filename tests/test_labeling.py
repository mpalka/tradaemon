import numpy as np
import pandas as pd

from trademon.labeling.triple_barrier import triple_barrier_labels


def make_flat_df(n: int, price: float = 100.0) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "open": [price] * n, "high": [price] * n,
         "low": [price] * n, "close": [price] * n, "volume": [1.0] * n}
    )


def label_scenario(df: pd.DataFrame, horizon: int = 5):
    atr = pd.Series(1.0, index=df.index)  # tp = entry+2, sl = entry-1
    return triple_barrier_labels(df, atr, tp_mult=2.0, sl_mult=1.0, horizon=horizon)


def test_tp_hit_first_is_label_one():
    df = make_flat_df(20)
    df.loc[3, "high"] = 102.5  # bar t=3 touches tp for entries at t in {1, 2}
    out = label_scenario(df)
    assert out.loc[1, "label"] == 1.0
    assert out.loc[1, "hit_step"] == 1.0  # bar t+2 -> step k=1
    assert out.loc[2, "label"] == 1.0
    assert out.loc[0, "label"] == 1.0  # bar 3 is step k=2 within bar 0's horizon


def test_sl_hit_first_is_label_zero():
    df = make_flat_df(20)
    df.loc[3, "low"] = 98.5
    df.loc[5, "high"] = 102.5  # tp later than sl
    out = label_scenario(df)
    assert out.loc[1, "label"] == 0.0


def test_same_bar_both_barriers_is_conservative_sl():
    df = make_flat_df(20)
    df.loc[3, "high"] = 103.0
    df.loc[3, "low"] = 98.0
    out = label_scenario(df)
    assert out.loc[2, "label"] == 0.0


def test_timeout_is_label_zero_with_nan_step():
    df = make_flat_df(20)
    out = label_scenario(df)
    assert out.loc[5, "label"] == 0.0
    assert np.isnan(out.loc[5, "hit_step"])


def test_tail_without_full_horizon_is_nan():
    df = make_flat_df(20)
    out = label_scenario(df, horizon=5)
    assert out["label"].iloc[-6:].isna().all()
    assert out["label"].iloc[:-6].notna().all()
