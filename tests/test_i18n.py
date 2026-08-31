"""The message catalogues must stay in step with each other and with the code.

A half-finished translation is the failure mode worth catching early: it does not
crash, it just quietly shows Polish inside an English screen (or the raw key, which
is worse). These tests make that a red suite instead of a bug report.
"""

from __future__ import annotations

import ast
import string
from pathlib import Path

import pytest

from trademon import i18n
from trademon.dashboard import humanize
from trademon.locales import CATALOGUES

SRC = Path(__file__).resolve().parents[1] / "src"

# Keys built at runtime from a code (`t(f"reason.{code}")`), so the AST scan below
# cannot see them. Each family is checked against its own list of codes instead.
DYNAMIC_FAMILIES = {
    "reason.": humanize.REASON_CODES,
    "exit.": humanize.EXIT_CODES,
    "glossary.": humanize.GLOSSARY_TERMS,
}


def _placeholders(entry: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(entry) if name}


def _literal_keys() -> set[str]:
    """Every `t("...")` / `t_in(lang, "...")` / `lookup("...")` key written literally."""
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(
                node.func, "id", None)
            if name not in ("t", "t_in", "lookup", "has"):
                continue
            args = node.args[1:] if name == "t_in" else node.args
            if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                found.add(args[0].value)
    return found


def test_every_language_defines_the_same_keys():
    reference = set(CATALOGUES[i18n.SOURCE_LANG])
    for lang, catalogue in CATALOGUES.items():
        missing = reference - set(catalogue)
        extra = set(catalogue) - reference
        assert not missing, f"{lang} is missing {sorted(missing)}"
        assert not extra, f"{lang} has keys no other language has: {sorted(extra)}"


@pytest.mark.parametrize("lang", sorted(CATALOGUES))
def test_placeholders_survive_translation(lang):
    """A sentence that loses its `{amount}` in translation loses its numbers."""
    source = CATALOGUES[i18n.SOURCE_LANG]
    for key, entry in CATALOGUES[lang].items():
        assert _placeholders(entry) == _placeholders(source[key]), key


@pytest.mark.parametrize("lang", sorted(CATALOGUES))
def test_no_entry_is_empty(lang):
    for key, entry in CATALOGUES[lang].items():
        assert entry.strip(), key


def test_every_key_used_in_the_code_exists():
    known = set(CATALOGUES[i18n.SOURCE_LANG])
    missing = sorted(_literal_keys() - known)
    assert not missing, f"used in src/ but absent from the catalogues: {missing}"


def test_runtime_built_keys_exist():
    for prefix, codes in DYNAMIC_FAMILIES.items():
        for code in codes:
            assert i18n.has(f"{prefix}{code}", lang="pl"), f"{prefix}{code}"
            assert i18n.has(f"{prefix}{code}", lang="en"), f"{prefix}{code}"


def test_every_settings_field_has_a_label_and_a_help_text():
    """`Field` derives its keys from `path`, so the AST scan above cannot see them."""
    from trademon.dashboard.config_view import CRYPTO_SECTIONS, PORTFOLIO_SECTIONS

    fields = [f for section in (*CRYPTO_SECTIONS.values(), *PORTFOLIO_SECTIONS.values())
              for f in section]
    assert fields
    for lang in CATALOGUES:
        for f in fields:
            assert i18n.has(f"cfg.field.{f.path}.label", lang=lang), f"{lang}: {f.path} label"
            key = f.help_key or f"cfg.field.{f.path}.help"
            assert i18n.has(key, lang=lang), f"{lang}: {f.path} help ({key})"


def test_every_settings_section_has_a_heading():
    from trademon.dashboard.config_view import CRYPTO_SECTIONS, PORTFOLIO_SECTIONS

    for section in (*CRYPTO_SECTIONS, *PORTFOLIO_SECTIONS):
        for lang in CATALOGUES:
            assert i18n.has(f"cfg.section.{section}", lang=lang), f"{lang}: {section}"


def test_unknown_key_returns_itself_rather_than_raising():
    assert i18n.t("no.such.key") == "no.such.key"


def test_missing_english_entry_falls_back_to_polish(monkeypatch):
    monkeypatch.setitem(CATALOGUES["pl"], "tmp.only_pl", "tylko po polsku")
    assert i18n.t_in("en", "tmp.only_pl") == "tylko po polsku"


def test_language_normalisation():
    assert i18n.normalize("EN") == "en"
    assert i18n.normalize("en-GB") == "en"
    assert i18n.normalize("pl_PL") == "pl"
    assert i18n.normalize("klingon") is None
    assert i18n.normalize(None) is None


def test_set_lang_falls_back_to_the_default(monkeypatch):
    # No session here: this is the engine/CLI path, where the process default decides.
    # Importing the dashboard elsewhere in the suite leaves a value in st.session_state,
    # which would otherwise win — correctly, but not in the case under test.
    monkeypatch.setattr(i18n, "_session_lang", lambda: None)
    monkeypatch.setattr(i18n, "_default_lang", i18n.DEFAULT_LANG)
    assert i18n.set_lang("en") == "en"
    assert i18n.get_lang() == "en"
    assert i18n.set_lang("klingon") == i18n.DEFAULT_LANG


def test_the_session_language_beats_the_process_default(monkeypatch):
    """A dashboard serves several viewers from one process; the default must not win."""
    monkeypatch.setattr(i18n, "_session_lang", lambda: "en")
    monkeypatch.setattr(i18n, "_default_lang", "pl")
    assert i18n.get_lang() == "en"


def test_a_missing_placeholder_does_not_lose_the_sentence(monkeypatch):
    monkeypatch.setitem(CATALOGUES["pl"], "tmp.needs", "wynik {value}")
    assert i18n.t_in("pl", "tmp.needs") == "wynik {value}"
