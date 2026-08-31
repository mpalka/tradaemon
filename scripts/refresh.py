"""Maintenance ritual: refresh data, retrain with a safety gate, promote only
a candidate that passes an honest out-of-sample backtest.

Steps:
  1. Download the latest candles (incremental) for all configured pairs.
  2. Train CANDIDATE models excluding the last `model.validation_days` days.
  3. Backtest the candidate on that held-out window (data it never saw), next
     to naive controls run on the very same bars.
  4. GATE: promote only if the candidate is not catastrophic, beats doing
     nothing, AND beats every naive control. Otherwise keep the current
     production model untouched.

     The gate used to compare against buy & hold. That is nearly free to pass
     in a falling market — a candidate that barely trades returns ~0% and
     "beats" a benchmark that lost 17%, so the gate approved on no evidence.
     Naive controls (always-long, always-short, random, and not trading at all)
     are reachable alternatives, so clearing them means something.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))  # allow `import train`
from train import build_dataset

from tradaemon.backtest.runner import run_backtest
from tradaemon.config import load_config
from tradaemon.data import storage
from tradaemon.data.ingestion import download_symbol
from tradaemon.models.train import train_walk_forward
from tradaemon.research.lab import Window, buy_hold_pct, control_bundles, test_slice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("refresh")

GATE_MIN_RETURN_PCT = -2.0  # reject a candidate whose OOS mean return is worse
# Naive strategies the candidate has to beat on the same bars. They cost nothing
# to build and nothing to run, so a model that cannot clear them has not earned
# a promotion. "nic nie rob" (0%) is added separately in backtest_holdout.
CONTROLS = ("always_long", "always_short", "random")


def write_status(runtime_dir: Path, status: str, detail: str) -> None:
    """Health breadcrumb read by the dashboard's Zdrowie tab."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "refresh_status.json").write_text(json.dumps({
        "timestamp": datetime.now(UTC).isoformat(), "status": status, "detail": detail,
    }))


def backtest_holdout(cfg, bundles, days: int) -> dict:
    """Candidate and naive controls over the held-out window, on identical bars.

    Two things the previous version got wrong, both of which flattered the
    candidate:

    * It sliced exactly `days` of candles and backtested that. Features look
      back up to 180 bars, so in a 60-day window on 4h candles roughly the first
      half has NaN features and cannot trade — the gate judged the candidate on
      about half the sample it appeared to use (42 trades instead of 78). Here
      the slice carries `warmup_bars` of extra history and `trade_from` forbids
      trading inside that prefix, so every bar of the window is live.
    * Its only benchmark was buy & hold. Controls run on the same bars, with the
      same costs and the same direction setting, are a far harder target.
    """
    window = Window(0, days)
    series: dict[str, list[float]] = {name: [] for name in ("kandydat", *CONTROLS)}
    control_trades = dict.fromkeys(CONTROLS, 0)
    bh: list[float] = []
    n_trades = 0

    for symbol in cfg.exchange.symbols:
        path = storage.ohlcv_path(cfg.paths.data_dir, cfg.exchange.id, symbol,
                                  cfg.exchange.timeframe)
        df = storage.load_ohlcv(path)
        if df.empty:
            continue
        sub, trade_from = test_slice(df, window, cfg.strategy.warmup_bars)
        r = run_backtest(sub, bundles, cfg, symbol, trade_from=trade_from)["summary"]
        series["kandydat"].append(r["total_return_pct"])
        n_trades += r["n_trades"]
        for name in CONTROLS:
            c = run_backtest(sub, control_bundles(name), cfg, symbol,
                             trade_from=trade_from)["summary"]
            series[name].append(c["total_return_pct"])
            control_trades[name] += c["n_trades"]
        bh.append(buy_hold_pct(df, window))

    if not series["kandydat"]:
        raise RuntimeError("no pair had data for the held-out window")
    out = {k: float(np.mean(v)) for k, v in series.items()}
    # Not trading at all is the floor any promotion must clear: the gate exists
    # to stop a losing model reaching the engine, and a flat book loses nothing.
    out["nic nie rob"] = 0.0
    out["buy_hold"] = float(np.mean(bh))
    out["n_trades"] = n_trades
    # A control the current `direction` setting forbids never opens a position
    # and scores a flat 0% — always_short under direction: long, for instance.
    # Reported so a 0.000% row is not misread as "shorting broke even".
    out["control_trades"] = control_trades
    return out


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

    log.info("3/5 out-of-sample backtest of the candidate against naive controls...")
    active = {"long": candidate["long"]}
    if cfg.strategy.direction == "long_short":
        active["short"] = candidate["short"]
    res = backtest_holdout(cfg, active, val_days)
    mean_ret = res["kandydat"]
    rivals = {k: res[k] for k in (*CONTROLS, "nic nie rob")}
    # On a tie, name "nic nie rob" rather than a control the direction setting
    # makes unreachable — both score 0%, but only one is a meaningful rival.
    best_name = max(rivals, key=lambda k: (rivals[k], k == "nic nie rob"))
    log.info("candidate OOS %.3f%% on %d trades over last %d days "
             "(buy&hold %.3f%%, for context only)",
             mean_ret, res["n_trades"], val_days, res["buy_hold"])
    for name, val in sorted(rivals.items(), key=lambda kv: -kv[1]):
        trades = res["control_trades"].get(name)
        note = "" if trades is None else f" ({trades} trades)"
        if trades == 0 and name != "nic nie rob":
            note += f" — unreachable with direction: {cfg.strategy.direction}"
        log.info("  control %-14s %+.3f%%%s", name, val, note)

    log.info("4/5 gate...")
    if mean_ret < GATE_MIN_RETURN_PCT or mean_ret <= rivals[best_name]:
        reason = ("catastrophic" if mean_ret < GATE_MIN_RETURN_PCT
                  else f"does not beat '{best_name}'")
        log.warning(
            "GATE FAILED — %s (candidate %+.3f%%, floor %.1f%%, best control "
            "'%s' %+.3f%%) — keeping current production model, nothing promoted",
            reason, mean_ret, GATE_MIN_RETURN_PCT, best_name, rivals[best_name],
        )
        write_status(cfg.paths.runtime_dir, "gate_failed",
                     f"kandydat {mean_ret:+.2f}% nie bije '{best_name}' "
                     f"({rivals[best_name]:+.2f}%) — zachowano stary model")
        return 2

    log.info("5/5 gate passed — retraining final models on all data and promoting...")
    final = train_models(cfg, exclude_last_days=0)
    for direction, bundle in final.items():
        path = bundle.save(cfg.paths.models_dir, name=f"model_{direction}")
        log.info("promoted %s: %s (AUC %.4f)", direction, path,
                 bundle.metadata["mean_auc"] or float("nan"))
    log.info("done — the running engine will hot-reload on its next candle")
    write_status(cfg.paths.runtime_dir, "promoted",
                 f"kandydat {mean_ret:+.2f}% pobil najlepsza kontrole '{best_name}' "
                 f"({rivals[best_name]:+.2f}%) — wypromowano nowy model")
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
