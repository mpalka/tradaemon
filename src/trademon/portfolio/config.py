"""Typed configuration for the portfolio manager, loaded from
config/portfolio.yaml. Reuses CostsConfig / PathsConfig from module 1 so the two
modules share the same data/runtime layout and cost model."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from trademon.config import (
    PROJECT_ROOT,
    CostsConfig,
    PathsConfig,
    deep_merge,
    load_raw_config,
)


class AssetConfig(BaseModel):
    symbol: str            # base ticker, e.g. "SPY" (the Stooq adapter adds .us)
    target_weight: float   # desired portfolio fraction (weights are normalized)
    safe: bool = False     # defensive asset (e.g. bonds) trend-"off" weight parks in


class RebalanceConfig(BaseModel):
    cadence_days: int = 90            # rebalance at least this often (quarterly)
    drift_threshold_pct: float = 5.0  # ...or sooner if any weight drifts this far


class TrendConfig(BaseModel):
    """Optional systematic tilt: hold an asset only while it trends up. This is a
    risk premium (modest returns, long drawdowns), not a free lunch."""
    enabled: bool = False
    ma_days: int = 200                # hold an asset only above its N-day average
    safe_asset: str | None = None     # where an "off" asset's weight goes (None -> cash)


class ScreenConfig(BaseModel):
    """Diversification screen: what to measure the basket's candidates against.

    VT (Vanguard Total World) is the USD proxy for FTSE All-World with the longest
    history on Yahoo. VWRL.L is the literal FTSE All-World UCITS ETF but quotes in
    GBP, which would mix a currency effect into every correlation.
    """
    benchmark: str = "VT"
    years: int = 10
    candidates: list[str] = Field(default_factory=list)


class PortfolioConfig(BaseModel):
    source: str = "yahoo"
    assets: list[AssetConfig] = Field(default_factory=list)
    rebalance: RebalanceConfig = RebalanceConfig()
    trend: TrendConfig = TrendConfig()
    screen: ScreenConfig = ScreenConfig()
    costs: CostsConfig = CostsConfig()
    paths: PathsConfig = PathsConfig()
    initial_capital: float = 10_000.0
    runtime_subdir: str = "portfolio"   # books live under runtime/portfolio/<name>/
    book_name: str = "core"             # the single default book's name
    # Language for the alerts this module journals and sends to the webhook. Same
    # meaning as `display_language` in config.yaml; see `trademon.i18n`.
    display_language: str = "pl"
    bars_per_year: int = 252            # ETF trading days/year (Sharpe annualization)

    @property
    def alert_webhook_url(self) -> str | None:
        return os.environ.get("ALERT_WEBHOOK_URL")

    @property
    def base_weights(self) -> dict[str, float]:
        """Normalized target weights keyed by symbol."""
        total = sum(a.target_weight for a in self.assets) or 1.0
        return {a.symbol: a.target_weight / total for a in self.assets}

    @property
    def symbols(self) -> list[str]:
        return [a.symbol for a in self.assets]

    @property
    def runtime_dir(self) -> Path:
        return self.paths.runtime_dir / self.runtime_subdir

    def resolved_safe_asset(self) -> str | None:
        """Trend safe asset, defaulting to the first asset flagged `safe:`."""
        if self.trend.safe_asset:
            return self.trend.safe_asset
        return next((a.symbol for a in self.assets if a.safe), None)


def _find_config_path(explicit: str | Path | None) -> Path:
    """Locate portfolio.yaml, mirroring config.load_config so it works as an
    editable install (host) and a site-packages install (Docker)."""
    if explicit:
        return Path(explicit)
    if env := os.environ.get("TRADEMON_PORTFOLIO_CONFIG"):
        return Path(env)
    cwd_cfg = Path.cwd() / "config" / "portfolio.yaml"
    if cwd_cfg.exists():
        return cwd_cfg
    return PROJECT_ROOT / "config" / "portfolio.yaml"


def load_portfolio_config(path: str | Path | None = None) -> PortfolioConfig:
    """Load portfolio.yaml (+ portfolio.overrides.yaml) and resolve data/models/runtime
    next to the config dir."""
    cfg_path = _find_config_path(path)
    base = cfg_path.resolve().parent.parent  # directory that contains config/
    defaults, overrides = load_raw_config(cfg_path)
    raw = deep_merge(defaults, overrides)
    cfg = PortfolioConfig.model_validate(raw)
    cfg = cfg.model_copy(update={"paths": cfg.paths.resolve(base)})
    for d in (cfg.paths.data_dir, cfg.paths.models_dir, cfg.paths.runtime_dir):
        d.mkdir(parents=True, exist_ok=True)
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    return cfg
