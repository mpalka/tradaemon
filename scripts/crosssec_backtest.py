"""Cross-sectional ranking study (module 3): buy the leaders, optionally sell the
laggards, re-rank periodically — measured on crypto and ETFs with identical code.

Usage: python scripts/crosssec_backtest.py [--refresh] [--market crypto|etf]
       [--lookback 120] [--rebalance 20] [--windows 4]

Prints the full market x direction x window matrix. It deliberately does not pick a
winner: the question is whether the sign holds across disjoint windows, because a
best-of-N cell has fooled this project three times already.
"""

import argparse
import json
import logging

import pandas as pd

from trademon.crosssec.config import load_crosssec_config
from trademon.crosssec.panels import refresh_market
from trademon.crosssec.validate import run_matrix, verdict
from trademon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("crosssec")

COLS = ["market", "direction", "window", "total_return_pct", "hurdle_pct",
        "excess_vs_hurdle_pp", "sigmas_from_zero", "sharpe", "max_drawdown_pct",
        "avg_gross_exposure_pct", "avg_net_exposure_pct", "n_rebalances",
        "fees_pct_of_capital"]
HEADERS = {"total_return_pct": "wynik %", "hurdle_pct": "poprzeczka %",
           "excess_vs_hurdle_pp": "nadwyżka pkt", "sigmas_from_zero": "odch. od 0",
           "sharpe": "Sharpe",
           "max_drawdown_pct": "obsunięcie %", "avg_gross_exposure_pct": "w grze %",
           "avg_net_exposure_pct": "netto %", "n_rebalances": "rebalansów",
           "fees_pct_of_capital": "koszty %", "market": "rynek",
           "direction": "kierunek", "window": "okno"}


def render(matrix: pd.DataFrame) -> str:
    if matrix.empty:
        return "Brak wyników — najpierw pobierz dane (--refresh)."
    view = matrix[COLS].rename(columns=HEADERS).copy()
    view["okno"] = view["okno"].map(lambda w: "CAŁOŚĆ" if w == 0 else str(w))
    lines = ["=" * 100, "MODUŁ 3: RANKING PRZEKROJOWY — ten sam kod na dwóch rynkach",
             "=" * 100, "",
             view.to_string(index=False, float_format=lambda v: f"{v:.2f}"), "",
             "Poprzeczka zależy od ekspozycji: long_only (~100% netto) mierzy się",
             "z koszykiem kup&trzymaj, long_short (~0% netto) z gotówką. Porównywanie",
             "książki neutralnej rynkowo z w pełni długim koszykiem to ten sam błąd",
             "niedopasowanej ekspozycji, który zawyżał ocenę Modułu 1.", "",
             "-" * 100, "CZY ZNAK SIĘ TRZYMA NA ROZŁĄCZNYCH OKNACH?", "-" * 100]
    lines += verdict(matrix)
    full = matrix[matrix["window"] == 0]
    if len(full):
        lines += ["", "-" * 100,
                  "CZY WYNIK JEST ODRÓŻNIALNY OD SZCZĘŚCIA? (całe okresy)", "-" * 100]
        for _, r in full.iterrows():
            sig = abs(r["sigmas_from_zero"]) > 2.0
            lines.append(
                f"{r['market']:6s} {r['direction']:11s}: wynik {r['total_return_pct']:+7.1f}% "
                f"przy {r['sigmas_from_zero']:+.2f} odchylenia od zera — "
                + ("ISTOTNE" if sig else "NIEODRÓŻNIALNE od szumu (potrzeba ~2)"))
    lines += ["", "Okno CAŁOŚĆ jest tylko kontekstem — nakłada się na okna 1..N,",
              "więc nie jest niezależnym potwierdzeniem.", "=" * 100]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true",
                   help="download/refresh daily history for both universes first")
    p.add_argument("--market", choices=["crypto", "etf"], default=None,
                   help="limit the study to one market")
    p.add_argument("--lookback", type=int, default=None, help="momentum lookback in days")
    p.add_argument("--rebalance", type=int, default=None, help="days between re-rankings")
    p.add_argument("--windows", type=int, default=None, help="how many disjoint windows")
    args = p.parse_args()

    cfg = load_crosssec_config()
    if args.lookback:
        cfg = cfg.model_copy(update={
            "signal": cfg.signal.model_copy(update={"lookback_days": args.lookback})})
    if args.rebalance:
        cfg = cfg.model_copy(update={
            "rank": cfg.rank.model_copy(update={"rebalance_days": args.rebalance})})
    if args.windows:
        cfg = cfg.model_copy(update={"n_windows": args.windows})
    if args.market:
        cfg = cfg.model_copy(update={"markets": [cfg.market(args.market)]})

    if args.refresh:
        for m in cfg.markets:
            log.info("%s: refreshing %d symbols...", m.name, len(m.symbols))
            rows = refresh_market(cfg.paths.data_dir, m.name, m.symbols)
            log.info("%s: %d/%d symbols have data", m.name, len(rows), len(m.symbols))

    matrix = run_matrix(cfg)
    report = render(matrix)
    print(report)
    if matrix.empty:
        return

    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    (out_dir / f"crosssec_{stamp}.txt").write_text(report)
    matrix.to_csv(out_dir / f"crosssec_{stamp}.csv", index=False)
    log.info("report saved to %s", out_dir)

    per_window = matrix[matrix["window"] > 0]
    log_experiment(cfg.paths.runtime_dir, {
        "kind": "crosssec",
        "timeframe": "1d",
        "window_days": int(per_window["bars"].mean()) if len(per_window) else 0,
        "pairs": sum(len(m.symbols) for m in cfg.markets),
        "strategy": {"signal": cfg.signal.model_dump(), "rank": cfg.rank.model_dump(),
                     "markets": [m.name for m in cfg.markets],
                     "n_windows": cfg.n_windows},
        "mean_return_pct": float(per_window["total_return_pct"].mean()),
        "benchmark_return_pct": float(per_window["benchmark_return_pct"].mean()),
        "excess_return_pct": float(per_window["excess_vs_hurdle_pp"].mean()),
        "total_trades": int(matrix["n_rebalances"].sum()),
        "notes": json.dumps(verdict(matrix), ensure_ascii=False),
        "report": f"crosssec_{stamp}.txt",
    })


if __name__ == "__main__":
    main()
