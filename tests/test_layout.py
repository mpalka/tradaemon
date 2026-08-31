"""Tests for the mobile/desktop switch (dashboard/layout.py).

The one thing here that is a contract rather than a preference: `?layout=` is a URL
parameter documented in the README, so people have it in bookmarks. 0.2.0 made the
internal codes language-independent, and the Polish spellings have to keep working.
"""

from __future__ import annotations

import pytest

from trademon.dashboard import layout


@pytest.fixture
def url(monkeypatch):
    """Pretend a `?layout=` value is in the address bar."""
    def _set(value):
        monkeypatch.setattr(layout, "_layout_param",
                            lambda: layout._PARAM_ALIASES.get(str(value).strip().lower())
                            if value else None)
    return _set


@pytest.mark.parametrize("value,mobile", [
    # the spellings from before 0.2.0 — these are in people's bookmarks
    ("telefon", True), ("komputer", False),
    # and the language-independent ones it added
    ("mobile", True), ("phone", True), ("desktop", False),
    # case and stray whitespace should not decide a layout
    ("Telefon", True), ("  MOBILE  ", True),
])
def test_the_url_parameter_still_understands_every_spelling(url, value, mobile):
    url(value)
    assert layout.is_mobile() is mobile


def test_an_unknown_value_falls_through_to_detection(url, monkeypatch):
    url("nonsense")
    monkeypatch.setattr(layout, "_ua_is_mobile", lambda: True)
    assert layout.is_mobile() is True


def test_the_internal_codes_carry_no_language():
    """If these ever become translated labels again, the query parameter and the
    session state stop matching each other the moment someone switches language."""
    assert (layout._AUTO, layout._MOBILE, layout._DESKTOP) == ("auto", "mobile", "desktop")
