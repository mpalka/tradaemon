"""Changing the bot's parameters from the browser.

Edits go to `config/config.overrides.yaml`, never to `config.yaml` — the baseline keeps
its research commentary, and "restore default" is a deleted key rather than a retyped
number. Every write is validated through pydantic first (config_store.apply_changes) and
journalled afterwards, so an invalid value cannot reach a running engine and a valid one
leaves a trace on the equity chart.

Two speeds of change, made explicit in the UI rather than left as a footgun:

* fields the engine re-reads each candle take effect on the next bar (⚡)
* fields read once at startup need the engine to come back (🔄) — the screen writes a
  flag, the engine persists its books and exits, and Docker restarts it

A third asymmetry sits underneath both, and only the risk fields have it: raising the
exposure ceiling takes effect on the next candle, while lowering it takes effect when
the extra positions happen to close. `_ceiling_dialog` is the one place that says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from trademon import config_store
from trademon.config import Config, config_path
from trademon.dashboard import auth, humanize, journals, layout
from trademon.data.storage import TIMEFRAME_MS
from trademon.i18n import t
from trademon.portfolio.config import PortfolioConfig
from trademon.portfolio.config import _find_config_path as _portfolio_config_path

HOT = "⚡"
RESTART = "🔄"

# Booleans shown as an on/off selectbox rather than a bare True/False. The widget
# carries the real booleans as its options and translates them only for display —
# until 0.2.0 the Polish word *was* the encoding (`raw == "włączony"`), which meant a
# translated label silently turned every save of these fields into False.
BOOL_CHOICES = ("trend.enabled", "strategy.rollover")


@dataclass
class Field:
    """One editable setting. The label and help text live in the message catalogues,
    keyed off `path`, so a new language is a catalogue edit and not a form edit."""
    path: str
    kind: str                      # float | int | choice | symbols | text
    help_key: str | None = None    # override, for text shared with the glossary
    min: float | None = None
    max: float | None = None
    step: float | None = None
    fmt: str | None = None
    choices: list[str] | None = None

    @property
    def label(self) -> str:
        return t(f"cfg.field.{self.path}.label")

    @property
    def help(self) -> str:
        return t(self.help_key or f"cfg.field.{self.path}.help")

    @property
    def hot(self) -> bool:
        return self.path in config_store.HOT_FIELDS

    @property
    def marker(self) -> str:
        return HOT if self.hot else RESTART


# Sections are keyed by a stable code, never by their heading: the heading is
# translated, and `_render_section` keys Streamlit widgets and the slot-queue special
# case off this dict.
CRYPTO_SECTIONS: dict[str, list[Field]] = {
    "strategy": [
        Field("strategy.prob_threshold", "float", min=0.0, max=1.0, step=0.01, fmt="%.2f"),
        Field("strategy.tp_atr_mult", "float", min=0.1, max=10.0, step=0.1, fmt="%.1f"),
        Field("strategy.sl_atr_mult", "float", min=0.1, max=10.0, step=0.1, fmt="%.1f"),
        Field("strategy.horizon_bars", "int", min=1, max=500, step=1),
        Field("strategy.rollover", "choice"),
        Field("strategy.atr_period", "int", min=2, max=200, step=1),
        Field("strategy.direction", "choice", choices=["long", "long_short"]),
        Field("strategy.warmup_bars", "int", min=50, max=2000, step=10),
    ],
    "risk": [
        Field("risk.position_pct", "float", min=0.01, max=1.0, step=0.01, fmt="%.2f"),
        Field("risk.max_open_positions", "int", min=1, max=20, step=1),
        Field("risk.daily_loss_limit_pct", "float", help_key="glossary.kill_switch",
              min=0.005, max=0.5, step=0.005, fmt="%.3f"),
        Field("risk.drawdown_alert_pct", "float", min=0.01, max=0.9, step=0.01, fmt="%.2f"),
    ],
    "costs": [
        Field("costs.taker_fee", "float", min=0.0, max=0.01, step=0.0001, fmt="%.4f"),
        Field("costs.maker_fee", "float", min=0.0, max=0.01, step=0.0001, fmt="%.4f"),
        Field("costs.slippage_bps", "float", min=0.0, max=50.0, step=0.5, fmt="%.1f"),
    ],
    "market": [
        Field("exchange.timeframe", "choice", choices=list(TIMEFRAME_MS)),
        Field("exchange.symbols", "symbols"),
        Field("paper.initial_capital", "float", min=10.0, max=1_000_000.0, step=100.0,
              fmt="%.2f"),
        Field("primary_variant", "choice"),
    ],
    "training": [
        Field("model.train_window_days", "int", min=30, max=4000, step=10),
        Field("model.validation_days", "int", min=7, max=365, step=1),
        Field("model.n_folds", "int", min=2, max=20, step=1),
    ],
}

PORTFOLIO_SECTIONS: dict[str, list[Field]] = {
    "portfolio": [
        Field("initial_capital", "float", min=100.0, max=10_000_000.0, step=100.0,
              fmt="%.2f"),
        Field("rebalance.cadence_days", "int", min=1, max=730, step=1),
        Field("rebalance.drift_threshold_pct", "float", help_key="glossary.drift",
              min=0.5, max=50.0, step=0.5, fmt="%.1f"),
        Field("trend.enabled", "choice"),
        Field("trend.ma_days", "int", min=20, max=500, step=10),
    ],
}


# ---------- what raising the ceiling would let in ----------

@dataclass(frozen=True)
class BookSlots:
    """One book's slot situation, as the engine last left it in `state.json`."""
    name: str
    taken: int                  # positions currently open
    cap: int                    # the limit the engine is really trading on
    queued: int                 # pairs that cleared the threshold and were turned away
    top_p: float | None         # the best probability among those
    position_pct: float

    @property
    def free(self) -> int:
        return max(0, self.cap - self.taken)


