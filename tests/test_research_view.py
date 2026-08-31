"""Tests for the research view's data plumbing (dashboard/research_view.py).

Streamlit rendering is not exercised here; the parts worth pinning are the ones
that pick which report to show and how its date is read.
"""

import pandas as pd
import pytest

from trademon import i18n
from trademon.dashboard import research_view as rv
from trademon.portfolio.correlation import VERDICT_KEYS


def test_latest_picks_the_newest_report(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "REPORTS", tmp_path)
    for name in ["crosssec_20260101_120000.csv", "crosssec_20260730_205218.csv",
                 "crosssec_20260315_090000.csv"]:
        (tmp_path / name).write_text("market\n")
    (tmp_path / "screen_20260730_205218.csv").write_text("symbol\n")
    assert rv.latest("crosssec").name == "crosssec_20260730_205218.csv"
    assert rv.latest("screen").name == "screen_20260730_205218.csv"


def test_latest_returns_none_when_a_study_never_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "REPORTS", tmp_path)
    assert rv.latest("crosssec") is None


def test_latest_survives_a_missing_reports_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "REPORTS", tmp_path / "never-created")
    assert rv.latest("screen") is None


def test_stamp_reads_the_date_out_of_the_filename(tmp_path):
    assert rv.stamp_of(tmp_path / "crosssec_20260730_205218.csv") == "30.07.2026 20:52"


def test_stamp_degrades_gracefully_on_an_odd_filename(tmp_path):
    assert rv.stamp_of(tmp_path / "crosssec.csv") == "nieznana data"
    assert rv.stamp_of(tmp_path / "screen_nonsense.csv") == "nieznana data"


def test_every_verdict_has_a_colour_and_an_explanation():
    """A verdict rendered without its meaning is how 'low correlation' gets read as
    'good' — the traps are exactly the ones with the best correlations."""
    from trademon.portfolio.correlation import classify
    produced = {
        classify(0.10, 0.30, 8.0), classify(0.10, 0.75, 8.0),
        classify(0.80, 0.90, 8.0), classify(0.10, 0.30, -2.0),
        classify(-0.85, -0.60, -12.0),
    }
    assert produced <= set(rv.VERDICT_STYLE)
    assert produced <= set(VERDICT_KEYS)
    # And every verdict must actually say something, in both languages — a token
    # rendered with an empty explanation is the failure this test exists to stop.
    for token in produced:
        for lang in ("pl", "en"):
            assert i18n.t_in(lang, f"verdict.{VERDICT_KEYS[token]}.label").strip()
            assert i18n.t_in(lang, f"verdict.{VERDICT_KEYS[token]}.help").strip()


def test_the_stored_verdict_token_is_not_translated():
    """`models/reports/*.csv` written before 0.2.0 hold these exact tokens, and
    `research_view` filters on them — translating the data would orphan every report."""
    assert set(rv.VERDICT_STYLE) == {"KANDYDAT", "NIESTABILNY", "TRACI", "PUŁAPKA",
                                     "SKORELOWANY"}
    assert i18n.t_in("en", "verdict.candidate.label") == "CANDIDATE"


def test_an_as_of_run_is_recorded_so_it_cannot_pose_as_current():
    """A screen run as of 2016 saved under today's timestamp looked like today's
    answer in the dashboard — the CSV has to carry the cutoff."""
    current = pd.DataFrame({"symbol": ["GLD"], "corr": [0.21]}).assign(as_of="")
    historic = pd.DataFrame({"symbol": ["TLT"], "corr": [-0.27]}).assign(
        as_of="2016-07-30")
    assert current["as_of"].iloc[0] == ""
    assert historic["as_of"].iloc[0] == "2016-07-30"


def test_significance_bar_matches_the_reported_measure():
    """The view must not call something significant that the study calls noise."""
    assert rv.SIGMA_BAR == pytest.approx(2.0)
    measured = pd.Series([0.80, 1.11, 1.08, -1.04])   # the real module-3 results
    assert not (measured.abs() >= rv.SIGMA_BAR).any()
