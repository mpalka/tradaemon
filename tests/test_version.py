"""Keeps the version-bump rule from being skipped silently.

CLAUDE.md asks for a bump plus a CHANGELOG line on every change. A forgotten entry
is invisible in review, so it fails here instead.
"""

import re
from pathlib import Path

from trademon import __version__

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def test_changelog_top_entry_matches_version():
    headings = re.findall(r"^## (\S+)", CHANGELOG.read_text(encoding="utf-8"), re.MULTILINE)
    assert headings, "CHANGELOG.md has no '## <wersja>' heading"
    assert headings[0] == __version__, (
        f"__version__ is {__version__} but the newest CHANGELOG entry is {headings[0]} — "
        "bump one or add the missing entry"
    )
