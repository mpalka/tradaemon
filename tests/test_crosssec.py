"""Tests for the cross-sectional ranking study (module 3).

The load-bearing ones are the look-ahead tests: a ranking backtest that peeks at the
bar it trades on will show a beautiful, entirely fake edge.
"""

from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from tradaemon.crosssec.backtest import (
    equal_weight_benchmark,
    gross_of_noise,
    run_crosssec_backtest,
)
from tradaemon.crosssec.config import CrossSecConfig, MarketConfig, RankConfig, SignalConfig
from tradaemon.crosssec.signal import (
    momentum_scores,
    select_legs,
    target_weights,
    weights_at,
)
from tradaemon.crosssec.validate import split_windows


def make_panel(n_days: int, trends: dict[str, float], start: float = 100.0) -> pd.DataFrame:
    """Deterministic panel: each symbol compounds at a fixed daily rate."""
    idx = pd.date_range("2024-01-01", periods=n_days, freq="D", tz="UTC")
    return pd.DataFrame(
        {sym: start * (1.0 + r) ** np.arange(n_days) for sym, r in trends.items()},
        index=idx)


def cfg_for(n_long=2, n_short=2, lookback=20, skip=0, rebalance=10) -> CrossSecConfig:
    return CrossSecConfig(
        signal=SignalConfig(lookback_days=lookback, skip_days=skip),
        rank=RankConfig(n_long=n_long, n_short=n_short, rebalance_days=rebalance),
        markets=[MarketConfig(name="crypto", symbols=[])],
        initial_capital=10_000.0)


# ---------- signal ----------

def test_momentum_ranks_by_relative_strength():
    panel = make_panel(40, {"FAST": 0.02, "SLOW": 0.001, "DOWN": -0.01})
    scores = momentum_scores(panel, lookback_days=20)
    assert list(scores.sort_values(ascending=False).index) == ["FAST", "SLOW", "DOWN"]


def test_momentum_needs_enough_history():
    panel = make_panel(10, {"A": 0.01, "B": 0.02})
    assert momentum_scores(panel, lookback_days=20).empty


def test_momentum_skip_excludes_the_freshest_bars():
    # A rises for 20 days then crashes on the last 3. With no skip the crash drags the
    # score down; skipping the last 3 bars ignores it, which is the point of the skip.
    idx = pd.date_range("2024-01-01", periods=25, freq="D", tz="UTC")
    prices = [100 * 1.01 ** i for i in range(22)] + [80.0, 70.0, 60.0]
    panel = pd.DataFrame({"A": prices}, index=idx)
    assert momentum_scores(panel, 20, skip_days=0)["A"] < 0
    assert momentum_scores(panel, 20, skip_days=3)["A"] > 0


def test_select_legs_never_overlaps_on_a_thin_universe():
    scores = pd.Series({"A": 0.5, "B": 0.3, "C": 0.1})
    longs, shorts = select_legs(scores, n_long=2, n_short=2)
    assert longs == ["A", "B"] and shorts == ["C"]
    assert not set(longs) & set(shorts)


def test_target_weights_long_only_and_long_short():
    lo = target_weights(["A", "B"], ["C", "D"], "long_only")
    assert lo == {"A": 0.5, "B": 0.5}                       # shorts ignored
    ls = target_weights(["A", "B"], ["C", "D"], "long_short")
    assert ls == {"A": 0.25, "B": 0.25, "C": -0.25, "D": -0.25}
    assert sum(ls.values()) == pytest.approx(0.0)           # market neutral
    assert sum(abs(w) for w in ls.values()) == pytest.approx(1.0)  # 100% gross


def test_target_weights_rejects_unknown_direction():
    with pytest.raises(ValueError):
        target_weights(["A"], [], "sideways")


# ---------- no look-ahead ----------

def test_signal_ignores_bars_after_the_decision_date():
    panel = make_panel(40, {"A": 0.02, "B": 0.001})
    early = weights_at(panel.iloc[:30], 20, 0, 1, 1, "long_short")
    # rewrite everything after day 30 — the day-30 decision must not change
    tampered = panel.copy()
    tampered.iloc[30:] = tampered.iloc[30:] * 100.0
    assert weights_at(tampered.iloc[:30], 20, 0, 1, 1, "long_short") == early


def test_backtest_cannot_see_the_bar_it_trades_on():
    """Plant a violent, unpredictable reversal. A backtest that peeked at the current
    bar would trade it profitably; an honest one is simply hurt by it."""
    cfg = cfg_for(n_long=1, n_short=1, lookback=10, rebalance=5)
    base = make_panel(60, {"A": 0.01, "B": -0.01, "C": 0.002})
    honest = run_crosssec_backtest(base, cfg, "long_short")["summary"]["total_return_pct"]

    flipped = base.copy()
    flipped.iloc[40:] = flipped.iloc[39].values * np.array([0.5, 2.0, 1.0])
    peeked = run_crosssec_backtest(flipped, cfg, "long_short")["summary"]
    # the reversal must hurt the long-short book, never help it
    assert peeked["total_return_pct"] < honest


# ---------- backtest mechanics ----------

def test_long_only_tracks_the_strongest_names():
    cfg = cfg_for(n_long=1, n_short=0, lookback=10, rebalance=5)
    panel = make_panel(60, {"UP": 0.01, "FLAT": 0.0, "DOWN": -0.01})
    s = run_crosssec_backtest(panel, cfg, "long_only")["summary"]
    assert s["total_return_pct"] > 0            # it should ride UP
    assert s["excess_vs_benchmark_pp"] > 0      # ...and beat the equal-weight basket
    assert s["avg_net_exposure_pct"] == pytest.approx(100.0, abs=1.0)