def book_slots(states: dict[str, dict]) -> list[BookSlots]:
    """Read the slot picture off the books' live state.

    `queued` counts only pairs turned away *by the cap*. `risk_blocked` also covers the
    kill-switch (`RiskManager.can_open` returns both), and those pairs would not enter
    however high the limit went — counting them would promise positions that a raise
    cannot deliver.

    Counting them at all is new: until 0.1.12 the engine checked the cap before asking
    the model, so a blocked pair had no probability attached and `risk_blocked` could
    equally mean a 0.92 opportunity or a 0.31 non-event. Now it is always the former.
    """
    slots = []
    for name, state in states.items():
        live = state.get("live_config") or {}
        cap = live.get("risk.max_open_positions")
        pct = live.get("risk.position_pct")
        if cap is None or pct is None:
            continue  # a book from before live_config; nothing honest to say about it
        blocked = [s for s in (state.get("signals") or {}).values()
                   if s.get("reason") == "risk_blocked"
                   and str(s.get("detail", "")).startswith("max_open_positions")]
        probs = [s["p_long"] for s in blocked if s.get("p_long") is not None]
        slots.append(BookSlots(
            name=name, taken=len(state.get("positions") or {}), cap=int(cap),
            queued=len(blocked), top_p=max(probs) if probs else None,
            position_pct=float(pct),
        ))
    return slots


def slot_lines(slots: list[BookSlots]) -> list[str]:
    """One sentence per book: how full it is, and what a free slot would cost.

    The queue count sits after a colon rather than inside a phrase, the same dodge
    `humanize._ago` uses: "2 pary czekają" vs "5 par czeka" is a declension rule this
    line does not need to know, in Polish or in any other language.
    """
    lines = []
    for s in slots:
        head = t("cfg.slots.head", book=s.name, taken=s.taken, cap=s.cap)
        if s.queued:
            top = (t("cfg.slots.top_p", p=humanize.dec(f"{s.top_p:.2f}"))
                   if s.top_p is not None else "")
            lines.append(t("cfg.slots.queued", head=head, queued=s.queued, top=top,
                           pct=f"{s.position_pct:.0%}"))
        elif s.free:
            lines.append(t("cfg.slots.free", head=head))
        else:
            lines.append(t("cfg.slots.full", head=head))
    return lines


def ceiling_change(current: dict, changes: dict) -> tuple[float, float] | None:
    """(ceiling before, ceiling after) when a save *raises* max exposure — else None.

    The ceiling is `position_pct × max_open_positions`: what share of the account can
    be in the market at once. Both halves matter, so 5 × 10% → 5 × 20% is as much of a
    raise as 5 × 10% → 10 × 10%, and the screen must not treat one as routine.

    Only raises are worth a question. Lowering the limit is not the dangerous
    direction — it is also not the safe one people assume, but that is a caption's job
    (nothing gets closed), not a dialog's.
    """
    pct_now = config_store.get_path(current, "risk.position_pct")
    cap_now = config_store.get_path(current, "risk.max_open_positions")
    if pct_now is None or cap_now is None:
        return None  # portfolio scope: no such thing here
    pct_new = changes.get("risk.position_pct", pct_now)
    cap_new = changes.get("risk.max_open_positions", cap_now)
    before, after = float(pct_now) * int(cap_now), float(pct_new) * int(cap_new)
    return (before, after) if after > before else None


