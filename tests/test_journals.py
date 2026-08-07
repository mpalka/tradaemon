"""Tests for the dashboard's journal reader (dashboard/journals.py).

The parse itself is a one-liner; what is worth pinning is the behaviour the two
call sites used to duplicate (missing and empty files, blank lines) and the one
thing the cache could plausibly get wrong: a row appended after a read must show
up on the next one.
"""

import json

import pandas as pd

from trademon.dashboard import journals


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def append_row(path, row):
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


# ---------- degenerate files ----------

def test_a_missing_journal_reads_as_empty(tmp_path):
    """A book that has never traded has no trades.jsonl; that is not an error."""
    assert journals.load_jsonl(tmp_path / "trades.jsonl").empty


def test_an_empty_journal_reads_as_empty(tmp_path):
    path = tmp_path / "equity.jsonl"
    path.write_text("")
    assert journals.load_jsonl(path).empty


def test_blank_lines_are_skipped(tmp_path):
    path = tmp_path / "equity.jsonl"
    path.write_text(json.dumps({"equity": 100.0}) + "\n\n   \n")
    assert len(journals.load_jsonl(path)) == 1


# ---------- parsing ----------

def test_rows_become_columns(tmp_path):
    path = tmp_path / "equity.jsonl"
    write_rows(path, [
        {"timestamp": "2026-08-01T00:00:00+00:00", "symbol": "BTC/USDT", "equity": 1000.0},
        {"timestamp": "2026-08-01T04:00:00+00:00", "symbol": "BTC/USDT", "equity": 1010.0},
    ])
    df = journals.load_jsonl(path)
    assert list(df.columns) == ["timestamp", "symbol", "equity"]
    assert df["equity"].tolist() == [1000.0, 1010.0]


# ---------- cache invalidation ----------

def test_an_appended_row_shows_up_on_the_next_read(tmp_path):
    """The whole point of the fingerprint: the engine appends a candle and the
    panel sees it on its next re-run, with no TTL to wait out. Both writes land
    in the same second here, so it is the size half of the fingerprint doing the
    work — which is exactly the case a mtime-only key would miss."""
    path = tmp_path / "equity.jsonl"
    write_rows(path, [{"equity": 1000.0}])
    assert len(journals.load_jsonl(path)) == 1

    append_row(path, {"equity": 1010.0})
    df = journals.load_jsonl(path)
    assert len(df) == 2
    assert df["equity"].tolist() == [1000.0, 1010.0]


def test_two_journals_do_not_share_a_cache_entry(tmp_path):
    """Same shape, same length, different file — the path is part of the key."""
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_rows(first, [{"equity": 1.0}])
    write_rows(second, [{"equity": 2.0}])
    assert journals.load_jsonl(first)["equity"].tolist() == [1.0]
    assert journals.load_jsonl(second)["equity"].tolist() == [2.0]


def test_the_caller_may_mutate_what_it_gets_back(tmp_path):
    """Callers filter and reshape these frames in place; that must not corrupt
    the cached copy for the next read."""
    path = tmp_path / "equity.jsonl"
    write_rows(path, [{"equity": 1000.0}, {"equity": 1010.0}])

    df = journals.load_jsonl(path)
    df["equity"] = 0.0
    df.drop(df.index[0], inplace=True)

    fresh = journals.load_jsonl(path)
    assert fresh["equity"].tolist() == [1000.0, 1010.0]


def test_a_file_replaced_at_the_same_size_is_still_re_read(tmp_path):
    """Not an append: the file is rewritten wholesale to the same length (a
    restore from backup). Size alone would miss it; mtime catches it."""
    path = tmp_path / "equity.jsonl"
    write_rows(path, [{"equity": 1000.0}])
    assert journals.load_jsonl(path)["equity"].tolist() == [1000.0]

    write_rows(path, [{"equity": 2000.0}])
    assert path.stat().st_size == len(json.dumps({"equity": 1000.0})) + 1
    assert journals.load_jsonl(path)["equity"].tolist() == [2000.0]


def test_a_journal_emptied_after_a_read_goes_back_to_empty(tmp_path):
    path = tmp_path / "equity.jsonl"
    write_rows(path, [{"equity": 1000.0}])
    assert len(journals.load_jsonl(path)) == 1

    path.write_text("")
    assert journals.load_jsonl(path).empty


def test_the_result_is_a_dataframe_even_when_empty(tmp_path):
    """Callers do `.empty`, `"close" not in df` and `df.copy()` on the result
    without checking the type first."""
    assert isinstance(journals.load_jsonl(tmp_path / "nope.jsonl"), pd.DataFrame)
