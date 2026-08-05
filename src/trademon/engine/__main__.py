"""Entry point: python -m trademon.engine"""

from __future__ import annotations

import asyncio
import logging

from trademon.config import load_config
from trademon.engine.loop import RestartRequested, TradingEngine
from trademon.execution.executors import PaperExecutor
from trademon.models.train import load_bundles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("trademon")


def main() -> None:
    cfg = load_config()
    bundles = load_bundles(cfg.paths.models_dir)

    if cfg.mode == "live" and cfg.variants:
        raise SystemExit("live A/B variants are not supported (paper only) — "
                         "remove `variants:` from config.yaml or use paper mode")

    if cfg.strategy.direction == "long_short":
        if cfg.mode == "live":
            # Real short selling needs a futures/margin account; the spot
            # LiveExecutor cannot represent it. Refuse rather than mis-trade.
            raise SystemExit(
                "strategy.direction=long_short is not supported in live mode "
                "(requires futures; not implemented) — use paper mode or direction=long"
            )
        if "short" not in bundles:
            log.warning("direction=long_short but no model_short found — long-only until retrain")

    if cfg.execution.order_style == "maker":
        # Maker execution is modeled in the backtester (limit entries with
        # non-fill risk, maker-priced take-profits). The live engine does not
        # yet place resting limit orders, so it executes taker regardless.
        log.warning(
            "config execution.order_style=maker is backtest-only; "
            "the engine executes taker market orders"
        )

    if cfg.mode == "live":
        from trademon.data.ingestion import make_exchange
        from trademon.execution.executors import LiveExecutor

        log.warning("LIVE MODE: real orders will be sent to %s", cfg.exchange.id)
        executor = LiveExecutor(cfg, make_exchange(cfg, authenticated=True))
    else:
        log.info("paper mode: simulated fills, no real orders")
        executor = PaperExecutor(cfg)

    engine = TradingEngine(cfg, bundles, executor)
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        log.info("shutting down (state persisted)")
    except RestartRequested:
        # Exit 0 on purpose: `restart: unless-stopped` restarts a container that
        # stopped for any reason, and a clean code keeps this out of the crash logs.
        # Books were persisted on the way out and reload themselves on the way back.
        log.info("restarting to pick up the new configuration (state persisted)")


if __name__ == "__main__":
    main()