# ---------- widgets ----------

def _widget(f: Field, current: Any, key: str) -> Any:
    label = f"{f.marker} {f.label}"
    if f.kind == "float":
        return st.number_input(label, value=float(current), min_value=f.min,
                               max_value=f.max, step=f.step, format=f.fmt,
                               help=f.help, key=key)
    if f.kind == "int":
        return st.number_input(label, value=int(current), min_value=int(f.min),
                               max_value=int(f.max), step=int(f.step),
                               help=f.help, key=key)
    if f.kind == "choice":
        if f.path in BOOL_CHOICES:
            # Real booleans as the option values, translated only on the way to the
            # screen, so `_parse` has nothing to decode back.
            return st.selectbox(
                label, [False, True], index=int(bool(current)),
                format_func=lambda on: t("cfg.bool.on" if on else "cfg.bool.off"),
                help=f.help, key=key)
        choices = f.choices or []
        idx = choices.index(current) if current in choices else 0
        return st.selectbox(label, choices, index=idx, help=f.help, key=key)
    if f.kind == "symbols":
        text = ", ".join(current or [])
        return st.text_area(label, value=text, help=f.help, key=key, height=80)
    return st.text_input(label, value=str(current or ""), help=f.help, key=key)


def _parse(f: Field, raw: Any) -> Any:
    if f.kind == "symbols":
        return [s.strip().upper() for s in str(raw).replace("\n", ",").split(",") if s.strip()]
    if f.kind == "int":
        return int(raw)
    if f.kind == "float":
        return float(raw)
    if f.path in BOOL_CHOICES:
        return bool(raw)
    return raw


# ---------- one editable section ----------

def effective_values(effective: dict, model_cls: type) -> dict:
    """Effective config *including* the defaults the YAML leaves unsaid.

    config.yaml spells out only the values worth commenting on — `strategy.direction`
    and `risk.drawdown_alert_pct`, for instance, live purely in the pydantic model.
    Reading widget values off the raw dict would hand `None` to a number input, so the
    form reads them off a validated model instead.
    """
    try:
        return model_cls.model_validate(effective).model_dump(mode="json")
    except ValidationError:
        return effective


def _render_section(
    section: str, fields: list[Field], cfg_path: Path, runtime_dir: Path,
    effective: dict, overrides: dict, model_cls: type, scope: str,
) -> None:
    title = t(f"cfg.section.{section}")
    overridden = [f.path for f in fields if config_store.get_path(overrides, f.path) is not None]
    header = t("cfg.section.changed", title=title, n=len(overridden)) if overridden else title

    defaults_filled = effective_values(effective, model_cls)
    with st.expander(header, expanded=bool(overridden)):
        # Said before the fields, not after the save: a form does not re-run while you
        # type, so the screen cannot react to the number being entered — but it can say
        # what the current one is already holding back.
        if scope == "crypto" and section == "risk":
            _render_slot_queue(runtime_dir)
        with st.form(f"form_{scope}_{section}"):
            values: dict[str, Any] = {}
            for f in fields:
                current = config_store.get_path(defaults_filled, f.path)
                if f.path == "primary_variant":
                    f.choices = [v.get("name") for v in effective.get("variants", [])] or ["—"]
                values[f.path] = _widget(f, current, key=f"{scope}.{f.path}")
            saved = st.form_submit_button(t("cfg.save"), type="primary")

        if saved:
            changes = {}
            for f in fields:
                try:
                    changes[f.path] = _parse(f, values[f.path])
                except (TypeError, ValueError):
                    st.error(t("cfg.error.bad_value", field=f.label))
                    return
            if raised := ceiling_change(defaults_filled, changes):
                _ceiling_dialog(cfg_path, runtime_dir, changes, model_cls, scope, raised)
            else:
                _apply(cfg_path, runtime_dir, changes, model_cls, scope)

        if overridden and st.button(t("cfg.reset_section", title=title),
                                    key=f"reset_{scope}_{section}"):
            _apply(cfg_path, runtime_dir, dict.fromkeys(overridden), model_cls, scope)


