"""Maintenance ritual: refresh data, retrain with a safety gate, promote only
a candidate that passes an honest out-of-sample backtest.

Steps:
  1. Download the latest candles (incremental) for all configured pairs.
  2. Train CANDIDATE models excluding the last `model.validation_days` days.
  3. Backtest the candidate on that held-out window (data it never saw).
  4. GATE: promote only if the candidate is not catastrophic AND still beats
     buy & hold (the strategy's core value is capital protection). Otherwise
     keep the current production model untouched.
  5. On pass, retrain FINAL models on ALL data and save to production names.

The running engine hot-reloads the new model files on its next candle, so no
restart is needed. Run: python scripts/refresh.py

Designed to run unattended (e.g. weekly cron or the Docker `refresher` service).
Exit code 0 = promoted, 2 = gate failed (kept old model), 1 = error.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))  # allow `import train`
from train import build_dataset

from trademon.backtest.runner import run_backtest
from trademon.config import load_config
from trademon.data import storage
from trademon.data.ingestion import download_symbol
from trademon.models.train import train_walk_forward

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("refresh")

GATE_MIN_RETURN_PCT = -2.0  # reject a candidate whose OOS mean return is worse


def write_status(runtime_dir: Path, status: str, detail: str) -> None:
    """Health breadcrumb read by the dashboard's Zdrowie tab."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "refresh_status.json").write_text(json.dumps({
        "timestamp": datetime.now(UTC).isoformat(), "status": status, "detail": detail,
    }))


def backtest_holdout(cfg, bundles, days: int) -> tuple[float, float]:
    """Mean OOS return and mean buy&hold over the last `days` across all pairs."""
    rets, bh = [], []
    for symbol in cfg.exchange.symbols:
        path = storage.ohlcv_path(cfg.paths.data_dir, cfg.exchange.id, symbol,
                                  cfg.exchange.timeframe)
        df = storage.load_ohlcv(path)
        if df.empty:
            continue
        cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
        test = df[df["timestamp"] >= cutoff].reset_index(drop=True)
        r = run_backtest(test, bundles, cfg, symbol)["summary"]
        rets.append(r["total_return_pct"])
        bh.append((test["close"].iloc[-1] / test["open"].iloc[0] - 1.0) * 100.0)
    return float(np.mean(rets)), float(np.mean(bh))


def train_models(cfg, exclude_last_days: int) -> dict:
    bundles = {}
    for direction in ("long", "short"):
        feats, labels, info = build_dataset(
            cfg, cfg.model.train_window_days, exclude_last_days, direction
        )
        b = train_walk_forward(feats, labels, cfg, dataset_info=info)
        b.metadata["direction"] = direction
        bundles[direction] = b
    return bundles


def main() -> int:
    cfg = load_config()
    val_days = cfg.model.validation_days

    log.info("1/5 refreshing data for %d pairs...", len(cfg.exchange.symbols))
    for symbol in cfg.exchange.symbols:
        download_symbol(cfg, symbol, cfg.model.train_window_days)

    log.info("2/5 training candidate (excluding last %d days)...", val_days)
    candidate = train_models(cfg, exclude_last_days=val_days)

    log.info("3/5 out-of-sample backtest of the candidate...")
    active = {"long": candidate["long"]}
    if cfg.strategy.direction == "long_short":
        active["short"] = candidate["short"]
    mean_ret, mean_bh = backtest_holdout(cfg, active, val_days)
    log.info("candidate OOS: %.3f%% vs buy&hold %.3f%% over last %d days",
             mean_ret, mean_bh, val_days)

    log.info("4/5 gate...")
    if mean_ret < GATE_MIN_RETURN_PCT or mean_ret < mean_bh:
        log.warning(
            "GATE FAILED (return %.3f%%, floor %.1f%%, buy&hold %.3f%%) — "
            "keeping current production model, nothing promoted",
            mean_ret, GATE_MIN_RETURN_PCT, mean_bh,
        )
        write_status(cfg.paths.runtime_dir, "gate_failed",
                     f"kandydat {mean_ret:+.2f}% vs B&H {mean_bh:+.2f}% — zachowano stary model")
        return 2

    log.info("5/5 gate passed — retraining final models on all data and promoting...")
    final = train_models(cfg, exclude_last_days=0)
    for direction, bundle in final.items():
        path = bundle.save(cfg.paths.models_dir, name=f"model_{direction}")
        log.info("promoted %s: %s (AUC %.4f)", direction, path,
                 bundle.metadata["mean_auc"] or float("nan"))
    log.info("done — the running engine will hot-reload on its next candle")
    write_status(cfg.paths.runtime_dir, "promoted",
                 f"kandydat {mean_ret:+.2f}% vs B&H {mean_bh:+.2f}% — wypromowano nowy model")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logging.getLogger("refresh").exception("refresh failed")
        try:
            write_status(load_config().paths.runtime_dir, "error", str(exc)[:200])
        except Exception:
            logging.getLogger("refresh").debug("could not write refresh status", exc_info=True)
        sys.exit(1)
