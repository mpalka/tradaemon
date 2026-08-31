"""Message catalogues, one plain dict per language.

No gettext, no babel, no `.po` toolchain and no new dependency — the project runs on
twelve packages and this is not worth a thirteenth. A translation is one file, and
`tests/test_i18n.py` enforces that every language defines the same keys with the same
`{placeholders}`, so a half-finished catalogue fails the suite rather than the screen.

Keys are dotted and named for where the string appears: `app.holdings.empty`,
`cfg.field.prob_threshold.help`, `alert.kill_switch`.
"""

from __future__ import annotations

from trademon.locales.en import MESSAGES as EN
from trademon.locales.pl import MESSAGES as PL

# Order matters only for the language picker; Polish is the source language.
CATALOGUES: dict[str, dict[str, str]] = {"pl": PL, "en": EN}

__all__ = ["CATALOGUES"]