def _apply(cfg_path: Path, runtime_dir: Path, changes: dict,
           model_cls: type, scope: str) -> None:
    if not auth.can_write():
        st.error(t("cfg.error.no_permission"))
        return
    try:
        report = config_store.apply_changes(
            cfg_path, runtime_dir, changes, actor=auth.current_user(),
            model_cls=model_cls, scope=scope)
    except config_store.ConfigWriteError as exc:
        st.error(str(exc))
        return

    if not report.changed:
        st.info(t("cfg.nothing_changed"))
        return
    # st.rerun() throws away everything this run has drawn, so a message written here
    # is never painted — the save looked like a click into the void, which is what
    # made a user undo a change that had in fact been saved. Hand it to the next run
    # instead, the same way "restart_sent" already does.
    st.session_state["config_saved"] = "\n".join(
        f"- `{k}`: {old} → **{new}**" for k, (old, new) in report.applied.items())
    st.session_state["config_saved_hot"] = not report.needs_restart
    if report.needs_restart:
        st.session_state["pending_restart"] = report.needs_restart
    st.rerun()


# ---------- what the engine really trades on ----------

def _render_drift(cfg_path: Path, runtime_dir: Path) -> None:
    """Say out loud when the engine and this screen disagree.

    Without it, a book left behind on old parameters is indistinguishable from one
    that adopted them — the screen shows the file either way. That silence is what
    let `max_open_positions` sit at 5 in the engine while this form said 3.
    """
    try:
        drift = config_store.live_drift(cfg_path, runtime_dir)
    except ValidationError:
        # A value hand-edited into the file can be valid YAML and still not a valid
        # Config. The sections below survive that (effective_values falls back to the
        # raw dict), and this diagnostic must not be the thing that takes down the very
        # screen you would use to fix it.
        return

    if stuck := [d for d in drift if d.stuck]:
        st.warning(t("cfg.drift.stuck"))
        st.markdown("\n".join(
            t("cfg.drift.row", book=d.book, field=d.field, live=d.live, disk=d.on_disk)
            for d in stuck))
        st.caption(t("cfg.drift.restart_fixes"))
    elif drift:
        st.info(t("cfg.drift.pending"))


def _render_slot_queue(runtime_dir: Path) -> None:
    """What the limit is holding back right now, per book."""
    try:
        slots = book_slots(journals.book_states(runtime_dir))
    except (OSError, ValueError):
        return  # a missing or half-written runtime must not take down the edit form
    if not slots:
        return
    st.markdown("\n".join(f"- {line}" for line in slot_lines(slots)))
    st.caption(t("cfg.slots.as_of"))


# ---------- raising the exposure ceiling ----------

@st.dialog(t("cfg.ceiling.title"))
def _ceiling_dialog(cfg_path: Path, runtime_dir: Path, changes: dict,
                    model_cls: type, scope: str, raised: tuple[float, float]) -> None:
    """Ask before the ceiling goes up, because the answer arrives one candle later and
    cannot be taken back.

    Written after 9–10.08.2026: `max_open_positions` went 5 → 10 at 17:51 UTC and back
    to 5 at 22:43, but the candle in between had already opened four extra positions
    and pushed the book from 50% to 90% of the account. They stayed after the setting
    was reverted, three of them stopped out, and they cost 7.07 USDT — half of the
    whole drawdown. Neither half of that was visible from this screen: not how many
    pairs were queued for the new slots, and not that lowering the number back closes
    nothing.
    """
    before, after = raised
    st.markdown(t("cfg.ceiling.from_to", before=f"{before:.0%}", after=f"{after:.0%}"))
    try:
        slots = book_slots(journals.book_states(runtime_dir))
    except (OSError, ValueError):
        slots = []
    if slots:
        st.markdown("\n".join(f"- {line}" for line in slot_lines(slots)))
    st.warning(t("cfg.ceiling.warning"))
    c1, c2 = st.columns(2)
    if c1.button(t("cfg.ceiling.save_anyway"), type="primary", width="stretch"):
        _apply(cfg_path, runtime_dir, changes, model_cls, scope)
    if c2.button(t("cfg.cancel"), width="stretch"):
        st.rerun()


# ---------- restart handshake ----------

@st.dialog(t("cfg.restart.title"))
def _restart_dialog(runtime_dir: Path, fields: list[str]) -> None:
    st.write(t("cfg.restart.startup_only"))
    st.markdown("\n".join(f"- `{f}`" for f in fields))
    st.caption(t("cfg.restart.explain"))
    c1, c2 = st.columns(2)
    if c1.button(t("cfg.restart.do"), type="primary", width="stretch"):
        config_store.request_restart(runtime_dir, actor=auth.current_user())
        st.session_state.pop("pending_restart", None)
        st.session_state["restart_sent"] = True
        st.rerun()
    if c2.button(t("cfg.restart.later"), width="stretch"):
        st.session_state.pop("pending_restart", None)
        st.rerun()


