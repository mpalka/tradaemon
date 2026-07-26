"""Shared plumbing for the research scripts under scripts/research/.

Everything here exists to answer one question honestly: how much of the model's
gross edge survives which cost regime and which barrier geometry. So it enforces
three things ad-hoc scripts keep getting wrong:

1. Strict out-of-sample. A window is defined by (days_back, window_days); the
   model is fit only on bars before the window starts, and only opens positions
   inside it. The test slice still carries `warmup_bars` of history so features
   are not NaN — `trade_from` forbids trading inside that prefix.
2. One cost model. Backtests go through trademon.backtest.runner, which shares
   trademon.execution.fills with the paper/live executor.
3. Controls. 2025-07..2026-07 is a bear market (buy&hold ~ -60%), so any
   short-capable strategy looks good against buy&hold. ConstantBundle gives the
   always-long / always-short / random benchmarks a signal must beat.

Training here does a single fit on the pre-window data (no walk-forward folds):
the held-out window is the out-of-sample measurement, and skipping the folds
makes a multi-cell sweep cheap. Use scripts/train.py when you want fold AUCs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trademon.backtest.runner import run_backtest
from trademon.config import Config
from trademon.data import storage
from trademon.features.engineering import FEATURE_COLUMNS, compute_atr, compute_features
from trademon.labeling.triple_barrier import triple_barrier_labels
from trademon.models.train import ModelBundle, make_classifier


def load_pairs(cfg: Config) -> dict[str, pd.DataFrame]:
    out = {}
    for symbol in cfg.exchange.symbols:
        path = storage.ohlcv_path(
            cfg.paths.data_dir, cfg.exchange.id, symbol, cfg.exchange.timeframe
        )
        df = storage.load_ohlcv(path)
        if not df.empty:
            out[symbol] = df.reset_index(drop=True)
    return out


@dataclass(frozen=True)
class Window:
    """An OOS block ending `days_back` days before the last bar."""
    days_back: int
    window_days: int

    def bounds(self, df: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
        hi = df["timestamp"].max() - pd.Timedelta(days=self.days_back)
        return hi - pd.Timedelta(days=self.window_days), hi

    def label(self) -> str:
        return f"[-{self.days_back + self.window_days}d..-{self.days_back}d]"


def train_slice(df: pd.DataFrame, window: Window) -> pd.DataFrame:
    """Bars strictly before the window — the only data a model may see."""
    lo, _ = window.bounds(df)
    return df[df["timestamp"] < lo].reset_index(drop=True)


def test_slice(df: pd.DataFrame, window: Window, warmup_bars: int) -> tuple[pd.DataFrame, int]:
    """(slice, trade_from): warmup history, then the window itself."""
    lo, hi = window.bounds(df)
    idx = df.index[df["timestamp"] >= lo]
    first = int(idx[0])
    start = max(0, first - warmup_bars)
    sub = df.iloc[start:]
    sub = sub[sub["timestamp"] <= hi].reset_index(drop=True)
    return sub, first - start


def buy_hold_pct(df: pd.DataFrame, window: Window) -> float:
    lo, hi = window.bounds(df)
    w = df[(df["timestamp"] >= lo) & (df["timestamp"] <= hi)]
    if len(w) < 2:
        return float("nan")
    return float((w["close"].iloc[-1] / w["close"].iloc[0] - 1.0) * 100.0)


def regime_of(buy_hold: float, flat_band: float = 5.0) -> str:
    """Label a window by what the market did in it, so results can be split by
    regime instead of averaged over one. Bands are deliberately wide: a 60-day
    move inside +/-5% tells us nothing directional."""
    if buy_hold > flat_band:
        return "wzrosty"
    if buy_hold < -flat_band:
        return "spadki"
    return "bok"


def enough_history(pairs: dict[str, pd.DataFrame], window: Window, min_bars: int) -> bool:
    """True when every pair has at least `min_bars` of pre-window history.

    Guards the oldest windows, where training data would otherwise be too thin
    (or empty for pairs listed late) and the numbers would be noise.
    """
    return all(len(train_slice(df, window)) >= min_bars for df in pairs.values())


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------


@dataclass
class ConstantBundle:
    """Control "model" that ignores features and returns a fixed probability.

    p=1.0 on the long bundle and 0.0 on the short one gives always-long;
    swapped, always-short. A seeded uniform gives a random-entry control with a
    comparable trade count. Duck-types ModelBundle for run_backtest.
    """
    value: float
    feature_columns: list[str]
    metadata: dict
    seed: int | None = None

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        if self.seed is None:
            return np.full(len(features), self.value)
        return np.random.default_rng(self.seed).random(len(features))


def control_bundles(kind: str, seed: int = 7) -> dict[str, ModelBundle]:
    cols, meta = FEATURE_COLUMNS, {"control": kind}
    if kind == "always_long":
        return {"long": ConstantBundle(1.0, cols, meta),
                "short": ConstantBundle(0.0, cols, meta)}
    if kind == "always_short":
        return {"long": ConstantBundle(0.0, cols, meta),
                "short": ConstantBundle(1.0, cols, meta)}
    if kind == "random":
        return {"long": ConstantBundle(0.0, cols, meta, seed=seed),
                "short": ConstantBundle(0.0, cols, meta, seed=seed + 1)}
    raise ValueError(kind)


def build_training_set(
    pairs: dict[str, pd.DataFrame],
    cfg: Config,
    tp_mult: float,
    sl_mult: float,
    horizon: int,
    window: Window,
    direction: str,
) -> tuple[pd.DataFrame, pd.Series]:
    feats, labels = [], []
    for df in pairs.values():
        sub = train_slice(df, window)
        atr = compute_atr(sub, cfg.strategy.atr_period)
        feats.append(compute_features(sub, cfg.strategy.atr_period))
        labels.append(
            triple_barrier_labels(sub, atr, tp_mult, sl_mult, horizon,
                                  direction=direction)["label"]
        )
    return pd.concat(feats, ignore_index=True), pd.concat(labels, ignore_index=True)


def fit_bundle(features: pd.DataFrame, labels: pd.Series, meta: dict) -> ModelBundle:
    mask = labels.notna() & features[FEATURE_COLUMNS].notna().all(axis=1)
    x = features.loc[mask, FEATURE_COLUMNS]
    y = labels[mask].astype(int)
    clf = make_classifier()
    clf.fit(x, y)
    return ModelBundle(clf, FEATURE_COLUMNS,
                       {**meta, "n_samples": int(mask.sum()), "base_rate": float(y.mean())})


def train_for_geometry(
    pairs: dict[str, pd.DataFrame],
    cfg: Config,
    tp_mult: float,
    sl_mult: float,
    horizon: int,
    window: Window,
) -> dict[str, ModelBundle]:
    """Long + short bundles labeled with this TP/SL geometry, pre-window data only."""
    bundles = {}
    for direction in ("long", "short"):
        x, y = build_training_set(pairs, cfg, tp_mult, sl_mult, horizon, window, direction)
        bundles[direction] = fit_bundle(
            x, y, {"direction": direction, "tp_atr_mult": tp_mult, "sl_atr_mult": sl_mult}
        )
    return bundles


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------


def run_oos(
    pairs: dict[str, pd.DataFrame],
    bundles: dict[str, ModelBundle],
    cfg: Config,
    window: Window,
) -> dict:
    """Backtest every pair over the window and aggregate.

    Per-trade figures are a fraction of the trade's own notional, so they are
    comparable across pairs and price levels; `gross` is before fees and
    slippage, `net` after — their difference is the cost drag being studied.
    """
    per_pair, frames, bh = [], [], []
    for symbol, df in pairs.items():
        sub, trade_from = test_slice(df, window, cfg.strategy.warmup_bars)
        r = run_backtest(sub, bundles, cfg, symbol, trade_from=trade_from)
        per_pair.append(r["summary"])
        bh.append(buy_hold_pct(df, window))
        if len(r["trades"]):
            frames.append(r["trades"])

    trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out = {
        "pairs": len(per_pair),
        "n_trades": int(sum(s["n_trades"] for s in per_pair)),
        "mean_return_pct": float(np.mean([s["total_return_pct"] for s in per_pair])),
        "pairs_positive": int(sum(s["total_return_pct"] > 0 for s in per_pair)),
        "mean_sharpe": float(np.mean([s["sharpe"] for s in per_pair])),
        "mean_max_dd_pct": float(np.mean([s["max_drawdown_pct"] for s in per_pair])),
        "buy_hold_pct": float(np.mean(bh)),
    }
    if len(trades):
        notional = trades["qty"] * trades["entry_price"]
        gross = trades["pnl"] + trades["fees"]
        out.update(
            win_rate_pct=float((trades["pnl"] > 0).mean() * 100.0),
            avg_gross_pct=float((gross / notional).mean() * 100.0),
            avg_net_pct=float((trades["pnl"] / notional).mean() * 100.0),
            avg_cost_pct=float((trades["fees"] / notional).mean() * 100.0),
            short_share_pct=float((trades["side"] == "short").mean() * 100.0),
            exits=trades["exit_reason"].value_counts().to_dict(),
        )
    else:
        out.update(win_rate_pct=0.0, avg_gross_pct=0.0, avg_net_pct=0.0,
                   avg_cost_pct=0.0, short_share_pct=0.0, exits={})
    return out


def with_costs(
    cfg: Config, taker: float, maker: float, slippage_bps: float, order_style: str = "taker"
) -> Config:
    return cfg.model_copy(update={
        "costs": cfg.costs.model_copy(update={
            "taker_fee": taker, "maker_fee": maker, "slippage_bps": slippage_bps,
        }),
        "execution": cfg.execution.model_copy(update={"order_style": order_style}),
    })


def with_strategy(cfg: Config, **overrides) -> Config:
    return cfg.model_copy(update={"strategy": cfg.strategy.model_copy(update=overrides)})


# Binance USDⓈ-M futures VIP0 is 0.0500%/0.0200%; the BNB row applies the 10%
# pay-with-BNB discount. The zero row is not a tradable regime — it is the gross
# edge, the ceiling any cost schedule is measured against.
COST_SCENARIOS = [
    ("spot taker (obecny config)", 0.0010, 0.0010, 2.0, "taker"),
    ("spot maker", 0.0010, 0.0010, 2.0, "maker"),
    ("futures taker VIP0", 0.0005, 0.0002, 2.0, "taker"),
    ("futures taker + BNB -10%", 0.00045, 0.00018, 2.0, "taker"),
    ("futures maker VIP0", 0.0005, 0.0002, 2.0, "maker"),
    ("bez kosztow (sufit)", 0.0, 0.0, 0.0, "taker"),
]


def round_trip_pct(taker: float, maker: float, slippage_bps: float, style: str) -> float:
    if style == "maker":
        return 2.0 * maker * 100.0
    return 2.0 * (taker + slippage_bps / 10_000.0) * 100.0
