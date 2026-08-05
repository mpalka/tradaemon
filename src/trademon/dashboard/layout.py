"""Screen-size decisions, in one place.

Streamlit already stacks `st.columns` below a 640px viewport (its own `breakpoints.columns`
media query), so the column layouts throughout the dashboard need no help on a phone.
What does not survive a 390px screen is the rest: Altair's right-hand legend eats ~40% of
the plot, `%d.%m %H:%M` tick labels collide, and an eight-column `st.dataframe` becomes a
horizontal scroll nobody reads.

Detection is server-side via the User-Agent (`st.context.headers`). UA sniffing is
imperfect, but here it only picks a layout — the worst case is a desktop layout on a phone,
never a wrong number — and `layout_switch()` renders an explicit override for the misses.
"""

from __future__ import annotations

import re

import altair as alt
import pandas as pd
import streamlit as st

# Tablets deliberately fall through to the desktop layout: at 768px+ the wide tables
# and side legends are still readable, which is the whole reason for a breakpoint.
_MOBILE_UA = re.compile(r"iPhone|iPod|Android.+Mobile|Windows Phone|BlackBerry", re.IGNORECASE)

_OVERRIDE_KEY = "layout_override"
_AUTO, _MOBILE, _DESKTOP = "auto", "telefon", "komputer"

GOOD, BAD, MUTED = "#0ca30c", "#d03b3b", "#999999"


def _layout_param() -> str | None:
    """`?layout=` from the URL, or None outside a script run (tests, bare imports)."""
    try:
        return st.query_params.get("layout")
    except Exception:  # noqa: BLE001 - no script run context
        return None


def _ua_is_mobile() -> bool:
    try:
        return bool(_MOBILE_UA.search(st.context.headers.get("User-Agent", "")))
    except Exception:  # noqa: BLE001 - headers are unavailable in tests//bare reruns
        return False


def is_mobile() -> bool:
    """Query parameter wins, then the in-app switch, then the User-Agent.

    `?layout=telefon` is there so the choice can be bookmarked — handy when the
    detection misses on a particular browser, and the only way to exercise the mobile
    layout from a desktop browser.
    """
    param = _layout_param()
    if param in (_MOBILE, _DESKTOP):
        return param == _MOBILE

    choice = st.session_state.get(_OVERRIDE_KEY, _AUTO)
    if choice == _MOBILE:
        return True
    if choice == _DESKTOP:
        return False
    return _ua_is_mobile()


def layout_switch() -> None:
    """Manual override, so both layouts can be checked from one device."""
    st.radio(
        "Układ", [_AUTO, _MOBILE, _DESKTOP], key=_OVERRIDE_KEY, horizontal=True,
        help="„auto\" rozpoznaje urządzenie po przeglądarce. Zmień, jeśli trafiło źle "
             "albo chcesz zobaczyć drugi układ. Można też dopisać do adresu "
             "`?layout=telefon`, żeby zapisać wybór w zakładce.",
    )
    if _layout_param():
        st.caption("Układ wymuszony parametrem `?layout` w adresie — "
                   "przełącznik powyżej jest w tej chwili nieaktywny.")


# ---------- sizing ----------

def chart_height(desktop: int = 300) -> int:
    """Phones are tall and narrow: a 300px plot plus a bottom legend pushes everything
    below it off the first screen."""
    return 220 if is_mobile() else desktop


def refresh_interval() -> str:
    """A 4h candle closes six times a day — polling every 15s on a phone spends data
    and battery to redraw the same numbers."""
    return "60s" if is_mobile() else "15s"


def max_cards() -> int:
    """How many rows to show before hiding the rest behind an expander."""
    return 5 if is_mobile() else 12


# ---------- Altair ----------

def legend(title: str | None = None) -> alt.Legend:
    """Bottom, horizontal: the default right-hand placement costs ~40% of the canvas
    at 390px, which matters far more than the vertical space it gives back."""
    if is_mobile():
        return alt.Legend(title=title, orient="bottom", direction="horizontal",
                          columns=1, labelLimit=200)
    return alt.Legend(title=title)


def time_axis(title: str | None = None) -> alt.Axis:
    fmt = "%d.%m" if is_mobile() else "%d.%m %H:%M"
    return alt.Axis(format=fmt, grid=False, title=title,
                    tickCount=4 if is_mobile() else 6,
                    labelAngle=0)


# ---------- tables ----------

def _fmt(value, spec: str | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if spec is None:
        return str(value)
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)


def cards(
    df: pd.DataFrame,
    label_col: str,
    fields: list[str],
    formats: dict[str, str] | None = None,
    color_by: str | None = None,
) -> None:
    """A wide table rendered as one stacked block per row.

    `fields` is the shortlist worth reading on a phone; anything else in `df` is
    dropped rather than shrunk, because a squeezed eight-column grid communicates
    less than three clear numbers.
    """
    formats = formats or {}
    if df.empty:
        st.caption("Brak danych.")
        return
    rows = df.to_dict("records")
    shown, hidden = rows[:max_cards()], rows[max_cards():]
    for rec in shown:
        _card(rec, label_col, fields, formats, color_by)
    if hidden:
        with st.expander(f"Pokaż pozostałe ({len(hidden)})"):
            for rec in hidden:
                _card(rec, label_col, fields, formats, color_by)


def _card(rec: dict, label_col: str, fields: list[str],
          formats: dict[str, str], color_by: str | None) -> None:
    parts = [f"{f} **{_fmt(rec.get(f), formats.get(f))}**" for f in fields if f in rec]
    line = " · ".join(parts)
    if color_by and isinstance(rec.get(color_by), (int, float)) and not pd.isna(rec[color_by]):
        tone = "green" if rec[color_by] > 0 else ("red" if rec[color_by] < 0 else "gray")
        line = f":{tone}[{line}]"
    st.markdown(f"**{rec.get(label_col, '?')}**  \n{line}")