# ---------- history ----------

def _render_history(runtime_dir: Path) -> None:
    rows = config_store.load_history(runtime_dir, limit=100)
    st.subheader(t("cfg.history.title"))
    if not rows:
        st.caption(t("cfg.history.empty"))
        return
    st.caption(t("cfg.history.marked_on_chart"))
    col = {name: t(f"cfg.history.col.{name}")
           for name in ("time", "field", "old", "new", "actor")}
    df = pd.DataFrame(rows)
    df[col["time"]] = pd.to_datetime(df["timestamp"]).dt.strftime("%d.%m.%Y %H:%M")
    view = df[[col["time"], "field", "old", "new", "actor"]].rename(
        columns={"field": col["field"], "old": col["old"],
                 "new": col["new"], "actor": col["actor"]})
    if layout.is_mobile():
        layout.cards(view, col["field"], [col["time"], col["old"], col["new"]])
    else:
        st.dataframe(view, width="stretch", hide_index=True)


# ---------- entry ----------

def render() -> None:
    st.caption(t("cfg.intro"))
    st.markdown(t("cfg.markers", hot=HOT, restart=RESTART))
    layout.layout_switch()

    if st.session_state.pop("restart_sent", False):
        st.success(t("cfg.restart.sent"))

    if saved := st.session_state.pop("config_saved", None):
        st.success(t("cfg.saved", changes=saved))
        if st.session_state.pop("config_saved_hot", False):
            st.info(t("cfg.saved.hot"))

    cfg_path = config_path()
    runtime_dir = _runtime_dir()

    if pending := st.session_state.get("pending_restart"):
        st.warning(t("cfg.restart.needed"))
        if st.button(t("cfg.restart.button"), type="primary"):
            _restart_dialog(runtime_dir, pending)

    # Options are codes, formatted for display only — comparing against a translated
    # label would make this branch depend on the viewer's language.
    scope = st.segmented_control(t("module.label"), ["crypto", "portfolio"], default="crypto",
                                 format_func=lambda s: t(f"module.{s}"),
                                 label_visibility="collapsed") or "crypto"

    if scope == "crypto":
        # Crypto only: the portfolio loop is daily and has no hot-reload to lag behind,
        # which the caption in the other branch already says.
        _render_drift(cfg_path, runtime_dir)
        effective = config_store.effective_config(cfg_path)
        overrides = config_store.load_overrides(cfg_path)
        for section, fields in CRYPTO_SECTIONS.items():
            _render_section(section, fields, cfg_path, runtime_dir, effective, overrides,
                            Config, "crypto")
        _render_variants(cfg_path, runtime_dir, effective, overrides)
    else:
        p_path = _portfolio_config_path(None)
        effective = config_store.effective_config(p_path)
        overrides = config_store.load_overrides(p_path)
        st.caption(t("cfg.portfolio.daily_loop"))
        for section, fields in PORTFOLIO_SECTIONS.items():
            _render_section(section, fields, p_path, runtime_dir, effective, overrides,
                            PortfolioConfig, "portfolio")

    st.divider()
    _render_history(runtime_dir)


def _render_variants(cfg_path: Path, runtime_dir: Path,
                     effective: dict, overrides: dict) -> None:
    """A/B books, edited as a grid. Adding or removing one changes which books exist,
    so this is restart-only by nature."""
    with st.expander(f"{RESTART} {t('cfg.variants.title')}"):
        st.caption(t("cfg.variants.help"))
        variants = effective.get("variants", []) or []
        cols = ["name", "prob_threshold", "tp_atr_mult", "sl_atr_mult",
                "horizon_bars", "direction", "rollover",
                "position_pct", "max_open_positions"]
        df = pd.DataFrame(variants)
        for c in cols:
            if c not in df:
                df[c] = None
        edited = st.data_editor(df[cols], num_rows="dynamic", width="stretch",
                                hide_index=True, key="variants_editor")
        if st.button(t("cfg.variants.save"), key="save_variants"):
            rows = [
                {k: v for k, v in rec.items() if v is not None and v != ""}
                for rec in edited.to_dict("records")
                if str(rec.get("name") or "").strip()
            ]
            _apply(cfg_path, runtime_dir, {"variants": rows}, Config, "crypto")
        if config_store.get_path(overrides, "variants") is not None and st.button(
                t("cfg.variants.reset"), key="reset_variants"):
            _apply(cfg_path, runtime_dir, {"variants": None}, Config, "crypto")


def _runtime_dir() -> Path:
    from trademon.config import load_config
    return load_config().paths.runtime_dir
