"""Event-driven backtest using the same fill simulation as the paper executor.

Execution model (one position per symbol, long and optionally short):
- signal at close of bar t: the direction whose model probability clears the
  threshold (higher one wins if both do),
- entry at open of bar t+1 with taker fee + slippage (or a resting limit at
  close[t] in maker mode, which may expire unfilled),
- exits: TP/SL barrier touched intra-bar (both touched -> SL, conservative)
  or timeout after `horizon_bars` bars at that bar's close.

Short accounting is futures-style: margin equal to the entry notional is set
aside, pnl = qty * (entry - exit) - fees. Real short execution requires a
futures/margin account; backtest and paper trading simulate it.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from trademon.backtest.metrics import periods_per_year, summarize
from trademon.config import Config
from trademon.execution.fills import (
    buy_fill,
    check_bracket_exit,
    limit_buy_fills,
    limit_sell_fills,
    maker_buy_fill,
    maker_sell_fill,
    sell_fill,
)
from trademon.features.engineering import compute_atr, compute_features
from trademon.models.train import ModelBundle

log = logging.getLogger(__name__)


def run_backtest(
    df: pd.DataFrame,
    bundles: dict[str, ModelBundle] | ModelBundle,
    cfg: Config,
    symbol: str,
    funding: pd.DataFrame | None = None,
    trade_from: int = 0,
) -> dict:
    """`trade_from`: index of the first bar allowed to open a position. Bars
    before it only feed feature computation, so a short test window can carry
    the warmup history it needs without trading inside it."""
    if not isinstance(bundles, dict):
        bundles = {"long": bundles}
    strat, costs = cfg.strategy, cfg.costs
    maker = cfg.execution.order_style == "maker"
    allow_short = strat.direction == "long_short" and "short" in bundles
    features = compute_features(df, strat.atr_period, funding=funding)
    atr = compute_atr(df, strat.atr_period)

    feature_cols = bundles["long"].feature_columns
    valid = features[feature_cols].notna().all(axis=1).to_numpy()
    p_long = np.full(len(df), np.nan)
    p_short = np.full(len(df), np.nan)
    if valid.any():
        p_long[valid] = bundles["long"].predict_proba(features[valid])
        if allow_short:
            p_short[valid] = bundles["short"].predict_proba(features[valid])

    open_ = df["open"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    ts = df["timestamp"].to_numpy()
    atr_v = atr.to_numpy(float)

    initial = cfg.paper.initial_capital
    cash = initial
    trades: list[dict] = []
    equity_curve = np.full(len(df), np.nan)
    cash_curve = np.full(len(df), np.nan)   # free cash per bar -> how much was idle
    n_signals = n_fills = 0

    pos_qty = 0.0          # > 0 means a position is open (size is always positive)
    side = 1               # +1 long, -1 short
    pos_entry = tp = sl = 0.0
    margin = entry_fees = 0.0
    entry_bar = -1
    deadline = -1
    entry_ts = None

    # pending maker limit entry (order_style == "maker")
    pend_active = False
    pend_side = 1
    pend_limit = pend_atr = 0.0
    pend_expiry = -1

    def set_barriers(entry_price: float, bar_atr: float, s: int) -> tuple[float, float]:
        return (
            entry_price + s * strat.tp_atr_mult * bar_atr,
            entry_price - s * strat.sl_atr_mult * bar_atr,
        )

    def open_position(fill, s: int, bar: int, bar_atr: float) -> bool:
        nonlocal cash, pos_qty, side, pos_entry, margin, entry_fees
        nonlocal tp, sl, entry_bar, deadline, entry_ts, n_fills
        if fill.notional + fill.fee > cash:
            return False
        cash -= fill.notional + fill.fee
        margin = fill.notional
        pos_qty, side, pos_entry, entry_fees = fill.notional / fill.price, s, fill.price, fill.fee
        tp, sl = set_barriers(fill.price, bar_atr, s)
        entry_bar, deadline, entry_ts = bar, bar + strat.horizon_bars, ts[bar]
        n_fills += 1
        return True

    for t in range(len(df)):
        # 1) manage an open position on this bar
        if pos_qty > 0.0 and t >= entry_bar:
            direction = "long" if side == 1 else "short"
            reason = check_bracket_exit(high[t], low[t], tp, sl, direction)
            exit_price = None
            exit_maker = False
            if reason == "tp":
                exit_price, exit_maker = tp, maker  # resting limit at the target
            elif reason == "sl":
                exit_price = sl  # stop -> market order, stays taker
            elif t >= deadline:
                reason, exit_price = "timeout", close[t]  # market order, taker
            if exit_price is not None:
                if side == 1:  # closing a long = sell
                    fill = (maker_sell_fill if exit_maker else sell_fill)(
                        exit_price, pos_qty, costs
                    )
                else:  # closing a short = buy back
                    fill = (maker_buy_fill if exit_maker else buy_fill)(
                        exit_price, pos_qty, costs
                    )
                pnl = side * pos_qty * (fill.price - pos_entry) - entry_fees - fill.fee
                cash += margin + side * pos_qty * (fill.price - pos_entry) - fill.fee
                trades.append(
                    {
                        "symbol": symbol,
                        "side": "long" if side == 1 else "short",
                        "entry_time": entry_ts,
                        "exit_time": ts[t],
                        "qty": pos_qty,
                        "entry_price": pos_entry,
                        "exit_price": fill.price,
                        "exit_reason": reason,
                        "fees": entry_fees + fill.fee,
                        "pnl": pnl,
                    }
                )
                pos_qty, margin = 0.0, 0.0

        # 2) maker: try to fill a resting entry limit, or expire it unfilled
        if maker and pend_active and pos_qty == 0.0:
            if t <= pend_expiry:
                filled = (
                    limit_buy_fills(low[t], pend_limit)
                    if pend_side == 1
                    else limit_sell_fills(high[t], pend_limit)
                )
                if filled:
                    qty = (cash * cfg.risk.position_pct) / pend_limit
                    fill = (maker_buy_fill if pend_side == 1 else maker_sell_fill)(
                        pend_limit, qty, costs
                    )
                    open_position(fill, pend_side, t, pend_atr)
                    pend_active = False
            else:
                pend_active = False  # expired unfilled -> the signal is missed

        # 3) new signal at close of bar t: direction with the higher prob wins
        if (
            pos_qty == 0.0
            and not pend_active
            and t >= trade_from
            and t + 1 < len(df)
            and atr_v[t] > 0
        ):
            sig_side = 0
            best_p = strat.prob_threshold
            if not np.isnan(p_long[t]) and p_long[t] >= best_p:
                sig_side, best_p = 1, p_long[t]
            if allow_short and not np.isnan(p_short[t]) and p_short[t] > best_p:
                sig_side = -1
            if sig_side != 0:
                n_signals += 1
                if maker:
                    pend_active = True
                    pend_side = sig_side
                    pend_limit, pend_atr = close[t], atr_v[t]
                    pend_expiry = t + cfg.execution.maker_timeout_bars
                else:
                    qty = (cash * cfg.risk.position_pct) / open_[t + 1]
                    fill = (buy_fill if sig_side == 1 else sell_fill)(
                        open_[t + 1], qty, costs
                    )
                    open_position(fill, sig_side, t + 1, atr_v[t])

        if t >= trade_from:
            equity_curve[t] = cash + margin + side * pos_qty * (close[t] - pos_entry)
            cash_curve[t] = cash

    trades_df = pd.DataFrame(trades)
    equity = pd.Series(equity_curve, index=df["timestamp"]).dropna()
    cash_series = pd.Series(cash_curve, index=df["timestamp"]).dropna()
    result = summarize(trades_df, equity, initial, periods_per_year(cfg.exchange.timeframe),
                       cash=cash_series)
    result["symbol"] = symbol
    result["period"] = {
        "start": str(df["timestamp"].iloc[trade_from]),
        "end": str(df["timestamp"].iloc[-1]),
        "bars": len(df) - trade_from,
    }
    # Cost-awareness: median TP distance vs the cost of a winning round trip.
    result["order_style"] = cfg.execution.order_style
    result["median_tp_pct"] = float(strat.tp_atr_mult * np.nanmedian(atr_v / close) * 100.0)
    if maker:
        # a win = maker entry + maker take-profit
        result["round_trip_cost_pct"] = 2.0 * costs.maker_fee * 100.0
    else:
        result["round_trip_cost_pct"] = 2.0 * (costs.taker_fee + costs.slippage) * 100.0
    result["signals"] = n_signals
    result["fills"] = n_fills
    result["fill_rate_pct"] = (n_fills / n_signals * 100.0) if n_signals else 0.0
    result["direction"] = strat.direction if allow_short else "long"
    if len(trades_df) and "side" in trades_df:
        result["by_side"] = {
            s: {"trades": int(g["pnl"].count()), "pnl": float(g["pnl"].sum())}
            for s, g in trades_df.groupby("side")
        }
    return {"summary": result, "trades": trades_df, "equity": equity}


def _risked_suffix(s: dict) -> str:
    """Return rescaled to the money at work — omitted when the book traded so rarely
    that the rescale would extrapolate rather than inform."""
    risked = s.get("return_on_risked_pct")
    if risked is None:
        return " (too rarely in the market to rescale the return)"
    return f" -> return on money actually risked: {risked:+.2f}%"


def render_report(results: list[dict], cfg: Config) -> str:
    """Plain-text report; also states the go/no-go verdict after costs."""
    lines = ["=" * 64, "TRADEMON BACKTEST REPORT", "=" * 64]
    for r in results:
        s = r["summary"]
        lines += [
            f"\nSymbol: {s['symbol']}  ({s['period']['start']} .. {s['period']['end']})",
            (
                f"  trades: {s['n_trades']}, win rate: {s.get('win_rate_pct', 0):.1f}%, "
                f"profit factor: {s.get('profit_factor', 0):.2f}"
            ),
            (
                f"  net return: {s['total_return_pct']:+.2f}%  "
                f"(fees paid: {s.get('fees_paid', 0):.2f})"
            ),
            f"  sharpe: {s['sharpe']:.2f}, max drawdown: {s['max_drawdown_pct']:.2f}%",
            # The numbers above are measured on the whole account, most of which
            # never traded — so state how much of it was actually at work.
            (
                f"  capital at work: {s.get('avg_exposure_pct', 0):.1f}% on average, "
                f"in the market on {s.get('time_in_market_pct', 0):.0f}% of bars"
                + _risked_suffix(s)
            ),
            f"  exits: {s.get('exits', {})}",
            (
                f"  order style: {s.get('order_style', 'taker')}, "
                f"direction: {s.get('direction', 'long')}, "
                f"signals: {s.get('signals', 0)}, fills: {s.get('fills', 0)} "
                f"({s.get('fill_rate_pct', 0):.0f}% filled)"
            ),
        ]
        if s.get("by_side"):
            parts = [
                f"{name}: {v['trades']} trades, pnl {v['pnl']:+.2f}"
                for name, v in sorted(s["by_side"].items())
            ]
            lines.append(f"  by side: {'; '.join(parts)}")
        if s["median_tp_pct"] < s["round_trip_cost_pct"]:
            lines.append(
                f"  WARNING: median TP distance ({s['median_tp_pct']:.3f}%) is below "
                f"round-trip costs ({s['round_trip_cost_pct']:.3f}%) — winning trades "
                f"still lose money; widen tp_atr_mult / horizon or use a higher timeframe"
            )
    net = [r["summary"]["total_return_pct"] for r in results]
    verdict = "POSITIVE after costs" if all(x > 0 for x in net) else "NEGATIVE after costs"
    lines += ["-" * 64, f"VERDICT: {verdict} — do not go live on a negative strategy.", "=" * 64]
    return "\n".join(lines)


def render_html_report(results: list[dict], cfg: Config) -> str:
    """Self-contained HTML report: metrics table + per-symbol equity curves
    (Vega-Lite, rendered via CDN). Written alongside the .txt/.json reports."""
    import json

    rows = []
    for r in results:
        eq = r["equity"]
        for ts, val in eq.items():
            rows.append({"symbol": r["summary"]["symbol"], "timestamp": str(ts),
                         "equity": float(val)})
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container", "height": 340, "data": {"values": rows},
        "mark": {"type": "line", "strokeWidth": 1.5},
        "encoding": {
            "x": {"field": "timestamp", "type": "temporal", "title": None},
            "y": {"field": "equity", "type": "quantitative", "title": "Kapitał (USDT)",
                  "scale": {"zero": False}},
            "color": {"field": "symbol", "type": "nominal", "title": "Para"},
        },
    }

    def cells(s: dict) -> str:
        risked = s.get("return_on_risked_pct")
        return "".join(f"<td>{c}</td>" for c in [
            s["symbol"], s["n_trades"], f"{s.get('win_rate_pct', 0):.0f}%",
            f"{s.get('profit_factor', 0):.2f}", f"{s['total_return_pct']:+.2f}%",
            f"{s.get('avg_exposure_pct', 0):.1f}%",
            f"{s.get('time_in_market_pct', 0):.0f}%",
            f"{risked:+.2f}%" if risked is not None else "—",
            f"{s['sharpe']:.2f}", f"{s['max_drawdown_pct']:.2f}%",
            f"{s.get('fees_paid', 0):.2f}",
        ])

    header = "".join(f"<th>{h}</th>" for h in
                     ["Para", "Transakcje", "Win rate", "Profit factor",
                      "Wynik netto", "W grze (śr.)", "Czas w rynku", "Wynik od tego",
                      "Sharpe", "Max DD", "Prowizje"])
    body = "".join(f"<tr>{cells(r['summary'])}</tr>" for r in results)
    net = [r["summary"]["total_return_pct"] for r in results]
    positive = all(x > 0 for x in net)
    verdict = "DODATNI po kosztach" if positive else "UJEMNY po kosztach"
    color = "#0ca30c" if positive else "#d03b3b"
    period = results[0]["summary"]["period"] if results else {"start": "", "end": ""}

    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8">
<title>TraDaemon 👹💰 — raport backtestu</title>
<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
<style>
 body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
 h1{{margin-bottom:.2rem}} .sub{{color:#666;margin-top:0}}
 .verdict{{font-weight:600;color:{color};font-size:1.1rem;margin:1rem 0}}
 table{{border-collapse:collapse;width:100%;font-size:.9rem;margin-top:1rem}}
 th,td{{border:1px solid #ddd;padding:.4rem .6rem;text-align:right}}
 th:first-child,td:first-child{{text-align:left}} th{{background:#f4f4f4}}
 #chart{{margin-top:1.5rem}}
</style></head><body>
<h1>TraDaemon 👹💰 — raport backtestu</h1>
<p class="sub">Okres: {period['start']} .. {period['end']} · timeframe {cfg.exchange.timeframe}
 · {len(results)} par</p>
<p class="verdict">WERDYKT: {verdict}</p>
<div id="chart"></div>
<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>
<script>vegaEmbed('#chart', {json.dumps(spec)}, {{actions:false}});</script>
</body></html>"""
