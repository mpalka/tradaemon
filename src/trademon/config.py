"""Typed configuration loaded from config/config.yaml (+ .env for secrets)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ExchangeConfig(BaseModel):
    id: str = "binance"
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT"])
    timeframe: str = "1m"


class PathsConfig(BaseModel):
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    runtime_dir: Path = Path("runtime")

    def resolve(self, root: Path) -> PathsConfig:
        return PathsConfig(
            data_dir=root / self.data_dir,
            models_dir=root / self.models_dir,
            runtime_dir=root / self.runtime_dir,
        )


class CostsConfig(BaseModel):
    taker_fee: float = 0.001
    maker_fee: float = 0.001
    slippage_bps: float = 2.0

    @property
    def slippage(self) -> float:
        return self.slippage_bps / 10_000.0


class StrategyConfig(BaseModel):
    atr_period: int = 14
    tp_atr_mult: float = 2.0
    sl_atr_mult: float = 1.0
    horizon_bars: int = 30
    prob_threshold: float = 0.60
    warmup_bars: int = 300
    # long: only bet on price rising (spot-compatible).
    # long_short: also open shorts on down-signals. NOTE: real short selling
    #   needs a Binance futures/margin account (spot cannot short); backtest
    #   and paper trading simulate it freely, live short is not wired.
    direction: Literal["long", "long_short"] = "long"
    # When a position hits its deadline while the model still signals its side
    # above the threshold, extend it (rebase TP/SL on the current close and ATR,
    # fresh deadline) instead of closing and reopening on the same bar — the
    # round trip pays double fees and slippage to keep holding the same coins.
    rollover: bool = False
    # Bars to wait before re-entering a pair the book just closed. 0 keeps the
    # current behaviour: an exit and a fresh entry can land on the same candle.
    # 1 makes the book sit out that candle. The question it exists to answer is
    # whether an immediate re-entry earns its two fees, or whether it is the same
    # bet re-established at a cost — the features barely move inside one bar, so
    # the "new" signal is largely the old one.
    reentry_cooldown_bars: int = 0


class ExecutionConfig(BaseModel):
    # taker: market entry + all exits pay taker fee + slippage (conservative).
    # maker: entry is a resting limit order at the signal-bar close (maker fee,
    #   no slippage) that may not fill within maker_timeout_bars (a missed
    #   trade — models adverse selection honestly); take-profit exits also fill
    #   as maker limit orders. Stop-loss and timeout exits stay taker, because
    #   in reality they are market orders that must get out.
    order_style: Literal["taker", "maker"] = "taker"
    maker_timeout_bars: int = 1


class PaperConfig(BaseModel):
    initial_capital: float = 1000.0


class RiskConfig(BaseModel):
    position_pct: float = 0.10
    max_open_positions: int = 2
    daily_loss_limit_pct: float = 0.03
    drawdown_alert_pct: float = 0.10  # alert when equity drops this far below its peak


class ModelConfig(BaseModel):
    train_window_days: int = 90
    validation_days: int = 14
    n_folds: int = 5


class VariantConfig(BaseModel):
    """One live A/B book: a name plus strategy/risk overrides on the base config."""
    name: str
    prob_threshold: float | None = None
    tp_atr_mult: float | None = None
    sl_atr_mult: float | None = None
    horizon_bars: float | None = None
    direction: str | None = None
    rollover: bool | None = None
    reentry_cooldown_bars: int | None = None
    position_pct: float | None = None
    max_open_positions: int | None = None


class Config(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    exchange: ExchangeConfig = ExchangeConfig()
    paths: PathsConfig = PathsConfig()
    costs: CostsConfig = CostsConfig()
    strategy: StrategyConfig = StrategyConfig()
    execution: ExecutionConfig = ExecutionConfig()
    paper: PaperConfig = PaperConfig()
    risk: RiskConfig = RiskConfig()
    model: ModelConfig = ModelConfig()
    variants: list[VariantConfig] = Field(default_factory=list)
    # Which A/B book the beginner dashboard shows as "Twój portfel" on the main
    # screen (the others stay in the details). None -> the first/default book.
    primary_variant: str | None = None
    # IANA timezone the dashboard renders timestamps in. The engine stores
    # everything in UTC and the container runs in UTC, so the dashboard converts
    # for display. Change this if you run the bot from another timezone.
    display_timezone: str = "Europe/Warsaw"

    @property
    def api_key(self) -> str | None:
        return os.environ.get("EXCHANGE_API_KEY")

    @property
    def api_secret(self) -> str | None:
        return os.environ.get("EXCHANGE_API_SECRET")

    @property
    def alert_webhook_url(self) -> str | None:
        return os.environ.get("ALERT_WEBHOOK_URL")

    def for_variant(self, variant: VariantConfig) -> Config:
        """A copy of this config with the variant's non-None overrides applied
        to strategy/risk. Used to give each live A/B book its own parameters."""
        strat = self.strategy.model_dump()
        risk = self.risk.model_dump()
        for field in ("prob_threshold", "tp_atr_mult", "sl_atr_mult",
                      "horizon_bars", "direction", "rollover",
                      "reentry_cooldown_bars"):
            if (val := getattr(variant, field)) is not None:
                strat[field] = val
        for field in ("position_pct", "max_open_positions"):
            if (val := getattr(variant, field)) is not None:
                risk[field] = val
        return self.model_copy(update={
            "strategy": StrategyConfig(**strat), "risk": RiskConfig(**risk),
        })


def _find_config_path(explicit: str | Path | None) -> Path:
    """Locate config.yaml so it works both as an editable install (host) and a
    site-packages install (Docker, where PROJECT_ROOT points into site-packages).

    Order: explicit arg, TRADEMON_CONFIG env, ./config/config.yaml under the
    current working directory (Docker WORKDIR /app, or the project root on host),
    then the source-tree default.
    """
    if explicit:
        return Path(explicit)
    if env := os.environ.get("TRADEMON_CONFIG"):
        return Path(env)
    cwd_cfg = Path.cwd() / "config" / "config.yaml"
    if cwd_cfg.exists():
        return cwd_cfg
    return PROJECT_ROOT / "config" / "config.yaml"


def config_path() -> Path:
    """The config.yaml this process would load, resolved the same way load_config
    resolves it. Lets the engine watch the overrides file for changes."""
    return _find_config_path(None)


def overrides_path(cfg_path: Path) -> Path:
    """Sibling file holding the dashboard's edits: config.yaml -> config.overrides.yaml,
    portfolio.yaml -> portfolio.overrides.yaml."""
    return cfg_path.with_name(f"{cfg_path.stem}.overrides.yaml")


def deep_merge(base: dict, over: dict) -> dict:
    """Merge `over` onto `base`: dicts recurse, everything else replaces.

    Lists replace wholesale on purpose. `symbols` and `variants` are the two lists
    here, and merging them element-wise would silently keep a removed pair trading
    or leave half of an old variant's overrides in place — a per-index merge is a
    trap, not a convenience.
    """
    out = dict(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_raw_config(cfg_path: Path) -> tuple[dict, dict]:
    """Return (defaults from config.yaml, overrides from overrides.yaml).

    config.yaml is the documented baseline and is never written to — the dashboard's
    config screen only ever writes overrides.yaml, so the research commentary in the
    baseline survives every edit and "restore default" is just dropping a key.
    """
    with open(cfg_path) as f:
        defaults = yaml.safe_load(f) or {}
    over_path = overrides_path(cfg_path)
    if not over_path.exists():
        return defaults, {}
    with open(over_path) as f:
        return defaults, yaml.safe_load(f) or {}


def load_config(path: str | Path | None = None) -> Config:
    """Load config.yaml (+ overrides.yaml) and resolve data/models/runtime next to
    the config dir."""
    cfg_path = _find_config_path(path)
    base = cfg_path.resolve().parent.parent  # directory that contains config/
    defaults, overrides = load_raw_config(cfg_path)
    raw = deep_merge(defaults, overrides)
    cfg = Config.model_validate(raw)
    cfg = cfg.model_copy(update={"paths": cfg.paths.resolve(base)})
    for d in (cfg.paths.data_dir, cfg.paths.models_dir, cfg.paths.runtime_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
