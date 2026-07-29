"""Typed configuration for the cross-sectional ranking study, loaded from
config/crosssec.yaml. Reuses CostsConfig / PathsConfig from module 1 so all three
modules share one data layout and one set of cost assumptions."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from trademon.config import PROJECT_ROOT, CostsConfig, PathsConfig

# Ranking needs breadth: with 10 assets, "top 3 vs bottom 3" is too few names to tell
# signal from luck. These are the liquid USDT pairs on Binance and a spread of sector,
# region and asset-class ETFs — the classic cross-sectional momentum universe.
CRYPTO_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "LINK/USDT", "AVAX/USDT", "LTC/USDT", "DOT/USDT", "TRX/USDT",
    "ATOM/USDT", "UNI/USDT", "ETC/USDT", "XLM/USDT", "BCH/USDT", "FIL/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "INJ/USDT", "SUI/USDT",
    "AAVE/USDT",
]
ETF_UNIVERSE = [
    # US sectors
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE",
    # broad + regions
    "SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "EWG", "EWU", "FXI", "EWZ",
    # bonds, commodities, real estate
    "TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "DBC", "VNQ", "TIP",
]


class SignalConfig(BaseModel):
    """Momentum measured over `lookback_days`, ignoring the most recent
    `skip_days`. The skip is standard practice: the freshest move tends to mean-revert,
    so including it mixes a reversal effect into a momentum signal."""
    lookback_days: int = 120
    skip_days: int = 5


class RankConfig(BaseModel):
    n_long: int = 5            # how many leaders to hold
    n_short: int = 5           # how many laggards to sell (long_short only)
    rebalance_days: int = 20   # re-rank roughly monthly


class MarketConfig(BaseModel):
    name: str                        # "crypto" | "etf"
    symbols: list[str] = Field(default_factory=list)
    bars_per_year: int = 365         # crypto trades every day; ETFs ~252


class CrossSecConfig(BaseModel):
    signal: SignalConfig = SignalConfig()
    rank: RankConfig = RankConfig()
    markets: list[MarketConfig] = Field(default_factory=list)
    costs: CostsConfig = CostsConfig()
    paths: PathsConfig = PathsConfig()
    initial_capital: float = 10_000.0
    # Disjoint periods the study is scored on. One number is a single verdict and
    # invites the selection bias that has already fooled this project three times.
    n_windows: int = 4

    @property
    def turnover_cost(self) -> float:
        """Cost of trading one unit of notional, one way. A full rotation of a fully
        invested book has turnover 2.0 (everything out, everything in), which at the
        defaults comes to ~0.24% — the same round trip module 1 pays."""
        return self.costs.taker_fee + self.costs.slippage

    def market(self, name: str) -> MarketConfig:
        for m in self.markets:
            if m.name == name:
                return m
        raise KeyError(f"no market '{name}' in config (have: "
                       f"{[m.name for m in self.markets]})")


def _find_config_path(explicit: str | Path | None) -> Path:
    """Locate crosssec.yaml, mirroring config.load_config so it works both as an
    editable install (host) and a site-packages install (Docker)."""
    if explicit:
        return Path(explicit)
    if env := os.environ.get("TRADEMON_CROSSSEC_CONFIG"):
        return Path(env)
    cwd_cfg = Path.cwd() / "config" / "crosssec.yaml"
    if cwd_cfg.exists():
        return cwd_cfg
    return PROJECT_ROOT / "config" / "crosssec.yaml"


def load_crosssec_config(path: str | Path | None = None) -> CrossSecConfig:
    """Load crosssec.yaml and resolve data/models/runtime next to the config dir."""
    cfg_path = _find_config_path(path)
    base = cfg_path.resolve().parent.parent
    with open(cfg_path) as f:
        raw = yaml.safe_load(f) or {}
    cfg = CrossSecConfig.model_validate(raw)
    cfg = cfg.model_copy(update={"paths": cfg.paths.resolve(base)})
    for d in (cfg.paths.data_dir, cfg.paths.runtime_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
