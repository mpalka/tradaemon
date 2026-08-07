"""Runtime persistence: state.json (atomic) + append-only JSONL journals.

The dashboard reads these files; the engine is the only writer, which avoids
database lock contention between the two processes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _json_default(obj: Any) -> str:
    return str(obj)


class RuntimeStore:
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = runtime_dir
        self.state_path = runtime_dir / "state.json"
        self.trades_path = runtime_dir / "trades.jsonl"
        self.equity_path = runtime_dir / "equity.jsonl"
        self.alerts_path = runtime_dir / "alerts.jsonl"
        runtime_dir.mkdir(parents=True, exist_ok=True)

    def save_state(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, default=_json_default))
        os.replace(tmp, self.state_path)

    def load_state(self) -> dict | None:
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text())

    def _append(self, path: Path, record: dict) -> None:
        with open(path, "a") as f:
            f.write(json.dumps(record, default=_json_default) + "\n")

    def append_trade(self, record: dict) -> None:
        self._append(self.trades_path, record)

    def append_equity(self, record: dict) -> None:
        self._append(self.equity_path, record)

    def append_alert(self, record: dict) -> None:
        self._append(self.alerts_path, record)

    def last_alert(self, kind: str) -> dict | None:
        """The most recent alert of one kind, or None.

        The only read on a journal the engine otherwise just appends to, and it
        earns its place: an alert about a *state* (the exchange is unreachable)
        has to be closed by whoever finds that state over, and after a container
        restart that is a different process than the one which opened it. Without
        this the alarm stays the newest line in the log, telling the reader the
        bot is down long after it came back.

        Reads the whole file because alerts are the small journal — a few hundred
        rows over weeks, against equity's thousands per month. A malformed line is
        skipped rather than raised on: a half-written record must not stop a book
        from starting.
        """
        if not self.alerts_path.exists():
            return None
        found = None
        for line in self.alerts_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("kind") == kind:
                found = record
        return found
