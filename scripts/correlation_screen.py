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

from trademon.portfolio.config import load_portfolio_config
from trademon.portfolio.correlation import screen, summarize_screen
from trademon.portfolio.data import download_etf, load_wide_panel
from trademon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("screen")

HEADERS = {"symbol": "aktywo", "corr": "korelacja", "roll_min": "min 3-let.",
           "roll_max": "max 3-let.", "cagr_pct": "CAGR %", "months": "mies.",
           "verdict": "werdykt"}


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
    view = result.rename(columns=HEADERS)
    okres = (f"{years} lat do {as_of} — TYLKO to, co było wiadome wtedy"
             if as_of else f"ostatnie {years} lat")
    lines = ["=" * 88,
             f"PRZESIEW DYWERSYFIKACJI — co porusza się inaczej niż {benchmark}?",
             f"(korelacje miesięcznych stóp zwrotu, {okres})", "=" * 88, "",
             view.to_string(index=False, float_format=lambda v: f"{v:.2f}"), "",
             "-" * 88, "JAK TO CZYTAĆ", "-" * 88,
             "Kolumny 'min/max 3-let.' są ważniejsze niż średnia korelacja: pokazują,",
             "co robiła korelacja w najgorszym momencie. Aktywo o średniej +0,2, które",
             "w kryzysie skacze do +0,75, nie ochroniło portfela wtedy, gdy było potrzebne.",
             "",
             "KANDYDAT   = niska korelacja, stabilna, dodatni zwrot",
             "NIESTABILNY= niska średnio, ale w kryzysie idzie razem z rynkiem",
             "TRACI      = dywersyfikuje, ale zjada portfel (ujemny CAGR)",
             "PUŁAPKA    = ujemna korelacja z konstrukcji (instrumenty odwrotne,",
             "             zmienność) — płaci za nią erozją kapitału",
             "", "-" * 88, "WNIOSEK", "-" * 88]
    lines += summarize_screen(result, benchmark)
    if not as_of:
        lines += ["", "UWAGA: ta tabela opisuje reżim, który się WŁAŚNIE SKOŃCZYŁ.",
                  "Uruchom `--as-of` sprzed 10 lat i zobacz, co metoda wybrałaby wtedy",
                  "— wskazała obligacje długoterminowe, które potem straciły 5%/rok",
                  "i przestały dywersyfikować dokładnie w kryzysie 2022."]
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
    result.to_csv(out_dir / f"screen_{stamp}.csv", index=False)
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
