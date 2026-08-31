"""Diversification screen: what actually moves differently from world equities?

Usage: python scripts/correlation_screen.py [--benchmark VT] [--years 10]
       [--no-download] [--add TICKER ...]

Answers a risk question, not a prediction one: if the global equity market falls,
what else in the basket is not falling with it? Reports the rolling correlation
range alongside the average, because an asset that diversifies on average and
correlates in a crash has not diversified at all.
"""

import argparse
import json
import logging

import pandas as pd

from tradaemon import i18n
from tradaemon.i18n import t
from tradaemon.portfolio.config import load_portfolio_config
from tradaemon.portfolio.correlation import screen, summarize_screen, verdict_help
from tradaemon.portfolio.data import download_etf, load_wide_panel
from tradaemon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("screen")

# Console headings only, translated from the shared `col.*` keys. The CSV keeps the raw
# column names and the raw verdict tokens, which is what `research_view` reads.
HEADER_KEYS = ["symbol", "corr", "roll_min", "roll_max", "cagr_pct", "months", "verdict"]


def fetch(data_dir, symbols: list[str]) -> list[str]:
    """Download what we can; a delisted or renamed ticker is skipped, not fatal."""
    ok = []
    for sym in symbols:
        try:
            download_etf(data_dir, sym)
            ok.append(sym)
        except Exception as exc:  # noqa: BLE001 - one dead ticker must not stop the screen
            log.warning("%s: skipped (%s)", sym, str(exc)[:80])
    return ok


def render(result: pd.DataFrame, benchmark: str, years: int,
           as_of: str | None = None) -> str:
    view = result.rename(columns={k: t(f"col.{k}") for k in HEADER_KEYS})
    period = (t("cli.screen.period.as_of", years=years, as_of=as_of)
              if as_of else t("cli.screen.period.recent", years=years))
    lines = ["=" * 88,
             t("cli.screen.title", benchmark=benchmark),
             t("cli.screen.subtitle", period=period), "=" * 88, "",
             view.to_string(index=False, float_format=lambda v: f"{v:.2f}"), "",
             "-" * 88, t("cli.screen.how_to_read"), "-" * 88,
             t("cli.screen.rolling_matters"),
             "",
             # The token on the left is what the CSV stores; the words explain it.
             *(f"{token:<12}= {verdict_help(token)}"
               for token in ("KANDYDAT", "NIESTABILNY", "TRACI", "PUŁAPKA")),
             "", "-" * 88, t("cli.screen.conclusion"), "-" * 88]
    lines += summarize_screen(result, benchmark)
    if not as_of:
        lines += ["", t("cli.screen.regime_warning")]
    lines += ["=" * 88]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--benchmark", default=None, help="ticker to measure against")
    p.add_argument("--years", type=int, default=None, help="lookback window in years")
    p.add_argument("--no-download", action="store_true", help="use cached data only")
    p.add_argument("--add", nargs="*", default=[], help="extra tickers to screen")
    p.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                   help="screen using only data known by this date, to see what the "
                        "method would have picked back then (try 10 years ago)")
    args = p.parse_args()

    cfg = load_portfolio_config()
    i18n.init(getattr(cfg, "display_language", None))
    benchmark = args.benchmark or cfg.screen.benchmark
    years = args.years or cfg.screen.years
    wanted = list(dict.fromkeys([benchmark, *cfg.screen.candidates, *args.add]))

    if not args.no_download:
        log.info("refreshing %d tickers from Yahoo...", len(wanted))
        wanted = fetch(cfg.paths.data_dir, wanted)

    # wide, not aligned: each pair is scored on its own overlap, so one young fund
    # cannot quietly shorten the window for everything else
    panel = load_wide_panel(cfg.paths.data_dir, wanted)
    if panel.empty or benchmark not in panel.columns:
        log.error("no usable panel — is %s downloaded?", benchmark)
        return

    result = screen(panel, benchmark, years, as_of=args.as_of)
    report = render(result, benchmark, years, args.as_of)
    print(report)

    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    (out_dir / f"screen_{stamp}.txt").write_text(report)
    # Record the cutoff in the file itself: a saved --as-of run is a snapshot of what
    # was knowable back then, and without this the dashboard would show a 2016-vintage
    # screen under today's date as if it were current.
    result.assign(as_of=args.as_of or "").to_csv(
        out_dir / f"screen_{stamp}.csv", index=False)
    log.info("report saved to %s", out_dir)

    keepers = result[result["verdict"] == "KANDYDAT"]
    log_experiment(cfg.paths.runtime_dir, {
        "kind": "screen",
        "timeframe": "1mo",
        "window_days": years * 365,
        "pairs": len(result),
        "strategy": {"benchmark": benchmark, "years": years,
                     "candidates": list(result["symbol"])},
        "mean_return_pct": float(result["cagr_pct"].mean()),
        "benchmark_return_pct": 0.0,
        "excess_return_pct": 0.0,
        "total_trades": 0,
        "notes": json.dumps({"kandydaci": list(keepers["symbol"]),
                             "ujemna_korelacja": int((result["corr"] < 0).sum())},
                            ensure_ascii=False),
        "report": f"screen_{stamp}.txt",
    })


if __name__ == "__main__":
    main()
