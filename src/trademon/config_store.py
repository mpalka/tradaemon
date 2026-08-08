"""Writing configuration from the dashboard, safely.

Edits never touch config.yaml. That file is the documented baseline — it carries the
research commentary explaining *why* each value is what it is (why 4h, why a 2000-day
train window, why the ryzyko_100 book exists), and a `yaml.safe_dump` round-trip would
delete every one of those comments on the first save. Instead the dashboard writes a
sibling `<stem>.overrides.yaml` that `load_config` merges on top, so "restore default"
is just dropping a key and `git diff` shows only what actually changed.

Two guarantees this module exists to provide:

1. **Nothing invalid reaches disk.** A change is merged and validated through the
   pydantic model *before* the file is written, so a rejected value never touches the
   engine — it only produces an error message in the UI.
2. **Every change is on the record.** Each accepted edit is appended to
   runtime/config_history.jsonl. Changing parameters mid-flight makes a book's equity
   curve a blend of two strategies; the journal is what lets the dashboard draw the
   seam instead of quietly averaging over it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from trademon.config import Config, deep_merge, load_config, load_raw_config, overrides_path

HISTORY_FILENAME = "config_history.jsonl"
RESTART_FLAG_FILENAME = "restart_requested"

# Fields Book re-reads from self.cfg on every candle (_maybe_enter / _manage_position),
# so a new value takes effect on the next bar without restarting anything.
HOT_FIELDS: frozenset[str] = frozenset({
    "strategy.prob_threshold",
    "strategy.tp_atr_mult",
    "strategy.sl_atr_mult",
    "strategy.horizon_bars",
    "strategy.atr_period",
    "strategy.direction",
    "strategy.timeout_rollover",
    "risk.position_pct",
    "risk.max_open_positions",
    "risk.daily_loss_limit_pct",
    "risk.drawdown_alert_pct",
    "costs.taker_fee",
    "costs.maker_fee",
    "costs.slippage_bps",
})

# Fields read once, in Book.__init__ or TradingEngine.run: candle buffer length, bar
# delta, the set of streamed symbols, the list of books. Changing them needs a restart
# (the engine exits cleanly, Docker's restart policy brings it back, and Book.restore
# reloads cash and open positions from state.json).
RESTART_FIELDS: frozenset[str] = frozenset({
    "exchange.id",
    "exchange.symbols",
    "exchange.timeframe",
    "strategy.warmup_bars",
    "paper.initial_capital",
    "variants",
    "primary_variant",
    "display_timezone",
    "model.train_window_days",
    "model.validation_days",
    "model.n_folds",
    "execution.order_style",
    "execution.maker_timeout_bars",
})

# Never settable from a browser. Going live is a deliberate edit to the file on the
# host plus API keys in .env — not a toggle someone can flip from the couch.
FORBIDDEN_FIELDS: frozenset[str] = frozenset({"mode", "paths"})


class ConfigWriteError(Exception):
    """A change was rejected; nothing was written."""


@dataclass
class ChangeReport:
    """What actually changed, and whether the engine needs a restart to see it."""
    applied: dict[str, tuple[Any, Any]] = field(default_factory=dict)  # field -> (old, new)
    needs_restart: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)


# ---------- dotted-path helpers ----------

def get_path(data: dict, dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_path(data: dict, dotted: str, value: Any) -> dict:
    """Return a copy of `data` with `dotted` set to `value` (creating parents)."""
    out = dict(data)
    node = out
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        node[part] = dict(child) if isinstance(child, dict) else {}
        node = node[part]
    node[parts[-1]] = value
    return out


def drop_path(data: dict, dotted: str) -> dict:
    """Return a copy of `data` without `dotted`, pruning parents left empty."""
    parts = dotted.split(".")
    if get_path(data, dotted) is None and parts[0] not in data:
        return dict(data)
    out = dict(data)
    node = out
    stack: list[tuple[dict, str]] = []
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            return out
        node[part] = dict(child)
        stack.append((node, part))
        node = node[part]
    node.pop(parts[-1], None)
    for parent, key in reversed(stack):
        if not parent[key]:
            parent.pop(key)
    return out


# ---------- overrides file ----------

def load_overrides(cfg_path: Path) -> dict:
    path = overrides_path(cfg_path)
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_overrides(cfg_path: Path, data: dict) -> Path:
    """Atomic write, mirroring RuntimeStore.save_state: the engine may read this file
    at any moment, and it must never observe a half-written config."""
    path = overrides_path(cfg_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        path.unlink(missing_ok=True)
        return path
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(
        "# Written by the dashboard's config screen. config.yaml stays the documented\n"
        "# baseline; only the values you changed live here. Delete a key to restore\n"
        "# its default, or delete this file to restore all of them.\n"
        + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    os.replace(tmp, path)
    return path


def effective_config(cfg_path: Path) -> dict:
    """The merged dict the engine actually sees."""
    defaults, overrides = load_raw_config(cfg_path)
    return deep_merge(defaults, overrides)


# ---------- applying changes ----------

def apply_changes(
    cfg_path: Path,
    runtime_dir: Path,
    changes: dict[str, Any],
    actor: str = "local",
    model_cls: type[BaseModel] = Config,
    scope: str = "crypto",
) -> ChangeReport:
    """Validate, then persist, then journal. Raises ConfigWriteError without writing
    anything if the resulting config would be invalid.

    `changes` maps dotted paths to new values. A value of None is not "null" — it means
    *restore the default*, i.e. drop the key from the overrides file.
    """
    forbidden = sorted(f for f in changes if f.split(".")[0] in FORBIDDEN_FIELDS)
    if forbidden:
        raise ConfigWriteError(
            f"Tych pól nie można zmieniać z panelu: {', '.join(forbidden)}"
        )

    defaults, overrides = load_raw_config(cfg_path)
    before = deep_merge(defaults, overrides)
    baseline = _with_model_defaults(defaults, model_cls)

    new_overrides = dict(overrides)
    for dotted, value in changes.items():
        # An override is only worth storing when it differs from what you would get
        # without it. Writing back a value equal to the baseline would pin it: a later
        # edit to config.yaml would be silently shadowed by a stale copy here. It also
        # keeps forms honest — a section's Save submits every field it renders, and
        # only the ones actually touched should end up in the file or the journal.
        if value is None or get_path(baseline, dotted) == value:
            new_overrides = drop_path(new_overrides, dotted)
        else:
            new_overrides = set_path(new_overrides, dotted, value)
    after = deep_merge(defaults, new_overrides)

    try:
        model_cls.model_validate(after)
    except ValidationError as exc:
        raise ConfigWriteError(_humanize_validation_error(exc)) from exc

    report = ChangeReport()
    for dotted in changes:
        old, new = get_path(before, dotted), get_path(after, dotted)
        if old != new:
            report.applied[dotted] = (old, new)
            if dotted in RESTART_FIELDS or dotted.split(".")[0] in RESTART_FIELDS:
                report.needs_restart.append(dotted)

    if not report.changed:
        return report

    save_overrides(cfg_path, new_overrides)
    append_history(runtime_dir, report, actor, scope)
    return report


def _with_model_defaults(defaults: dict, model_cls: type[BaseModel]) -> dict:
    """config.yaml + the defaults it leaves unsaid.

    The baseline file only spells out values worth commenting on; fields like
    `strategy.direction` exist solely as pydantic defaults. Comparing against the raw
    dict would treat "unset" as different from the default it resolves to, and record
    a change where nothing changed.
    """
    try:
        return model_cls.model_validate(defaults).model_dump(mode="json")
    except ValidationError:
        return defaults


def _humanize_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "config"
        lines.append(f"**{where}** — {err['msg']}")
    return "Wartość odrzucona, nic nie zapisano:\n\n" + "\n\n".join(lines)


# ---------- change journal ----------

def history_path(runtime_dir: Path) -> Path:
    return runtime_dir / HISTORY_FILENAME


def append_history(runtime_dir: Path, report: ChangeReport, actor: str, scope: str) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    with open(history_path(runtime_dir), "a") as f:
        f.writelines(
            json.dumps({"timestamp": now, "scope": scope, "field": dotted,
                        "old": old, "new": new, "actor": actor}, default=str) + "\n"
            for dotted, (old, new) in report.applied.items()
        )


def load_history(runtime_dir: Path, limit: int | None = None) -> list[dict]:
    """Newest first. Returns [] when nothing has ever been changed."""
    path = history_path(runtime_dir)
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    rows.reverse()
    return rows[:limit] if limit else rows


# ---------- restart handshake ----------

def request_restart(runtime_dir: Path, actor: str = "local") -> None:
    """Ask the engine to exit. It persists its books and quits with status 0; the
    container's `restart: unless-stopped` brings it straight back with the new config.
    The dashboard deliberately has no access to the Docker socket — it only touches
    this file, and the engine decides when it is safe to go down."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / RESTART_FLAG_FILENAME).write_text(
        json.dumps({"requested_at": datetime.now(UTC).isoformat(), "actor": actor})
    )


