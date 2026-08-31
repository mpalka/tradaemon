"""Test C1 — is the model's probability worth anything *past* the threshold?

The engine treats p as a gate: 0.56 and 0.92 open exactly the same position, of
`equity * position_pct`. The obvious next idea is to let conviction set the size.
This measures whether there is any conviction to spend.

0.1.11 already measured a close relative and rejected it: `best_first`, which hands
a free slot to the highest probability, beat `fcfs` by -0.6..+0.7 pp with five of six
comparisons at zero or negative. But that test could only see the *ordering among
candidates competing on the same bar, and only while the cap was binding*. It never
asked the plain question — do trades entered at a high p end better than trades
entered at a low one — because no trade record carried its p until now.

What it measures
----------------
Per-trade net return as a fraction of the trade's own notional,

    r = pnl / (qty * entry_price)

which is `lab.run_oos`'s `avg_net_pct` at trade granularity: comparable across pairs
and price levels, and already after fees and slippage.

The key identity is that budget-neutral sizing needs no extra backtest. If trade i
takes `m_i * position_pct` of equity instead of `position_pct`, and the multiplier is
centred so that mean(m) = 1 (the same money, redistributed — not more money), then
the window's return changes by

    delta = position_pct * n_trades * mean((m - 1) * r)

i.e. by the covariance of the multiplier with the outcome. So one pool of trades
answers every monotone ramp at once, and the whole question collapses to: does a
multiplier that rises with p correlate with the trade going well?

The estimate is deliberately optimistic and must be read as a ceiling, not a result:
it ignores the cash constraint (`book.run_book_backtest` refuses a position it cannot
fund — `cash_blocked`), compounding, and the fact that changing sizes changes which
trades are affordable and therefore the path. It is enough to decide whether the idea
is worth a real implementation; it is not the number that implementation would earn.

Two caveats it cannot fix, both worth knowing before reading the tables:
* rollovers. `strategy.rollover` extends a position on a later bar's signal, but the
  trade keeps the p that opened it (as it keeps its entry price). A rolled-over trade
  is therefore filed under a probability that is only part of the story. `timeout_%`
  per bucket is printed for that reason.
* the shipped board is long-only (`strategy.direction`), so in practice one model
  supplies every number here. The bucketing is still done per side, because with
  `long_short` the two models have different base rates and a shared bucket would
  mix two scales.

Controls
--------
`--control random` replaces the model with `lab.control_bundles("random")`. It must
produce a flat curve. If it does not, this script is broken and the main table may
not be read.

The permutation null shuffles p inside each window, which leaves both marginal
distributions alone and destroys only the pairing. It is what says whether a +0.3 pp
is a finding or the shape of the noise — the equivalent of the t = 2.73 that 0.1.11
reported for the position cap.

    python scripts/research/prob_calibration.py --windows 6 --window-days 120
    python scripts/research/prob_calibration.py --windows 3 --control random
"""

from __future__ import annotations

import argparse
import json
import logging

import numpy as np
import pandas as pd

from trademon.backtest.book import run_book_backtest
from trademon.config import load_config
from trademon.research.lab import (
    Window,
    buy_hold_pct,
    control_bundles,
    enough_history,
    load_pairs,
    regime_of,
    round_trip_pct,
    train_for_geometry,
    window_frames,
    with_strategy,
)
from trademon.research.log import log_experiment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("prob_calibration")

pd.set_option("display.width", 250)

# Half-widths of the multiplier band. 0.25 means the weakest signal in a window
# enters at 0.75x the normal size and the strongest at 1.25x.
STRENGTHS = (0.25, 0.5, 0.75)


# --------------------------------------------------------------------------
# collecting trades
# --------------------------------------------------------------------------