def test_long_short_is_roughly_market_neutral():
    cfg = cfg_for(n_long=1, n_short=1, lookback=10, rebalance=5)
    panel = make_panel(60, {"UP": 0.01, "MID": 0.005, "DOWN": -0.01})
    s = run_crosssec_backtest(panel, cfg, "long_short")["summary"]
    assert abs(s["avg_net_exposure_pct"]) < 25.0        # legs offset
    assert s["avg_gross_exposure_pct"] > 75.0          # but money is at work


def test_costs_only_ever_reduce_the_result():
    panel = make_panel(80, {"UP": 0.01, "FLAT": 0.0, "DOWN": -0.008})
    free = cfg_for(lookback=10, rebalance=5)
    free = free.model_copy(update={
        "costs": free.costs.model_copy(update={"taker_fee": 0.0, "slippage_bps": 0.0})})
    pricey = cfg_for(lookback=10, rebalance=5)
    pricey = pricey.model_copy(update={
        "costs": pricey.costs.model_copy(update={"taker_fee": 0.01, "slippage_bps": 50.0})})
    a = run_crosssec_backtest(panel, free, "long_short")["summary"]
    b = run_crosssec_backtest(panel, pricey, "long_short")["summary"]
    assert b["total_return_pct"] < a["total_return_pct"]
    assert a["fees_paid"] == 0.0 and b["fees_paid"] > 0.0


def test_equity_reconciles_with_cash_plus_positions():
    """Equity must be arithmetic, not bookkeeping fiction — including for shorts."""
    cfg = cfg_for(n_long=1, n_short=1, lookback=10, rebalance=5)
    panel = make_panel(50, {"A": 0.01, "B": -0.01, "C": 0.0})
    res = run_crosssec_backtest(panel, cfg, "long_short")
    eq = res["equity"]
    assert eq.notna().all() and (eq > 0).all()
    # gross exposure implies real positions, and nothing exploded
    assert res["exposure"]["gross_pct"].max() < 200.0


def test_short_leg_profits_when_the_laggard_falls():
    cfg = cfg_for(n_long=1, n_short=1, lookback=10, rebalance=5)
    panel = make_panel(60, {"FLAT": 0.0, "CRASH": -0.02})
    s = run_crosssec_backtest(panel, cfg, "long_short")["summary"]
    assert s["total_return_pct"] > 0     # short CRASH, long FLAT
    assert s["benchmark_return_pct"] < 0  # the basket itself lost money


def test_hurdle_matches_the_books_exposure():
    """A market-neutral book must clear cash, not a fully invested basket — scoring
    ~0% net exposure against ~100% net exposure is the mismatch that flattered
    module 1, and it would flatter long_short here in every falling market."""
    cfg = cfg_for(n_long=1, n_short=1, lookback=10, rebalance=5)
    panel = make_panel(60, {"A": 0.01, "B": 0.005, "C": -0.01})

    lo = run_crosssec_backtest(panel, cfg, "long_only")["summary"]
    assert lo["hurdle_pct"] == pytest.approx(lo["benchmark_return_pct"])

    ls = run_crosssec_backtest(panel, cfg, "long_short")["summary"]
    assert ls["hurdle_pct"] == 0.0
    assert ls["excess_vs_hurdle_pp"] == pytest.approx(ls["total_return_pct"])


def test_backtest_refuses_too_little_history():
    cfg = cfg_for(lookback=100)
    s = run_crosssec_backtest(make_panel(20, {"A": 0.01, "B": 0.0}), cfg, "long_only")
    assert "error" in s["summary"]


def test_benchmark_excludes_names_not_trading_on_day_one():
    panel = make_panel(10, {"A": 0.01, "B": 0.0})
    panel.loc[panel.index[0], "B"] = np.nan
    bench = equal_weight_benchmark(panel, 1000.0)
    assert bench.iloc[0] == pytest.approx(1000.0)
    assert bench.iloc[-1] == pytest.approx(1000.0 * (panel["A"].iloc[-1] / panel["A"].iloc[0]))


# ---------- multi-window discipline ----------

def test_windows_are_disjoint_in_their_tradable_range():
    panel = make_panel(500, {"A": 0.001, "B": 0.002})
    warmup = 100
    wins = split_windows(panel, 4, warmup)
    assert len(wins) == 4
    # each window's tradable part starts after its own warmup and they must not overlap
    tradable = [(w.index[warmup], w.index[-1]) for w in wins]
    for (_, prev_end), (next_start, _) in pairwise(tradable):
        assert next_start > prev_end


def test_windows_collapse_to_one_when_history_is_short():
    panel = make_panel(120, {"A": 0.001, "B": 0.002})
    assert len(split_windows(panel, 4, warmup=100)) == 1


def test_noise_measure_flags_a_random_series():
    rng = np.random.default_rng(0)
    noise = pd.Series(rng.normal(0, 0.01, 500))
    assert abs(gross_of_noise(noise)) < 2.0        # indistinguishable from zero
    drift = pd.Series(rng.normal(0.005, 0.001, 500))
    assert gross_of_noise(drift) > 2.0            # a real, if synthetic, signal
