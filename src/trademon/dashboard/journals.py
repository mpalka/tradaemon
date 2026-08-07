"""Reading the engine's append-only journals, once per change instead of once
per click.

Streamlit re-runs the whole script on every widget interaction, so a plain
`read_text().splitlines()` re-parses every equity row each time someone drags a
date slider. The files are small today (the portfolio book's equity journal is
~5.5k rows) but they only grow, and the cost is paid on every interaction.

The cache is keyed on a fingerprint of the file rather than a TTL: the engine
appends a row and the panel shows it on the next re-run, with no staleness
window to wait out. This mirrors `price_view.closes`, which does the same for
stored candles.

Read-only on purpose. `RuntimeStore` (engine/state.py) remains the only writer;
this is its counterpart on the dashboard side, and the one place to change if
the journals ever move off JSONL.

Which is worth doing only under one of two conditions, both far from here.
Dropping to a 1m timeframe would push equity to ~525k rows per book per year,
where re-parsing the file at all stops being defensible; or a need for
cross-cutting queries ("every BTC trade across all books", retention, deleting
old rows) would want a query engine. Until then JSONL keeps what a database
takes away: `tail -f` on a running bot, `jq`, a readable `git diff`, and a
corrupt write that costs one line instead of the file. Note also that
docker-compose runs four containers over the same bind-mounted `runtime/`,
so a shared SQLite file would trade this problem for a locking one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


def _fingerprint(path: Path) -> tuple[int, int]:
    """(mtime_ns, size) — what makes a cached parse stale.

    The journals are append-only, so size alone would catch almost every write;
    mtime covers the rest (a file replaced wholesale, e.g. restored from a
    backup, may land on the same length). Whole-second mtime granularity is not
    a risk here because size moves too.
    """
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


# `max_entries` is not decoration: every appended candle produces a new
# fingerprint, so an unbounded cache would grow for as long as the panel stays
# up. 64 is comfortably more than the handful of journals across all books.
@st.cache_data(show_spinner=False, max_entries=64)
def _parse_jsonl(path: str, fingerprint: tuple[int, int]) -> pd.DataFrame:
    """`fingerprint` is unused in the body on purpose — it is there to key the cache."""
    lines = Path(path).read_text().splitlines()
    return pd.DataFrame([json.loads(x) for x in lines if x.strip()])


def load_jsonl(path: Path) -> pd.DataFrame:
    """One journal as a DataFrame; empty when the file is missing or empty.

    Callers filter and reshape what they get back. That is safe: `st.cache_data`
    hands out a copy per call, so mutating the result cannot poison the cache.
    """
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return _parse_jsonl(str(path), _fingerprint(path))


def records(df: pd.DataFrame) -> list[dict]:
    """Rows as dicts, with absent fields absent — not present as NaN.

    A journal holds several kinds of row in one file: `trade_open` carries a
    symbol, `config` and `risk` alerts carry none. The DataFrame has to square
    that into one rectangle, so it invents a `symbol` cell for the config row and
    fills it with NaN. Plain `to_dict("records")` then hands the caller a dict
    where `rec.get("symbol")` returns `nan` instead of `None` — and `nan` is
    truthy, so the obvious `if sym:` guard passes and the symbol reaches code
    that expects a string (`'float' object has no attribute 'replace'`).

    Dropping the empty cells restores what the writer wrote and what `.get()`
    callers assume. This is per-row on purpose: `dropna()` on the frame would
    delete whole rows or columns, which is a different thing entirely.
    """
    return [{k: v for k, v in rec.items() if not _missing(v)}
            for rec in df.to_dict("records")]


def _missing(value) -> bool:
    """NaN/NaT/None — the cells pandas invented. Scalars only, hence `is True`.

    `pd.isna` returns an array for list- and dict-valued cells (a JSONL journal
    may legitimately hold either), and `if` on an array raises. Comparing the
    result to `True` keeps those cells, which is right: they are real values.
    """
    return value is None or pd.isna(value) is True