def collect_trades(cfg, pairs: dict[str, pd.DataFrame], windows: list[Window],
                   control: str | None, min_train_bars: int, seed: int = 7,
                   quiet: bool = False) -> pd.DataFrame:
    """Run every window strict-OOS and pool the trades, tagged with their window."""
    strat = cfg.strategy
    frames = []
    for window in windows:
        if not enough_history(pairs, window, min_train_bars):
            if not quiet:
                log.warning("window %s skipped: not enough history before it", window.label())
            continue
        bh = float(np.mean([buy_hold_pct(df, window) for df in pairs.values()]))
        if not quiet:
            log.info("window %s (buy&hold %+.1f%%): training on data from before it...",
                     window.label(), bh)
        if control:
            bundles = control_bundles(control, seed=seed)
        else:
            bundles = train_for_geometry(pairs, cfg, strat.tp_atr_mult,
                                         strat.sl_atr_mult, int(strat.horizon_bars), window)
        wframes, trade_from = window_frames(pairs, window, strat.warmup_bars)
        r = run_book_backtest(wframes, bundles, cfg, allocation="best_first",
                              trade_from=trade_from)
        t, s = r["trades"], r["summary"]
        if not quiet:
            log.info("  %d transakcji, wynik %+.2f%%, bez slotu %d",
                     s["n_trades"], s["total_return_pct"], s["slot_blocked"])
        if not len(t):
            continue
        t = t.copy()
        t["window"] = window.label()
        t["buy_hold_pct"] = bh
        t["regime"] = regime_of(bh)
        frames.append(t)
    if not frames:
        raise SystemExit("no window produced any trades — there is nothing to measure")
    trades = pd.concat(frames, ignore_index=True)
    trades["r"] = trades["pnl"] / (trades["qty"] * trades["entry_price"])
    trades["gross_r"] = (trades["pnl"] + trades["fees"]) / (trades["qty"] * trades["entry_price"])
    trades["cost_r"] = trades["fees"] / (trades["qty"] * trades["entry_price"])
    return trades


# --------------------------------------------------------------------------
# A) the calibration curve
# --------------------------------------------------------------------------