def restart_requested_at(runtime_dir: Path) -> datetime | None:
    path = runtime_dir / RESTART_FLAG_FILENAME
    if not path.exists():
        return None
    try:
        return datetime.fromisoformat(json.loads(path.read_text())["requested_at"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


# ---------- what the engine is actually enforcing ----------

@dataclass
class LiveDrift:
    """One hot field where a running book disagrees with the file on disk."""
    book: str
    field: str          # dotted path, as in HOT_FIELDS
    live: Any           # what the engine is trading on
    on_disk: Any        # what the config screen shows
    stuck: bool         # a candle has closed since the edit and it still disagrees


def live_drift(cfg_path: Path, runtime_dir: Path) -> list[LiveDrift]:
    """Compare each book's state.json against the config it ought to be running.

    Two situations have to stay separate, because conflating them makes the warning
    useless: a book that has not seen a candle since the edit is *waiting* — correct,
    and on 4h candles that is hours — while a book that has seen one and still
    disagrees is *stuck*. `last_candle_ts` holds each pair's last closed candle by its
    open time, so requiring it to be later than the file's mtime is conservative: it
    can only make the warning late, never wrong, which is the right bias here.

    An mtime is good enough for *this* comparison, unlike in the engine's own watch:
    getting it wrong shifts when a message appears, it cannot change what is traded.

    Each book is compared against its own variant, because variants override these
    fields deliberately — ryzyko_100 runs max_open_positions: 5 against a base of 3
    and is not drifting.
    """
    cfg = load_config(cfg_path)
    books = ({v.name: runtime_dir / v.name for v in cfg.variants} if cfg.variants
             else {"default": runtime_dir})
    stamps = [p.stat().st_mtime for p in (cfg_path, overrides_path(cfg_path)) if p.exists()]
    edited_at = datetime.fromtimestamp(max(stamps), UTC) if stamps else None

    out: list[LiveDrift] = []
    for name, book_dir in books.items():
        try:
            state = json.loads((book_dir / "state.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        live = state.get("live_config")
        if not live:
            # An engine older than this field reports nothing. Without this guard every
            # user would see a phantom warning between deploying and restarting.
            continue
        variant = next((v for v in (cfg.variants or []) if v.name == name), None)
        want = (cfg.for_variant(variant) if variant else cfg).model_dump(mode="json")
        stuck = _saw_a_candle_after(state, edited_at)
        for dotted in sorted(HOT_FIELDS):
            if dotted not in live:
                continue          # forward compatibility: a newer engine, an older panel
            on_disk = get_path(want, dotted)
            if live[dotted] != on_disk:
                out.append(LiveDrift(name, dotted, live[dotted], on_disk, stuck))
    return out


def _saw_a_candle_after(state: dict, edited_at: datetime | None) -> bool:
    """Did this book close a candle after the config was last written?

    A dead engine produces no new candles, so it stays in the calm "waiting" state
    rather than being reported as stuck. That is right: "the engine is down" is the
    bot-status panel's job, not this function's.
    """
    if edited_at is None:
        return False
    stamps = []
    for raw in (state.get("last_candle_ts") or {}).values():
        try:
            ts = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        stamps.append(ts if ts.tzinfo else ts.replace(tzinfo=UTC))
    return bool(stamps) and max(stamps) > edited_at
