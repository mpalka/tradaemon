import numpy as np

from trademon.features.engineering import FEATURE_COLUMNS, compute_features
from trademon.models.train import walk_forward_splits


def test_all_declared_features_are_computed(ohlcv):
    feat = compute_features(ohlcv)
    assert set(FEATURE_COLUMNS) <= set(feat.columns)


def test_no_nans_after_warmup(ohlcv):
    feat = compute_features(ohlcv)
    # longest lookback is the 180-bar regime window
    assert feat[FEATURE_COLUMNS].iloc[200:].notna().all().all()


def test_no_lookahead(ohlcv):
    """A feature at bar t must not change when future bars are appended."""
    full = compute_features(ohlcv)
    truncated = compute_features(ohlcv.iloc[:300].reset_index(drop=True))
    np.testing.assert_allclose(
        full[FEATURE_COLUMNS].iloc[:300].to_numpy(float),
        truncated[FEATURE_COLUMNS].to_numpy(float),
        rtol=1e-9, atol=1e-12, equal_nan=True,
    )


def test_walk_forward_splits_respect_purge():
    purge = 30
    splits = walk_forward_splits(n=10_000, n_folds=5, purge=purge, min_train=2_000)
    assert len(splits) == 5
    for train_idx, test_idx in splits:
        assert len(train_idx) and len(test_idx)
        assert train_idx.max() < test_idx.min() - purge + 1
    # folds together cover the tail of the series exactly once
    all_test = np.concatenate([t for _, t in splits])
    assert len(all_test) == len(np.unique(all_test))
    assert all_test.max() == 9_999
