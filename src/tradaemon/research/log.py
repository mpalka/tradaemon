"""Persistent experiment log so backtests and sweeps are recorded once and
never re-derived. Append-only JSONL under runtime/, read by the dashboard.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def experiments_path(runtime_dir: Path) -> Path:
    return runtime_dir / "experiments.jsonl"


def log_experiment(runtime_dir: Path, record: dict) -> None:
    """Append one experiment result. `record` should carry at least a `kind`
    and the strategy params + headline metrics; a UTC timestamp is added here."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": datetime.now(UTC).isoformat(), **record}
    with open(experiments_path(runtime_dir), "a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def load_experiments(runtime_dir: Path) -> list[dict]:
    path = experiments_path(runtime_dir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