def calibration_table(trades: pd.DataFrame, n_buckets: int, breakeven: float) -> pd.DataFrame:
    """Win rate and net return by probability bucket.

    Buckets are quantiles taken *inside each window and side*, then aggregated by
    rank. Global quantiles would be wrong: each window has its own freshly fitted
    model, so the level of p drifts between windows, and a global cut would sort
    windows as much as it sorts signals.
    """
    def label(g: pd.DataFrame) -> pd.Series:
        # duplicates="drop" for the degenerate case of a window whose p barely varies;
        # rank(pct) instead of the raw value so ties spread across buckets rather
        # than collapsing one.
        return pd.qcut(g["prob"].rank(method="first", pct=True), n_buckets,
                       labels=False, duplicates="drop")

    t = trades.copy()
    t["bucket"] = (t.groupby(["window", "side"], group_keys=False)
                    .apply(label, include_groups=False))
    t = t[t["bucket"].notna()]
    t["bucket"] = t["bucket"].astype(int) + 1

    rows = []
    for b, g in t.groupby("bucket"):
        win = float((g["pnl"] > 0).mean() * 100.0)
        rows.append({
            "bucket_no": b,
            "p_od": float(g["prob"].min()), "p_do": float(g["prob"].max()),
            "n": len(g),
            "win_%": win,
            "breakeven_win_%": breakeven,
            "edge_pp": win - breakeven,
            "gross_%": float(g["gross_r"].mean() * 100.0),
            "net_%": float(g["r"].mean() * 100.0),
            "cost_%": float(g["cost_r"].mean() * 100.0),
            "timeout_%": float((g["exit_reason"] == "timeout").mean() * 100.0),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# B) what budget-neutral sizing would have earned
# --------------------------------------------------------------------------


def multipliers(trades: pd.DataFrame, strength: float, kind: str,
                threshold: float, prob_col: str = "prob") -> pd.Series:
    """A size multiplier in [1-strength, 1+strength] with mean exactly 1 per window.

    `kind="p"` ramps linearly in the probability itself — what an implementation would
    actually compute from a config field. `kind="rank"` ramps in the within-window
    percentile rank, which is invariant to how the probabilities happen to be
    distributed.

    The two are not interchangeable, and the difference is not cosmetic. This model's
    p sits packed against the threshold with a thin tail (buckets 1-3 span 0.550-0.591
    while bucket 5 reaches 0.762), so a ramp linear in p hands almost the whole
    redistribution to a handful of trades, while the same ramp on a flat p spreads it
    evenly. That matters when comparing against a control: `rank` gives both arms the
    identical multiplier distribution and so compares like with like, whereas `p`
    compares two differently-shaped bets and its z-score means nothing on its own.
    See `matched_multipliers` for the control that makes `p` judgeable.

    Renormalising to mean 1 inside each window is what makes this a redistribution
    rather than a disguised raise: the window puts the same total money to work, and
    the exposure ceiling `position_pct x max_open_positions` keeps its meaning.
    """
    out = pd.Series(1.0, index=trades.index)
    for _, g in trades.groupby("window"):
        p = g[prob_col]
        if kind == "rank":
            u = p.rank(method="average", pct=True)
        else:
            lo, hi = threshold, float(p.max())
            u = (p - lo) / (hi - lo) if hi > lo else pd.Series(0.5, index=p.index)
        m = 1.0 + strength * (2.0 * u - 1.0)   # into [1-strength, 1+strength]
        out.loc[g.index] = m / m.mean()        # mean 1 -> same money, redistributed
    return out


def multiplier_shape(trades: pd.DataFrame, mult: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """The real run's multiplier as a function of within-window rank, (u, m) sorted.

    Pooled over windows: the shape barely moves between them, and pooling keeps the
    curve smooth enough to interpolate onto a control run of a different size.
    """
    u = (trades.assign(m=mult)
               .groupby("window")["prob"].rank(method="average", pct=True))
    order = np.argsort(u.to_numpy())
    return u.to_numpy()[order], mult.to_numpy()[order]


def matched_multipliers(trades: pd.DataFrame, shape: tuple[np.ndarray, np.ndarray]
                        ) -> pd.Series:
    """Give these trades the real run's multiplier *distribution*, ordered by their p.

    This is what makes the `p` ramp testable. Judged against a control that recomputes
    the ramp from its own probabilities, the real p-ramp is compared with a bet of a
    different shape — concentrated on a few trades here, spread evenly there — and the
    comparison flatters whichever arm happens to be more concentrated. Fixing the
    multiplier distribution and letting only the *ordering* differ isolates the one
    thing under test: whether the model sorts trades better than noise does.
    """
    u_ref, m_ref = shape
    out = pd.Series(1.0, index=trades.index)
    for _, g in trades.groupby("window"):
        u = g["prob"].rank(method="average", pct=True).to_numpy()
        m = np.interp(u, u_ref, m_ref)
        out.loc[g.index] = m / m.mean()
    return out


def sizing_gain_pp(trades: pd.DataFrame, mult: pd.Series, position_pct: float) -> float:
    """Change in a window's return, in percentage points, from that multiplier.

    delta = position_pct * n * mean((m-1) * r): each trade risks `position_pct` of
    equity, so scaling it by m moves the account by position_pct*(m-1)*r.
    """
    return float(position_pct * len(trades) * ((mult - 1.0) * trades["r"]).mean() * 100.0)


def sizing_table(trades: pd.DataFrame, position_pct: float, threshold: float) -> pd.DataFrame:
    rows = []
    for kind in ("rank", "p"):
        for strength in STRENGTHS:
            per_window = []
            for w, g in trades.groupby("window"):
                m = multipliers(g, strength, kind, threshold)
                per_window.append({"window": w, "regime": g["regime"].iloc[0],
                                   "pp": sizing_gain_pp(g, m, position_pct)})
            pw = pd.DataFrame(per_window)
            rows.append({
                "ramp": kind, "strength": strength,
                "zakres": f"{1 - strength:.2f}–{1 + strength:.2f}x",
                "avg_pp_per_window": pw["pp"].mean(),
                "median_pp": pw["pp"].median(),
                "windows_positive": int((pw["pp"] > 0).sum()),
                "windows": len(pw),
                **{f"pp_{r}": pw.loc[pw["regime"] == r, "pp"].mean()
                   for r in ("wzrosty", "spadki", "bok") if (pw["regime"] == r).any()},
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# C) the null: how big does this number get when p means nothing?
# --------------------------------------------------------------------------
#
# Two nulls, and the gap between them is the point.
#
# The obvious one shuffles p among the trades of a window. It is also wrong, and
# measurably so: it treats each trade as its own draw, when eighteen crypto pairs
# opened within hours of each other rise and fall together. The real number of
# independent observations is nearer the number of *bars* than the number of trades,
# so a per-trade shuffle produces a null that is far too narrow and hands out
# significance to anything. Kept only to show how much too narrow.
#
# The null to read replaces the model with an uninformative one and runs the entire
# machine again — same board, same cap, same best_first, same wallet. Whatever gain
# survives *that* is the model's; whatever both produce is the mechanism. This is
# what `lab.control_bundles` exists for, and it catches an artifact the shuffle
# cannot see: `best_first` on a binding cap makes a high p the ticket into a
# contested bar, and contested bars are not average bars, so p ends up correlated
# with the outcome even when p is noise.


def gain_of(trades: pd.DataFrame, position_pct: float, threshold: float,
            strength: float, kind: str) -> float:
    """Mean pp per window of the budget-neutral ramp — the statistic under test."""
    return float(np.mean([
        sizing_gain_pp(g, multipliers(g, strength, kind, threshold), position_pct)
        for _, g in trades.groupby("window")
    ]))


def shuffle_null(trades: pd.DataFrame, position_pct: float, threshold: float,
                 strength: float, kind: str, n_perm: int, seed: int) -> dict:
    """The too-narrow null: p shuffled among the trades of a window."""
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(n_perm):
        gains = []
        for _, g in trades.groupby("window"):
            shuffled = g.copy()
            shuffled["shuffled_prob"] = rng.permutation(g["prob"].to_numpy())
            m = multipliers(shuffled, strength, kind, threshold, prob_col="shuffled_prob")
            gains.append(sizing_gain_pp(shuffled, m, position_pct))
        null.append(float(np.mean(gains)))
    return summarize_null(np.array(null), n_perm)


def control_null(cfg, pairs, windows, min_train_bars: int, position_pct: float,
                 n_seeds: int, seed0: int,
                 shape: tuple[np.ndarray, np.ndarray]) -> dict:
    """The null to read: the same book run on a model that knows nothing.

    Every seed is a fresh set of independent per-pair probabilities, so each run
    reproduces the selection, the contention for slots and the cross-sectional
    correlation between simultaneous trades — everything except information. The
    multiplier distribution is pinned to the real run's via `matched_multipliers`, so
    the arms differ only in the ordering of the trades.
    """
    gains = []
    for k in range(n_seeds):
        t = collect_trades(cfg, pairs, windows, "random", min_train_bars,
                           seed=seed0 + 1000 * k, quiet=True)
        m = matched_multipliers(t, shape)
        gains.append(float(np.mean([
            sizing_gain_pp(g, m.loc[g.index], position_pct)
            for _, g in t.groupby("window")
        ])))
        if (k + 1) % 5 == 0:
            log.info("  control: %d/%d runs, mean %+0.3f pp",
                     k + 1, n_seeds, float(np.mean(gains)))
    return summarize_null(np.array(gains), n_seeds)


def summarize_null(null: np.ndarray, n: int) -> dict:
    sd = float(null.std(ddof=1)) if len(null) > 1 else 0.0
    return {"mean_pp": float(null.mean()), "sd_pp": sd, "n": n,
            "values": [round(float(v), 4) for v in null]}


def stands_against(real: float, null: dict) -> dict:
    vals = np.array(null["values"])
    return {
        "real_pp": real,
        "null_mean_pp": null["mean_pp"],
        "null_sd_pp": null["sd_pp"],
        "percentile": float((vals < real).mean() * 100.0),
        "z": float((real - null["mean_pp"]) / null["sd_pp"]) if null["sd_pp"] > 0 else 0.0,
        "n": null["n"],
    }


# --------------------------------------------------------------------------
# D) the competing lever: just raise the threshold
# --------------------------------------------------------------------------


def threshold_table(trades: pd.DataFrame, position_pct: float,
                    n_buckets: int) -> pd.DataFrame:
    """What dropping the weakest signals outright would have been worth.

    If p carries information, cutting the bottom and shrinking the bottom are nearly
    the same bet — except that cutting stops paying fees on those trades, and cost is
    what decides the sign of this strategy. The engine already has the field for it
    (`strategy.prob_threshold`) and books running at 0.50 / 0.55 / 0.65.

    Same class of caveat as the sizing estimate, in the other direction: a dropped
    trade frees a slot the book may hand to the next candidate, which this does not
    model. It is the pessimistic end of what cutting is worth — and it is why table E
    exists, which does model it by simply running the book again at a fixed threshold.
    Read E to decide anything; this table only says whether the ordering is there.

    Unlike the sizing table, this one is *not* budget-neutral, and that makes the raw
    number misleading on its own: when the average trade loses money, dropping any
    trades looks like a gain, so a column of plus signs here can mean nothing but "the
    strategy is under water". Hence `losowo_pp` — what cutting the same *number* of
    trades at random would have given — and `excess_pp`, the difference. Only the
    excess is evidence that p is doing the choosing; the random control run makes this
    plain, printing a fat positive raw column against an excess of roughly zero.
    """
    rows = []
    for q in range(1, n_buckets):
        per_window = []
        for w, g in trades.groupby("window"):
            cut = g["prob"].quantile(q / n_buckets)
            dropped = g[g["prob"] < cut]
            by_p = float(-position_pct * dropped["r"].sum() * 100.0)
            # dropping the same count at random removes, in expectation, that share
            # of the window's total return
            share = len(dropped) / len(g) if len(g) else 0.0
            at_random = float(-position_pct * share * g["r"].sum() * 100.0)
            per_window.append({
                "window": w, "pp": by_p, "rand_pp": at_random,
                "dropped": len(dropped), "cut": cut,
            })
        pw = pd.DataFrame(per_window)
        rows.append({
            "cut_off": f"{q}/{n_buckets} weakest",
            "avg_threshold": pw["cut"].mean(),
            "transakcji_mniej": int(pw["dropped"].sum()),
            "avg_pp_per_window": pw["pp"].mean(),
            "random_pp": pw["rand_pp"].mean(),
            "excess_pp": (pw["pp"] - pw["rand_pp"]).mean(),
            "windows_positive": int(((pw["pp"] - pw["rand_pp"]) > 0).sum()),
            "windows": len(pw),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# E) the same question asked the only way that can be acted on
# --------------------------------------------------------------------------


def threshold_sweep(cfg, pairs: dict[str, pd.DataFrame], windows: list[Window],
                    min_train_bars: int, thresholds: list[float],
                    allocations: tuple[str, ...] = ("fcfs", "best_first")) -> pd.DataFrame:
    """Run the whole book at each fixed threshold, per window, strict OOS.

    Tables A-D work on a pool of trades all opened at threshold 0.55, so the only
    thing they can express is a *quantile inside a window* — "the weakest three
    fifths". That is not something `config.yaml` can hold. Worse, the model is
    refitted before every window, so the level of p drifts and one window's 60th
    percentile is not another's. This asks the question in the currency the engine
    actually speaks: a number in a config field.

    It also removes table D's one-sided error. Raising the threshold does not simply
    delete trades — it frees slots, and under a binding cap the next candidate takes
    them. Only a real run knows what that candidate did.

    `fcfs` is listed first because it is what the engine does: `_maybe_enter` runs per
    symbol as its candle arrives, so the config order decides, not the probability.
    `best_first` comes along because it costs nothing (the cached probabilities are
    reused across every cell) and a conclusion that flips between the two would be a
    conclusion about slot allocation, not about the threshold.
    """
    strat = cfg.strategy
    rows = []
    for window in windows:
        if not enough_history(pairs, window, min_train_bars):
            continue
        bh = float(np.mean([buy_hold_pct(df, window) for df in pairs.values()]))
        log.info("window %s (buy&hold %+.1f%%): training once, sweeping thresholds...",
                 window.label(), bh)
        bundles = train_for_geometry(pairs, cfg, strat.tp_atr_mult, strat.sl_atr_mult,
                                     int(strat.horizon_bars), window)
        wframes, trade_from = window_frames(pairs, window, strat.warmup_bars)
        # features and probabilities do not depend on the threshold, so one cache
        # serves every cell of the sweep
        cache: dict = {}
        for allocation in allocations:
            for t in thresholds:
                tcfg = with_strategy(cfg, prob_threshold=t)
                s = run_book_backtest(wframes, bundles, tcfg, allocation=allocation,
                                      trade_from=trade_from, cache=cache)["summary"]
                rows.append({
                    "window": window.label(), "regime": regime_of(bh),
                    "allocation": allocation, "threshold": t,
                    "return_%": s["total_return_pct"], "sharpe": s["sharpe"],
                    "maxDD_%": s["max_drawdown_pct"], "trades": s["n_trades"],
                    "signals": s["signals"], "no_slot": s["slot_blocked"],
                    "in_market_%": s.get("time_in_market_pct", 0.0),
                })
    return pd.DataFrame(rows)


def sweep_summary(sweep: pd.DataFrame, base: float) -> pd.DataFrame:
    """Per allocation and threshold: the mean across windows, and the paired
    difference against the shipped threshold — paired, because the windows differ
    from each other far more than the thresholds do."""
    rows = []
    for (alloc, t), g in sweep.groupby(["allocation", "threshold"]):
        ref = sweep[(sweep["allocation"] == alloc) & (sweep["threshold"] == base)]
        paired = (g.set_index("window")["return_%"] - ref.set_index("window")["return_%"]).dropna()
        rows.append({
            "allocation_rule": alloc, "threshold": t,
            "avg_return_%": g["return_%"].mean(),
            "median_%": g["return_%"].median(),
            f"vs {base:.2f} (pp)": paired.mean(),
            "windows_better": int((paired > 0).sum()),
            "windows": len(paired),
            "trades": int(g["trades"].sum()),
            "avg_in_market_%": g["in_market_%"].mean(),
        })
    return pd.DataFrame(rows)


def fmt(v) -> str:
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=6, help="how many OOS blocks")
    ap.add_argument("--window-days", type=int, default=120)
    ap.add_argument("--buckets", type=int, default=5)
    ap.add_argument("--min-train-bars", type=int, default=1200)
    ap.add_argument("--permutations", type=int, default=200,
                    help="draws for the (too narrow) shuffle null")
    ap.add_argument("--control-runs", type=int, default=30,
                    help="whole-book runs on an uninformative model — the null to read")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--thresholds", nargs="+", type=float,
                    default=[0.50, 0.55, 0.58, 0.60, 0.62, 0.65],
                    help="fixed prob_threshold values for the table E sweep")
    ap.add_argument("--skip-sweep", action="store_true",
                    help="skip table E (it retrains once per window)")
    ap.add_argument("--control", choices=["random", "always_long", "always_short"],
                    default=None, help="replace the model with a control (sanity check)")
    args = ap.parse_args()

    cfg = load_config()
    strat, risk = cfg.strategy, cfg.risk
    breakeven = strat.sl_atr_mult / (strat.tp_atr_mult + strat.sl_atr_mult) * 100.0
    rt = round_trip_pct(cfg.costs.taker_fee, cfg.costs.maker_fee,
                        cfg.costs.slippage_bps, cfg.execution.order_style)

    pairs = load_pairs(cfg)
    windows = [Window(i * args.window_days, args.window_days) for i in range(args.windows)]
    trades = collect_trades(cfg, pairs, windows, args.control, args.min_train_bars)

    cal = calibration_table(trades, args.buckets, breakeven)
    siz = sizing_table(trades, risk.position_pct, strat.prob_threshold)
    thr = threshold_table(trades, risk.position_pct, args.buckets)
    strength = STRENGTHS[-1]
    nulls = {}
    for kind in ("rank", "p"):
        mult = multipliers(trades, strength, kind, strat.prob_threshold)
        real = gain_of(trades, risk.position_pct, strat.prob_threshold, strength, kind)
        shuf = shuffle_null(trades, risk.position_pct, strat.prob_threshold,
                            strength, kind, args.permutations, args.seed)
        log.info("null distribution for ramp %s: %d runs on a model without knowledge...",
                 kind, args.control_runs)
        ctrl = control_null(cfg, pairs, windows, args.min_train_bars, risk.position_pct,
                            args.control_runs, args.seed,
                            multiplier_shape(trades, mult))
        nulls[kind] = {"shuffle": stands_against(real, shuf),
                       "model_without_knowledge": stands_against(real, ctrl)}

    head = "PROBABILITY CALIBRATION" + (f" — CONTROL: {args.control}" if args.control else "")
    print()
    print("=" * 100)
    print(head)
    print("=" * 100)
    print(f"windows: {trades['window'].nunique()} x {args.window_days} days, "
          f"trades: {len(trades)}, pairs: {len(pairs)}, "
          f"threshold: {strat.prob_threshold}, position: {risk.position_pct:.0%} of the "
          f"account, cap: {risk.max_open_positions}")
    print(f"TP/SL geometry {strat.tp_atr_mult}/{strat.sl_atr_mult} -> break-even at "
          f"{breakeven:.1f}% wins; round-trip cost {rt:.3f}%")

    print("\nA) CALIBRATION CURVE — quantile buckets computed within window and side")
    print(cal.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print("   The question is whether `net_%` rises from bucket to bucket. If it does not,")
    print("   varying the position size has nothing to draw on.")

    print("\nB) GAIN FROM VARYING SIZE, BUDGET-NEUTRAL (an upper bound, see the docstring)")
    print(siz.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))

    print(f"\nC) DOES IT CLEAR ZERO — ramp of strength {strength}")
    for kind, pair in nulls.items():
        print(f"   ramp {kind}: actual {pair['shuffle']['real_pp']:+.3f} pp per window")
        for label, n in (("shuffled p             ", pair["shuffle"]),
                         ("model without knowledge", pair["model_without_knowledge"])):
            print(f"      against {label}: {n['null_mean_pp']:+.3f} ± {n['null_sd_pp']:.3f} pp"
                  f"  ->  percentile {n['percentile']:.1f}, z = {n['z']:+.2f}"
                  f"  (n={n['n']})")
    print("   Read only the `model without knowledge` row: same board, same cap, same")
    print("   multiplier distribution — the one difference is that p knows nothing.")
    print("   Shuffling breaks apart pairs that entered together and move together, so its")
    print("   spread is too narrow and lets everything through, the knowledge-free model")
    print("   included. The gate: percentile > 95 (z > ~1.65).")

    print("\nD) COMPETITIVE LEVERAGE — cut the weak instead of shrinking their size")
    print(thr.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    print("   Read `excess_pp`, not `avg_pp_per_window`: when the average trade is negative,")
    print("   cutting anything comes out positive, so all that counts is the edge over")
    print("   cutting the same number of trades at random. Table E is what decides.")

    sweep = pd.DataFrame()
    if not args.skip_sweep:
        log.info("table E: sweeping thresholds %s...", args.thresholds)
        sweep = threshold_sweep(cfg, pairs, windows, args.min_train_bars, args.thresholds)
        agg = sweep_summary(sweep, strat.prob_threshold)
        print("\nE) FIXED THRESHOLD — a full book backtest, one per window and threshold")
        print(agg.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))
        print("   The only table expressed in something you can type into the config, and")
        print("   the only one that counts a cut signal freeing a slot for the next")
        print("   candidate. `fcfs` is what the engine does; `best_first` only checks that")
        print("   the conclusion does not depend on the allocation rule.")
        print("\n   by market regime:")
        by_reg = (sweep[sweep["allocation"] == "fcfs"]
                  .pivot_table(index="threshold", columns="regime", values="return_%", aggfunc="mean"))
        print("   " + by_reg.to_string(float_format=lambda v: f"{v:+.2f}").replace("\n", "\n   "))
    print("=" * 100)

    report = {
        "control": args.control,
        "windows": [w.label() for w in windows],
        "window_days": args.window_days,
        "n_trades": len(trades),
        "breakeven_win_pct": breakeven,
        "round_trip_cost_pct": rt,
        "strategy": strat.model_dump(),
        "position_pct": risk.position_pct,
        "calibration": cal.to_dict("records"),
        "sizing": siz.to_dict("records"),
        "permutation": nulls,
        "threshold": thr.to_dict("records"),
        "sweep": sweep.to_dict("records") if len(sweep) else [],
        "sweep_mean": (sweep_summary(sweep, strat.prob_threshold).to_dict("records")
                       if len(sweep) else []),
    }
    out_dir = cfg.paths.models_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "research_prob_calibration" + (f"_{args.control}" if args.control else "")
    (out_dir / f"{name}.json").write_text(json.dumps(report, indent=2, default=str))
    log_experiment(cfg.paths.runtime_dir, {
        "kind": "prob_calibration",
        "control": args.control,
        "windows": [w.label() for w in windows],
        "calibration": cal.to_dict("records"),
        "sizing": siz.to_dict("records"),
        "permutation": nulls,
        "report": f"{name}.json",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
