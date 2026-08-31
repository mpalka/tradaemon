"""Which language the user reads — a seam, like `dashboard/auth.py` is for identity.

The project was written in Polish and Polish is still the default: nothing about a
fresh checkout changes for a Polish reader. English is a second catalogue, not a
rewrite, so adding a third language is one file and no code.

Two callers with different needs share one resolver:

* The **dashboard** serves several viewers from one process, so the language must be
  per-session. It lives in `st.session_state`, seeded from `?lang=` exactly the way
  `layout.py` already seeds the mobile/desktop override.
* The **engine, the CLI reports and the webhook** have no session at all. They read
  the module default, which `set_lang()` sets once at startup from
  `display_language` in the config.

`t()` never raises. A key missing from the active catalogue falls back to Polish (the
source language), and a key missing everywhere returns itself — a visibly wrong label
is a bug report, a KeyError mid-render is a blank page.
"""

from __future__ import annotations

import os
import sys

from trademon.locales import CATALOGUES

LANGS: tuple[str, ...] = tuple(CATALOGUES)
DEFAULT_LANG = "pl"
SOURCE_LANG = "pl"

# Where the dashboard keeps the per-session choice. Also the `?lang=` query parameter.
SESSION_KEY = "lang"

# Set by the panel when it shells out to a research script, so the report printed into
# `st.code` comes back in the language the reader is actually looking at. A subprocess
# has no session to inherit.
ENV_VAR = "TRADEMON_LANG"

_default_lang = DEFAULT_LANG


def normalize(lang: str | None) -> str | None:
    """`"EN"`, `"en-GB"`, `"en_US"` -> `"en"`. None for anything we do not have."""
    if not lang:
        return None
    code = str(lang).strip().lower().replace("_", "-").split("-")[0]
    return code if code in CATALOGUES else None


def set_lang(lang: str | None) -> str:
    """Set the process-wide default (engine, scripts, reports). Returns what stuck."""
    global _default_lang
    _default_lang = normalize(lang) or DEFAULT_LANG
    return _default_lang


def init(config_lang: str | None = None) -> str:
    """Resolve the process language once at startup: env var, then config, then default.

    The env var wins because it is the more specific request — the panel sets it per
    subprocess, while `display_language` is a standing preference in a file.
    """
    return set_lang(os.environ.get(ENV_VAR) or config_lang)


def get_lang() -> str:
    """The session's language inside Streamlit, otherwise the process default."""
    session = _session_lang()
    return session or _default_lang


def _session_lang() -> str | None:
    """`st.session_state` when there is a script run, None otherwise (tests, engine).

    Deliberately does not *import* streamlit: a research script shelling out from the
    panel, and the test suite, would otherwise pull it in only to be told there is no
    script context — which Streamlit reports by logging two warnings per call, straight
    into the report the panel is about to display. If the module is not already loaded,
    this is not a dashboard process and there is no session to read.
    """
    st = sys.modules.get("streamlit")
    if st is None:
        return None
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:  # a Streamlit that moved it: fall back to asking directly
        get_script_run_ctx = None
    try:
        if get_script_run_ctx is not None:
            # suppress_warning: asking is not an error here, and without it Streamlit
            # logs a line every time a CLI report resolves a single string.
            try:
                ctx = get_script_run_ctx(suppress_warning=True)
            except TypeError:  # older signature, without the keyword
                ctx = get_script_run_ctx()
            if ctx is None:
                return None
        return normalize(st.session_state.get(SESSION_KEY))
    except Exception:  # noqa: BLE001 - no script run context, or state unavailable
        return None


def t(key: str, /, **params: object) -> str:
    """Look up `key` in the active catalogue and format it with `params`."""
    return _format(lookup(key), key, params)


def t_in(lang: str, key: str, /, **params: object) -> str:
    """Same, but in a language named outright — for the webhook and for tests."""
    return _format(lookup(key, lang=lang), key, params)


def lookup(key: str, *, lang: str | None = None) -> str:
    """The raw catalogue entry, before formatting. Polish, then the key itself."""
    code = normalize(lang) or get_lang()
    entry = CATALOGUES[code].get(key)
    if entry is None and code != SOURCE_LANG:
        entry = CATALOGUES[SOURCE_LANG].get(key)
    return entry if entry is not None else key


def has(key: str, *, lang: str | None = None) -> bool:
    """Whether the catalogue actually defines `key` (no Polish fallback, no key echo)."""
    code = normalize(lang) or get_lang()
    return key in CATALOGUES[code]


def _format(entry: str, key: str, params: dict[str, object]) -> str:
    if not params:
        return entry
    try:
        return entry.format(**params)
    except (KeyError, IndexError, ValueError):
        # A placeholder the caller did not supply: show the unformatted sentence
        # rather than losing the whole screen to a translation typo.
        return entry
