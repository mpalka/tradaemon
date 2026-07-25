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
                      "horizon_bars", "direction"):
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


def load_config(path: str | Path | None = None) -> Config:
    """Load config.yaml and resolve data/models/runtime next to the config dir."""
    cfg_path = _find_config_path(path)
    base = cfg_path.resolve().parent.parent  # directory that contains config/
    with open(cfg_path) as f:
        raw = yaml.safe_load(f) or {}
    cfg = Config.model_validate(raw)
    cfg = cfg.model_copy(update={"paths": cfg.paths.resolve(base)})
    for d in (cfg.paths.data_dir, cfg.paths.models_dir, cfg.paths.runtime_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
