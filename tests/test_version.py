"""Keeps the version-bump rule from being skipped silently.

CLAUDE.md asks for a bump plus a changelog line on every change. A forgotten entry is
invisible in review, so it fails here instead.

Since 0.2.0 there are two changelogs, one per language. They are the same document
written twice, so they must name the same newest version — otherwise one of them
quietly stops being maintained and nobody notices until a reader in that language
reads a stale history.
"""

import re
from pathlib import Path

import pytest

from tradaemon import __version__

ROOT = Path(__file__).resolve().parents[1]
CHANGELOGS = {"en": ROOT / "CHANGELOG.md", "pl": ROOT / "CHANGELOG.pl.md"}


def _headings(path: Path) -> list[str]:
    return re.findall(r"^## (\S+)", path.read_text(encoding="utf-8"), re.MULTILINE)


@pytest.mark.parametrize("lang", sorted(CHANGELOGS))
def test_changelog_top_entry_matches_version(lang):
    headings = _headings(CHANGELOGS[lang])
    assert headings, f"{CHANGELOGS[lang].name} has no '## <version>' heading"
    assert headings[0] == __version__, (
        f"__version__ is {__version__} but the newest entry in {CHANGELOGS[lang].name} "
        f"is {headings[0]} — bump one or add the missing entry"
    )


def test_both_changelogs_cover_the_same_versions():
    en, pl = _headings(CHANGELOGS["en"]), _headings(CHANGELOGS["pl"])
    missing_en = [v for v in pl if v not in en]
    missing_pl = [v for v in en if v not in pl]
    assert not missing_en, f"CHANGELOG.md is missing: {missing_en}"
    assert not missing_pl, f"CHANGELOG.pl.md is missing: {missing_pl}"
