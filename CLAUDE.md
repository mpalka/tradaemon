# CLAUDE.md

## Versioning

Every code change bumps the last digit of `__version__` in
`src/trademon/__init__.py` (0.2.0 → 0.2.1) and adds a line to **both** changelogs —
`CHANGELOG.md` (English) and `CHANGELOG.pl.md` (Polish) — under a new version heading.
That version number lives in one place; `pyproject.toml` reads it from there via
`[tool.hatch.version]`, so there is nothing to keep in sync by hand.

The middle digit moves only for large things (a new module, a rebuild), and the user
decides when — never bump the minor on your own initiative.

The panel shows this number under the title, so after a deployment you can tell from a
browser whether the running container is the fresh one.

## Languages

The panel and the docs exist in Polish and English. Polish is the source language.

- **User-facing strings live in `src/trademon/locales/pl.py` and `en.py`**, never inline
  in the code. Add a key to both files or `tests/test_i18n.py` fails, which also checks
  that the `{placeholders}` match.
- Code comments, docstrings and log messages are **English**.
- Docs come in pairs: `README.md` / `README.pl.md`, `howitworks.md` / `howitworks.pl.md`,
  and so on. Update both.
- Some strings are **data, not display**: the verdict tokens in `models/reports/*.csv`
  (`KANDYDAT`, `PUŁAPKA`, …) and the `?layout=` query values. Translating those breaks
  saved reports and people's bookmarks — translate the label, never the token.
