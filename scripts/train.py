"""Train the long and short models on downloaded data with walk-forward validation.

Usage: python scripts/train.py [--days 365] [--exclude-last-days 60]

Two symmetric models are always trained and saved (model_long, model_short);
whether the short one is actually used is decided by strategy.direction in
config.yaml.
"""

import argparse
import logging

import pandas as pd

from trademon.config import load_config
from trademon.data import storage
from trademon.features.engineering import compute_atr, compute_features
from trademon.labeling.triple_barrier import triple_barrier_labels
from trademon.models.train import train_walk_forward

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("train")


def build_dataset(
    cfg, days: int | None, exclude_last_days: int = 0, direction: str = "long"
) -> tuple[pd.DataFrame, pd.Series, dict]:
    frames, label_frames, info = [], [], {}
    strat = cfg.strategy
    for symbol in cfg.exchange.symbols:
        path = storage.ohlcv_path(
            cfg.paths.data_dir, cfg.exchange.id, symbol, cfg.exchange.timeframe
        )
        df = storage.load_ohlcv(path)
        if df.empty:
            log.warning("%s: no data at %s — run scripts/download_data.py first", symbol, path)
            continue
        if exclude_last_days:
            # Hold out the most recent days so scripts/backtest.py --days N
            # tests on data the model has never seen.
            holdout = df["timestamp"].max() - pd.Timedelta(days=exclude_last_days)
            df = df[df["timestamp"] < holdout].reset_index(drop=True)
        if days:
            cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
            df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
        feats = compute_features(df, strat.atr_period)
        atr = compute_atr(df, strat.atr_period)
        labels = triple_barrier_labels(
            df, atr, strat.tp_atr_mult, strat.sl_atr_mult, strat.horizon_bars,
            direction=direction,
        )
        frames.append(feats)
        label_frames.append(labels["label"])
        info[symbol] = {
            "bars": len(df),
            "start": str(df["timestamp"].iloc[0]),
            "end": str(df["timestamp"].iloc[-1]),
        }
        log.info("%s [%s]: %d bars, base rate %.3f", symbol, direction, len(df),
                 labels["label"].mean())
    if not frames:
        raise SystemExit("No data — run scripts/download_data.py first")
    features = pd.concat(frames, ignore_index=True)
    labels = pd.concat(label_frames, ignore_index=True)
    return features, labels, info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None,
                        help="limit training data to last N days (default: config window)")
    parser.add_argument("--exclude-last-days", type=int, default=0,
                        help="hold out the most recent N days for an out-of-sample backtest")
    args = parser.parse_args()

    cfg = load_config()
    days = args.days or cfg.model.train_window_days
    for direction in ("long", "short"):
        features, labels, info = build_dataset(cfg, days, args.exclude_last_days, direction)
        bundle = train_walk_forward(features, labels, cfg, dataset_info=info)
        bundle.metadata["direction"] = direction
        path = bundle.save(cfg.paths.models_dir, name=f"model_{direction}")
        log.info("[%s] model saved: %s (mean OOS AUC: %s)",
                 direction, path, bundle.metadata["mean_auc"])


if __name__ == "__main__":
    main()
