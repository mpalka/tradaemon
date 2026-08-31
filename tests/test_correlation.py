"""Tests for the diversification screen (portfolio/correlation.py)."""

import numpy as np
import pandas as pd
import pytest

from tradaemon.portfolio.correlation import (
    classify,
    monthly_returns,
    screen,
    summarize_screen,
)


def daily_panel(n_days: int, series: dict[str, np.ndarray]) -> pd.DataFrame:
    idx = pd.date_range("2016-01-01", periods=n_days, freq="D", tz="UTC")
    return pd.DataFrame(series, index=idx)


def walk(daily_returns: np.ndarray, start: float = 100.0) -> np.ndarray:
    return start * np.cumprod(1.0 + daily_returns)


def test_monthly_returns_collapse_daily_prices():
    panel = daily_panel(400, {"A": walk(np.full(400, 0.001))})
    m = monthly_returns(panel)
    assert len(m) == 13                      # 400 days spans 14 month-ends -> 13 returns
    assert (m["A"] > 0).all()


def test_screen_ranks_the_least_correlated_first():
    rng = np.random.default_rng(1)
    n = 2600
    mkt = rng.normal(0.0004, 0.01, n)
    panel = daily_panel(n, {
        "VT": walk(mkt),
        "TWIN": walk(mkt * 0.99 + rng.normal(0, 0.001, n)),   # nearly identical
        "INDEP": walk(rng.normal(0.0004, 0.01, n)),           # unrelated
    })
    out = screen(panel, "VT", years=10)
    assert out["symbol"].iloc[0] == "INDEP"        # least correlated ranks first
    assert out.set_index("symbol").loc["TWIN", "corr"] > 0.9
    assert abs(out.set_index("symbol").loc["INDEP", "corr"]) < 0.3


def test_screen_reports_the_rolling_range_not_just_the_mean():
    """The headline number can hide a correlation that flips — that range is the
    whole point of the screen."""
    rng = np.random.default_rng(2)
    n = 2600
    mkt = rng.normal(0.0004, 0.01, n)
    half = n // 2
    flipper = np.concatenate([-mkt[:half], mkt[half:]])   # hedges, then joins in
    panel = daily_panel(n, {"VT": walk(mkt), "FLIP": walk(flipper)})
    row = screen(panel, "VT", years=10).set_index("symbol").loc["FLIP"]
    assert row["roll_min"] < -0.5 and row["roll_max"] > 0.5
    assert row["verdict"] == "NIESTABILNY" or row["cagr_pct"] <= 0


def test_classify_separates_the_four_readings():
    assert classify(mean_corr=0.10, peak_corr=0.30, cagr_pct=8.0) == "KANDYDAT"
    assert classify(mean_corr=0.10, peak_corr=0.75, cagr_pct=8.0) == "NIESTABILNY"
    assert classify(mean_corr=0.80, peak_corr=0.90, cagr_pct=8.0) == "SKORELOWANY"
    assert classify(mean_corr=0.10, peak_corr=0.30, cagr_pct=-2.0) == "TRACI"
    # inverse/volatility products: negative by construction, decaying while they wait
    assert classify(mean_corr=-0.85, peak_corr=-0.60, cagr_pct=-12.0) == "PUŁAPKA"


def test_a_negatively_correlated_loser_is_never_a_candidate():
    """An inverse product tops any correlation ranking and still destroys capital —
    the screen must not present it as the answer."""
    rng = np.random.default_rng(3)
    n = 2600
    mkt = rng.normal(0.0006, 0.01, n)
    panel = daily_panel(n, {"VT": walk(mkt), "SH": walk(-mkt - 0.0004)})  # inverse + decay
    row = screen(panel, "VT", years=10).set_index("symbol").loc["SH"]
    assert row["corr"] < -0.9 and row["cagr_pct"] < 0
    assert row["verdict"] == "PUŁAPKA"


def test_screen_skips_assets_without_enough_history():
    rng = np.random.default_rng(4)
    n = 2600
    panel = daily_panel(n, {"VT": walk(rng.normal(0.0004, 0.01, n)),
                            "YOUNG": walk(rng.normal(0.0004, 0.01, n))})
    panel.loc[panel.index[:-300], "YOUNG"] = np.nan   # only ~10 months of history
    assert "YOUNG" not in list(screen(panel, "VT", years=10)["symbol"])


def test_one_young_fund_does_not_shorten_everyone_elses_window():
    """Each pair is scored on its own overlap. Aligning the whole panel on the
    youngest ticker turned a 10-year screen into a 5.5-year one without saying so."""
    rng = np.random.default_rng(6)
    n = 3000
    mkt = rng.normal(0.0004, 0.01, n)
    panel = daily_panel(n, {
        "VT": walk(mkt),
        "OLD": walk(rng.normal(0.0004, 0.01, n)),
        "YOUNG": walk(rng.normal(0.0004, 0.01, n)),
    })
    panel.loc[panel.index[:-2200], "YOUNG"] = np.nan   # launched partway through
    out = screen(panel, "VT", years=10).set_index("symbol")
    assert out.loc["OLD", "months"] > out.loc["YOUNG", "months"]
    assert out.loc["OLD", "months"] >= 90              # keeps its own long history


def test_as_of_hides_everything_after_the_cutoff():
    """The whole point of --as-of: the screen must not see the future it is about to
    be judged on."""
    rng = np.random.default_rng(7)
    n = 5000                       # each half must clear the 60-month minimum
    mkt = rng.normal(0.0004, 0.01, n)
    half = n // 2
    # HEDGE diversifies in the first half, then joins the market in the second
    hedge = np.concatenate([-mkt[:half], mkt[half:]])
    panel = daily_panel(n, {"VT": walk(mkt), "HEDGE": walk(hedge)})
    cutoff = panel.index[half]

    past = screen(panel, "VT", years=10, as_of=cutoff).set_index("symbol")
    full = screen(panel, "VT", years=10).set_index("symbol")
    assert past.loc["HEDGE", "corr"] < -0.5      # looked like a perfect hedge then
    assert full.loc["HEDGE", "corr"] > past.loc["HEDGE", "corr"]  # ...and stopped being one


def test_screen_rejects_a_missing_benchmark():
    panel = daily_panel(400, {"A": walk(np.full(400, 0.001))})
    with pytest.raises(KeyError):
        screen(panel, "NOPE", years=10)


def test_summary_states_plainly_when_nothing_is_negative():
    rng = np.random.default_rng(5)
    n = 2600
    mkt = rng.normal(0.0004, 0.01, n)
    panel = daily_panel(n, {"VT": walk(mkt),
                            "A": walk(mkt * 0.8 + rng.normal(0, 0.004, n))})
    text = " ".join(summarize_screen(screen(panel, "VT", years=10), "VT"))
    assert "0 z 1" in text or "UJEMNEJ" in text
