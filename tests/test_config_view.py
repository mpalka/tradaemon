"""Tests for the risk-limit warning on the config screen (dashboard/config_view.py).

Streamlit rendering is not exercised here; what is worth pinning is the arithmetic the
warning stands on — which pairs count as queued for a freed slot, and which saves are
a raise of the exposure ceiling.

The case these exist for is 9–10.08.2026: `max_open_positions` 5 -> 10 for five hours,
four positions opened on the very next candle, -7.07 USDT that stayed after the setting
was put back. See howitworks.md 4.8.
"""

import json

import pytest

from trademon import i18n
from trademon.dashboard import config_view as cv
from trademon.dashboard import journals


def state(*, positions: int, cap: int, pct: float = 0.10, signals: dict | None = None):
    return {
        "positions": {f"P{i}/USDT": {"qty": 1.0} for i in range(positions)},
        "signals": signals or {},
        "live_config": {"risk.max_open_positions": cap, "risk.position_pct": pct},
    }


BLOCKED = {"reason": "risk_blocked", "detail": "max_open_positions (5) reached",
           "side": "long", "p_long": 0.54}


# ---------- what is queued behind the cap ----------

def test_a_full_book_reports_the_pairs_the_cap_turned_away():
    slots = cv.book_slots({"prog_050": state(
        positions=5, cap=5,
        signals={"TRX/USDT": BLOCKED,
                 "XLM/USDT": {**BLOCKED, "p_long": 0.51},
                 "BCH/USDT": {"reason": "below_threshold", "p_long": 0.39}})})
    assert [(s.name, s.taken, s.cap, s.free, s.queued) for s in slots] == [
        ("prog_050", 5, 5, 0, 2)]
    assert slots[0].top_p == 0.54


def test_the_kill_switch_does_not_count_as_a_queue():
    """`risk_blocked` covers both refusals. Only the cap's can be undone by raising it —
    counting the kill-switch would promise positions that a raise cannot deliver."""
    killed = {"reason": "risk_blocked", "p_long": 0.61,
              "detail": "kill-switch: daily loss limit (3.0%) hit, no new entries today"}
    slots = cv.book_slots({"prog_050": state(positions=2, cap=5,
                                             signals={"ETH/USDT": killed})})
    assert slots[0].queued == 0
    assert slots[0].top_p is None


def test_a_book_from_before_live_config_is_skipped():
    """Nothing honest can be said about a book that never wrote what it trades on."""
    assert cv.book_slots({"stary": {"positions": {}, "signals": {}}}) == []


def test_free_slots_never_go_negative_when_the_cap_was_lowered_under_the_book():
    """Exactly the 9.08 state: five positions opened at cap 10, cap back at 5."""
    slots = cv.book_slots({"prog_050": state(positions=9, cap=5)})
    assert slots[0].free == 0


# ---------- how it reads ----------

def test_the_line_says_what_one_more_slot_would_cost():
    line = cv.slot_lines(cv.book_slots({"prog_050": state(
        positions=5, cap=5, pct=0.10, signals={"TRX/USDT": BLOCKED})}))[0]
    assert "5 z 5 miejsc zajętych" in line
    assert "w kolejce z sygnałem: **1**" in line
    assert "0,54" in line          # the queue's best probability, comma as decimal mark
    assert "10% konta" in line     # what the freed slot would put in the market


def test_an_empty_queue_says_a_raise_changes_nothing_today():
    line = cv.slot_lines(cv.book_slots({"prog_050": state(positions=2, cap=5)}))[0]
    assert "nikt nie czeka" in line


# ---------- which saves are a raise ----------

CURRENT = {"risk": {"position_pct": 0.10, "max_open_positions": 5}}


@pytest.mark.parametrize("changes, expected", [
    ({"risk.max_open_positions": 10}, (0.5, 1.0)),          # 9.08, exactly
    ({"risk.position_pct": 0.20}, (0.5, 1.0)),              # the other half of the same
    ({"risk.position_pct": 0.20, "risk.max_open_positions": 3}, (0.5, 0.6)),
])
def test_raising_the_ceiling_is_caught_however_it_is_raised(changes, expected):
    assert cv.ceiling_change(CURRENT, changes) == pytest.approx(expected)


@pytest.mark.parametrize("changes", [
    {"risk.max_open_positions": 3},                          # plainly lower
    {"risk.max_open_positions": 5},                          # saved untouched
    {"risk.position_pct": 0.20, "risk.max_open_positions": 2},   # lower by the product
    {"risk.daily_loss_limit_pct": 0.05},                     # not about exposure at all
])
def test_everything_that_is_not_a_raise_saves_without_a_question(changes):
    assert cv.ceiling_change(CURRENT, changes) is None


def test_the_portfolio_scope_has_no_ceiling_to_raise():
    assert cv.ceiling_change({"rebalance": {"cadence_days": 30}},
                             {"rebalance.cadence_days": 7}) is None


# ---------- reading the books off disk ----------

def test_book_states_finds_variants_and_skips_the_portfolio(tmp_path):
    (tmp_path / "prog_050").mkdir()
    (tmp_path / "prog_050" / "state.json").write_text(json.dumps({"cash": 1.0}))
    (tmp_path / "portfolio" / "spokojny").mkdir(parents=True)
    (tmp_path / "portfolio" / "spokojny" / "state.json").write_text("{}")
    (tmp_path / "agresywny").mkdir()  # a leftover directory with no state yet
    assert journals.book_states(tmp_path) == {"prog_050": {"cash": 1.0}}


def test_book_states_reads_a_single_book_runtime(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"cash": 2.0}))
    assert journals.book_states(tmp_path) == {"default": {"cash": 2.0}}


# ---------- the two things a translated screen could silently break ----------

@pytest.mark.parametrize("path", cv.BOOL_CHOICES)
@pytest.mark.parametrize("raw", [True, False])
def test_a_boolean_field_round_trips_as_a_boolean(path, raw):
    """Until 0.2.0 the Polish word *was* the encoding: `_parse` returned
    `raw == "włączony"`, so an English label would have turned every save of these
    fields into False. The widget now carries real booleans and translates only for
    display, and this is the test that keeps it that way."""
    field = cv.Field(path, "choice")
    assert cv._parse(field, raw) is raw


def test_a_boolean_field_is_labelled_in_both_languages():
    for lang in ("pl", "en"):
        assert i18n.t_in(lang, "cfg.bool.on").strip()
        assert i18n.t_in(lang, "cfg.bool.off").strip()
    assert i18n.t_in("pl", "cfg.bool.on") != i18n.t_in("en", "cfg.bool.on")
