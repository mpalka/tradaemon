"""Model training with walk-forward validation.

Primary model: LightGBM. If lightgbm is unavailable on the host (e.g. missing
libomp on macOS), falls back to sklearn's HistGradientBoostingClassifier,
which needs no native extras and behaves similarly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, roc_auc_score

from tradaemon.config import Config
from tradaemon.features.engineering import FEATURE_COLUMNS

log = logging.getLogger(__name__)


def make_classifier():
    try:
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=31,
            min_child_samples=200,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            verbosity=-1,
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier

        log.warning("lightgbm unavailable, falling back to HistGradientBoostingClassifier")
        return HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.03, min_samples_leaf=200
        )


def walk_forward_splits(
    n: int, n_folds: int, purge: int, min_train: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window splits over positional indices with a purge gap.

    The purge gap (>= label horizon) between train end and test start prevents
    leakage: labels near the train boundary look into bars inside the test set.
    """
    test_size = (n - min_train) // n_folds
    if test_size <= 0:
        raise ValueError(f"Not enough samples ({n}) for {n_folds} folds with min_train={min_train}")
    splits = []
    for i in range(n_folds):
        test_start = min_train + i * test_size
        test_end = n if i == n_folds - 1 else test_start + test_size
        train_end = max(0, test_start - purge)
        splits.append((np.arange(0, train_end), np.arange(test_start, test_end)))
    return splits


@dataclass
class ModelBundle:
    model: object
    feature_columns: list[str]
    metadata: dict

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        x = features[self.feature_columns].to_numpy(float)
        return self.model.predict_proba(x)[:, 1]

    def save(self, models_dir: Path, name: str = "model_latest") -> Path:
        models_dir.mkdir(parents=True, exist_ok=True)
        path = models_dir / f"{name}.joblib"
        joblib.dump({"model": self.model, "feature_columns": self.feature_columns,
                     "metadata": self.metadata}, path)
        (models_dir / f"{name}.json").write_text(json.dumps(self.metadata, indent=2, default=str))
        return path

    @classmethod
    def load(cls, models_dir: Path, name: str = "model_latest") -> ModelBundle:
        payload = joblib.load(models_dir / f"{name}.joblib")
        return cls(payload["model"], payload["feature_columns"], payload["metadata"])


def load_bundles(models_dir: Path) -> dict[str, ModelBundle]:
    """Load direction-keyed bundles: model_long always, model_short if present.

    Falls back to legacy single-model layout (model_latest -> long)."""
    bundles: dict[str, ModelBundle] = {}
    if (models_dir / "model_long.joblib").exists():
        bundles["long"] = ModelBundle.load(models_dir, "model_long")
    elif (models_dir / "model_latest.joblib").exists():
        bundles["long"] = ModelBundle.load(models_dir, "model_latest")
    else:
        raise FileNotFoundError(f"no trained model in {models_dir} — run scripts/train.py")
    if (models_dir / "model_short.joblib").exists():
        bundles["short"] = ModelBundle.load(models_dir, "model_short")
    return bundles


def train_walk_forward(
    features: pd.DataFrame,
    labels: pd.Series,
    cfg: Config,
    dataset_info: dict | None = None,
    feature_columns: list[str] | None = None,
) -> ModelBundle:
    """Walk-forward OOS evaluation, then a final fit on all data."""
    feature_columns = feature_columns or FEATURE_COLUMNS
    mask = labels.notna() & features[feature_columns].notna().all(axis=1)
    x = features.loc[mask, feature_columns].reset_index(drop=True)
    y = labels[mask].astype(int).reset_index(drop=True)
    n = len(x)
    purge = cfg.strategy.horizon_bars
    min_train = max(5_000, n // (cfg.model.n_folds + 1))

    fold_metrics = []
    thr = cfg.strategy.prob_threshold
    for i, (tr_idx, te_idx) in enumerate(
        walk_forward_splits(n, cfg.model.n_folds, purge, min_train)
    ):
        clf = make_classifier()
        clf.fit(x.iloc[tr_idx], y.iloc[tr_idx])
        proba = clf.predict_proba(x.iloc[te_idx])[:, 1]
        y_te = y.iloc[te_idx]
        signals = proba >= thr
        fold_metrics.append(
            {
                "fold": i,
                "train_size": len(tr_idx),
                "test_size": len(te_idx),
                "auc": float(roc_auc_score(y_te, proba)) if y_te.nunique() > 1 else None,
                "base_rate": float(y_te.mean()),
                "signal_rate": float(signals.mean()),
                "precision_at_thr": (
                    float(precision_score(y_te, signals, zero_division=0))
                    if signals.any()
                    else None
                ),
            }
        )
        log.info("fold %d: %s", i, fold_metrics[-1])

    final = make_classifier()
    final.fit(x, y)

    aucs = [m["auc"] for m in fold_metrics if m["auc"] is not None]
    metadata = {
        "trained_at": datetime.now(UTC).isoformat(),
        "n_samples": n,
        "base_rate": float(y.mean()),
        "prob_threshold": thr,
        "mean_auc": float(np.mean(aucs)) if aucs else None,
        "fold_metrics": fold_metrics,
        "feature_columns": feature_columns,
        "strategy": cfg.strategy.model_dump(),
        "dataset": dataset_info or {},
        "model_class": type(final).__name__,
    }
    return ModelBundle(final, feature_columns, metadata)
