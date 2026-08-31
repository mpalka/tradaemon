"""Price preview for a single instrument — the chart behind a click.

Both beginner screens list instruments as sentences ("Bought ETH for $100",
"LTC/USDT closed long"). Until now that was where the story ended: to see what
the price actually did, you had to leave the panel. Clicking an instrument here
opens its own price chart, with the bot's own fills drawn on it.

Two deliberate choices:

* **Selection lives in `st.session_state`, not in `st.popover`.** The crypto screen
  runs inside a `run_every` fragment, so it re-renders every 15 s; a popover would
  be slammed shut each time, while a stored selection is simply redrawn.
* **Hover shows numbers, not a chart.** Streamlit cannot render a chart on hover
  without a custom JS component, so hovering gives the native tooltip
  (`summary()`) — price now, 24 h and 7 d change — and clicking gives the picture.

Self-contained on purpose — it must not import app.py (which auto-runs on import).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import altair as alt
import pandas as pd
import streamlit as st

from trademon.config import load_config
from trademon.dashboard import humanize, layout
from trademon.data import storage
from trademon.i18n import t
from trademon.portfolio import data as portfolio_data

cfg = load_config()
ACCENT, GOOD, BAD, MUTED = "#2a78d6", humanize.GOOD, humanize.BAD, humanize.MUTED
RANGES = {"7d": 7, "30d": 30, "90d": 90}
DEFAULT_RANGE = "30d"
PRICE_COLUMNS = ["timestamp", "close"]
MARK_COLUMNS = ["timestamp", "price", "typ"]
# Stable codes, not labels: they are values in a DataFrame column and in Altair's
# scale domain, and `render()` filters on HELD. Translated once, at the chart.
ENTRY, EXIT, HELD = "entry", "exit", "held"

_KEY = "price_preview"   # {"symbol", "section", "at"} or absent

try:
    DISPLAY_TZ: ZoneInfo | None = ZoneInfo(cfg.display_timezone)
except ZoneInfoNotFoundError:
    DISPLAY_TZ = None


# ---------- selection (pure) ----------

def next_selection(current: dict | None, symbol: str, section: str,
                   at: str | None = None, item: str | None = None) -> dict | None:
    """Clicking the open row again closes the preview; anything else opens it.

    `section` keeps the two lists apart (the same pair can sit in "Co bot trzyma"
    and in the event log at once); `item` identifies the single row that was
    clicked, so the chart can be drawn under *that* line rather than under the
    whole list — a chart fifteen rows below the click reads as nothing happening.
    """
    if (current and current.get("section") == section
            and current.get("symbol") == symbol
            and current.get("item") == item):
        return None
    return {"symbol": symbol, "section": section, "at": at, "item": item}


# ---------- price series (pure) ----------

def window(df: pd.DataFrame, days: int, at: str | None = None) -> pd.DataFrame:
    """The last `days` of prices — widened to reach `at` when the preview was opened
    from an old event, which would otherwise land on an empty chart."""
    if df.empty or "timestamp" not in df:
        return df
    ts = pd.to_datetime(df["timestamp"], utc=True)
    start = ts.max() - pd.Timedelta(days=days)
    if at is not None:
        moment = pd.to_datetime(at, utc=True) - pd.Timedelta(days=1)  # a little air
        start = min(start, moment)
    return df[ts >= start].reset_index(drop=True)


def pct_change(df: pd.DataFrame, hours: float, ts: pd.Series | None = None) -> float | None:
    """Percent move over the last `hours`, or None when the history is too short.

    `ts` is the already-parsed timestamp column. Parsing it is the expensive part —
    `pd.to_datetime` costs ~5 ms on a full 4h history even when the column is
    already datetime64 — and `summary` asks for two horizons off the same frame,
    so it parses once and passes the result in rather than paying twice.
    """
    if len(df) < 2:
        return None
    if ts is None:
        ts = pd.to_datetime(df["timestamp"], utc=True)
    past = df[ts <= ts.max() - pd.Timedelta(hours=hours)]
    if past.empty:
        return None
    first, last = float(past["close"].iloc[-1]), float(df["close"].iloc[-1])
    return (last / first - 1.0) * 100.0 if first else None


# The tooltip looks back seven days. On 4h candles that is 42 rows, on the portfolio
# manager's daily bars 7 — so a 200-row tail covers both with room to spare, while
# keeping `pd.to_datetime` off the ~12k rows of stored history behind it. The number
# is a bound on the *lookback*, not on the data: a longer history is not truncated
# anywhere else, only ignored for this one calculation.
SUMMARY_TAIL = 200


def summary(df: pd.DataFrame) -> str:
    """The hover tooltip: what the price is doing, in one line.

    Runs on a tail slice rather than the whole frame. The event journal renders up
    to sixty rows per refresh and every one of them carries a tooltip, so this is
    the panel's hottest path by a wide margin — see `tooltips()` for the other half
    of that story.
    """
    if df is None or df.empty:
        return t("price.no_quotes")
    tail = df.tail(SUMMARY_TAIL)
    ts = pd.to_datetime(tail["timestamp"], utc=True)
    parts = [t("price.now", price=humanize.money2(float(tail["close"].iloc[-1])))]
    for key, hours in (("price.span.24h", 24), ("price.span.7d", 24 * 7)):
        change = pct_change(tail, hours, ts=ts)
        label = t(key)
        parts.append(f"{label} {change:+.1f}%" if change is not None else f"{label} —")
    return " · ".join(parts) + "  \n" + t("price.click_for_chart")


def tooltips(prices_for: Callable[[str], pd.DataFrame]) -> Callable[[str], str]:
    """One tooltip per instrument for the whole render, not one per row.

    The event journal repeats the same handful of pairs across its sixty rows — a
    live book shows eleven distinct instruments in those sixty lines — and each row
    used to rebuild the pair's price frame and re-derive its tooltip from scratch.
    Measured on the NAS's own books that came to ~1.1 s of pandas per refresh, every
    15 s, to produce eleven distinct strings.

    Returns a closure rather than caching in `st.cache_data`: the frame it would key
    on is the equity journal extended with a live point that moves every 60 s, so a
    cross-run cache would miss about as often as it hits. Within one render the
    prices cannot change, which is exactly the scope a plain dict covers.
    """
    cache: dict[str, str] = {}

    def get(symbol: str) -> str:
        if symbol not in cache:
            cache[symbol] = summary(prices_for(symbol))
        return cache[symbol]

    return get


def memoized(prices_for: Callable[[str], pd.DataFrame]) -> Callable[[str], pd.DataFrame]:
    """`prices_for` that reads each instrument once per render.

    Both beginner screens ask for the same pair from several places — the position
    cards, the event rows, and `render()` for whichever row is open. The underlying
    Parquet read is already cached by `closes()`; what this saves is the per-call
    work on top of it (the journal tail merge, a concat and a sort over the full
    history).
    """
    cache: dict[str, pd.DataFrame] = {}

    def get(symbol: str) -> pd.DataFrame:
        if symbol not in cache:
            cache[symbol] = prices_for(symbol)
        return cache[symbol]

    return get


def trade_points(trades: pd.DataFrame | None, symbol: str,
                 start=None, end=None) -> pd.DataFrame:
    """The bot's own fills for one instrument, as chart points.

    Two journals, two shapes: the scalper writes a finished round trip per row
    (entry_time/exit_time), the portfolio manager one fill per row
    (timestamp/side) — both end up as (timestamp, price, entry/exit).
    """
    empty = pd.DataFrame(columns=MARK_COLUMNS)
    if trades is None or not len(trades) or "symbol" not in trades:
        return empty
    rows = trades[trades["symbol"] == symbol]
    if not len(rows):
        return empty

    parts = []
    if "entry_time" in rows:
        parts.append(pd.DataFrame({"timestamp": rows["entry_time"],
                                   "price": rows["entry_price"], "typ": ENTRY}))
        if "exit_time" in rows:
            closed = rows.dropna(subset=["exit_time"])
            parts.append(pd.DataFrame({"timestamp": closed["exit_time"],
                                       "price": closed["exit_price"], "typ": EXIT}))
    elif "timestamp" in rows and "price" in rows:
        side = rows["side"] if "side" in rows else pd.Series(ENTRY, index=rows.index)
        parts.append(pd.DataFrame({
            "timestamp": rows["timestamp"], "price": rows["price"],
            "typ": side.map({"buy": ENTRY, "long": ENTRY}).fillna(EXIT),
        }))
    if not parts:
        return empty

    out = pd.concat(parts, ignore_index=True).dropna(subset=["timestamp", "price"])
    return _in_window(out, start, end)


def _in_window(marks: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """Clip marks to the visible range and put them in time order."""
    out = marks.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    if start is not None:
        out = out[out["timestamp"] >= pd.to_datetime(start, utc=True)]
    if end is not None:
        out = out[out["timestamp"] <= pd.to_datetime(end, utc=True)]
    return out.sort_values("timestamp").reset_index(drop=True)


def open_position_point(pos: dict | None, start=None, end=None) -> pd.DataFrame:
    """The position the bot is holding *right now*, which no journal row describes.

    The scalper journals a round trip only once it closes, so a position still
    open is absent from `trades.jsonl` entirely — and the chart, built from that
    journal alone, told the opposite of the card above it: LINK held since the 8th
    drew no marks at all, while LTC and ADA ended on a red exit triangle. Worse,
    that exit and the re-entry that followed it landed on the same candle (the
    close-and-reopen the timeout used to force), so the picture showed the half of
    the manoeuvre that looks like leaving and hid the half that came back.

    `state.json` has what the journal lacks — `entry_time` and `entry_price` from
    `Position.to_json` — and this turns it into the same (timestamp, price, typ)
    shape `trade_points` produces, so the two simply concatenate. Missing or
    unparsable fields yield an empty frame rather than an exception: this is on
    the panel's drawing path, where a broken chart is worse than a bare one.
    """
    empty = pd.DataFrame(columns=MARK_COLUMNS)
    if not pos or pos.get("entry_time") is None or pos.get("entry_price") is None:
        return empty
    try:
        row = pd.DataFrame({"timestamp": [pd.to_datetime(pos["entry_time"], utc=True)],
                            "price": [float(pos["entry_price"])], "typ": HELD})
    except (ValueError, TypeError):
        return empty
    return _in_window(row, start, end)


def chart_marks(trades: pd.DataFrame | None, symbol: str, pos: dict | None,
                start=None) -> pd.DataFrame:
    """Every fill worth drawing for one instrument: closed round trips plus the
    position still open, in time order.

    Clipped at the start — the reader chose a range — and deliberately left open at
    the end. The window's right edge is wherever the price history stops, and the
    downloader runs weekly while the bot trades every candle, so the newest fills
    routinely sit past it. Those are the ones a reader is looking for; cutting them
    is what made the chart omit the last entries.
    """
    return pd.concat([trade_points(trades, symbol, start),
                      open_position_point(pos, start)],
                     ignore_index=True).sort_values("timestamp").reset_index(drop=True)


# ---------- price sources ----------

@st.cache_data(ttl=300, show_spinner=False)
def _closes(path: str, mtime: float) -> pd.DataFrame:
    """`mtime` is unused in the body on purpose — it is there to key the cache."""
    df = storage.load_ohlcv(Path(path))
    return df[PRICE_COLUMNS].reset_index(drop=True) if len(df) else pd.DataFrame(
        columns=PRICE_COLUMNS)


def closes(path: Path) -> pd.DataFrame:
    """Close prices from a stored OHLCV file. The file's mtime is part of the cache
    key, so a freshly downloaded candle shows up without waiting out the TTL."""
    if not path.exists():
        return pd.DataFrame(columns=PRICE_COLUMNS)
    return _closes(str(path), path.stat().st_mtime)


def crypto_prices(symbol: str, fallback: pd.DataFrame | None = None) -> pd.DataFrame:
    """Stored candles for a pair, extended with the closes the engine journals
    alongside equity.

    The journal is not only a fallback for a pair whose Parquet file does not exist
    yet — it is what keeps the chart current. The downloader runs weekly
    (`docker-compose.yml`, the `refresher` service), so the stored candles can end
    six days before the bot's newest trade, and a line that stops there makes every
    fill since look like it never happened. The engine writes one close per pair per
    candle, so everything past the Parquet's last row is already on disk.

    The seam is worth naming: stored candles are indexed by their OPEN time and the
    engine journals by CLOSE, so the two conventions meet one timeframe apart. On a
    chart spanning days that is invisible, and the alternative — a line that ends
    last Tuesday — is not."""
    df = closes(storage.ohlcv_path(cfg.paths.data_dir, cfg.exchange.id, symbol,
                                   cfg.exchange.timeframe))
    if fallback is None or not len(fallback) or not {"symbol", "close"} <= set(fallback):
        return df
    rows = fallback[fallback["symbol"] == symbol]
    if not len(rows):
        return df
    rows = rows[PRICE_COLUMNS].copy()
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], utc=True)
    if len(df):
        rows = rows[rows["timestamp"] > pd.to_datetime(df["timestamp"], utc=True).max()]
        if not len(rows):
            return df
        df = pd.concat([df, rows], ignore_index=True)
    else:
        df = rows
    return df.sort_values("timestamp").reset_index(drop=True)


def portfolio_prices(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Daily closes for an ETF/stock held by the portfolio manager."""
    return closes(portfolio_data.path_for(data_dir, symbol))


# ---------- widgets ----------

def styles() -> None:
    """Left-align the instrument buttons. Call once per screen, before the first one.

    Streamlit centres a stretched button's label and offers no alignment parameter,
    which would knock every event line out of the column the rest of the screen
    reads down; a content-width button is not the way out either — inside a column
    it collapses to one character per line. `st-key-pv_*` are the container classes
    Streamlit derives from our widget keys, so this touches no other button.
    """
    st.markdown(
        "<style>"
        "div[class*='st-key-pv_'] button, div[class*='st-key-pv_'] button div,"
        "div[class*='st-key-pv_'] button span, div[class*='st-key-pv_'] button p"
        "{justify-content: flex-start !important; text-align: left !important;}"
        "</style>", unsafe_allow_html=True)


def preview_button(label: str, symbol: str, section: str, key: str,
                   at: str | None = None, tooltip: str | None = None) -> None:
    """One clickable instrument: hover for the numbers, click for the chart.

    Tertiary buttons render as plain text, so a fifteen-row event log stays a
    timeline instead of turning into a wall of grey boxes. `key` doubles as the
    row's identity, so `render(..., item=key)` can put the chart under this row.

    `tooltip` arrives already built (callers pass `tooltips(...)(symbol)`) rather
    than as the price frame this used to derive it from. Same string either way,
    but a `prices=` parameter is evaluated per row at the call site, which made
    sixty rows mean sixty derivations of eleven distinct tooltips.
    """
    if st.button(label, key=f"pv_{key}",   # the prefix `styles()` hangs its CSS on
                 help=tooltip, type="tertiary", width="stretch"):
        st.session_state[_KEY] = next_selection(st.session_state.get(_KEY), symbol,
                                                section, at, item=key)


def selected(section: str, item: str | None = None) -> dict | None:
    """The current selection, if it belongs here.

    With `item` the caller is one row asking "is it me?"; without it the caller
    owns the whole section (the position cards, where the chart goes under the
    row of tiles rather than inside a one-third-wide column).
    """
    sel = st.session_state.get(_KEY)
    if not sel or sel.get("section") != section:
        return None
    return sel if item is None or sel.get("item") == item else None


def _chart(prices: pd.DataFrame, marks: pd.DataFrame, entry_price: float | None,
           at: str | None) -> alt.LayerChart:
    data = prices.copy()
    data["timestamp"] = humanize.to_local(data["timestamp"], DISPLAY_TZ)
    layers = [alt.Chart(data).mark_line(color=ACCENT).encode(
        x=alt.X("timestamp:T", title=None, axis=layout.time_axis()),
        y=alt.Y("close:Q", title="Kurs ($)", scale=alt.Scale(zero=False, nice=False)),
        tooltip=[alt.Tooltip("timestamp:T", title="Czas", format="%d.%m.%Y %H:%M"),
                 alt.Tooltip("close:Q", title=t("price.rate"), format=",.2f")],
    )]

    if entry_price:
        line = pd.DataFrame({"cena": [float(entry_price)]})
        layers.append(alt.Chart(line).mark_rule(color=MUTED, strokeDash=[4, 4]).encode(
            y=alt.Y("cena:Q"),
            tooltip=[alt.Tooltip("cena:Q", title=t("price.entry_price"), format=",.2f")]))

    if at is not None:
        moment = pd.DataFrame({"chwila": [humanize.to_local(at, DISPLAY_TZ)]})
        layers.append(alt.Chart(moment).mark_rule(color=MUTED, strokeDash=[2, 3]).encode(
            x=alt.X("chwila:T"),
            tooltip=[alt.Tooltip("chwila:T", title=t("price.this_event"),
                                 format="%d.%m.%Y %H:%M")]))

    if len(marks):
        pts = marks.copy()
        pts["timestamp"] = humanize.to_local(pts["timestamp"], DISPLAY_TZ)
        # The column holds codes; the legend needs words. Translate here, where the
        # domain order is written down anyway, so colour and shape stay paired.
        domain = [t(f"price.mark.{code}") for code in (ENTRY, EXIT, HELD)]
        pts["typ"] = pts["typ"].map(dict(zip((ENTRY, EXIT, HELD), domain, strict=True)))
        scale = alt.Scale(domain=domain, range=[GOOD, BAD, GOOD])
        # A circle for the open position rather than a third triangle: after a
        # close-and-reopen it lands on the same candle as the exit, a tenth of a
        # percent away in price, and two triangles there would read as one smudge.
        shapes = alt.Scale(domain=domain,
                           range=["triangle-up", "triangle-down", "circle"])
        layers.append(alt.Chart(pts).mark_point(size=80, filled=True, opacity=0.9).encode(
            x=alt.X("timestamp:T"), y=alt.Y("price:Q"),
            color=alt.Color("typ:N", title=None, scale=scale, legend=layout.legend()),
            shape=alt.Shape("typ:N", title=None, scale=shapes, legend=layout.legend()),
            tooltip=[alt.Tooltip("typ:N", title=t("price.bot")),
                     alt.Tooltip("timestamp:T", title=t("chart.time"),
                                 format="%d.%m.%Y %H:%M"),
                     alt.Tooltip("price:Q", title=t("price.price"), format=",.2f")]))

    return alt.layer(*layers).properties(height=layout.chart_height(240))


def render(section: str, prices_for: Callable[[str], pd.DataFrame],
           trades: pd.DataFrame | None = None, positions: dict | None = None,
           item: str | None = None) -> None:
    """Draw the preview for whatever this section has selected (nothing, usually).

    Called with `item` from inside a list loop, so the chart lands directly under
    the row that was clicked: fifteen rows further down it reads as nothing having
    happened at all.

    `prices_for` is a lookup rather than a table because each module stores prices
    its own way — crypto candles under data/, ETF closes under the Yahoo layout.
    """
    sel = selected(section, item)
    if not sel:
        return
    symbol, at = sel["symbol"], sel.get("at")

    with st.container(border=True):
        head = st.columns([4, 1])
        head[0].markdown(f"**📈 {t('price.chart_for', symbol=symbol)}**")
        if head[1].button(t("price.close"), key=f"{section}_close", type="tertiary"):
            st.session_state[_KEY] = None
            st.rerun()

        prices = prices_for(symbol)
        if prices is None or prices.empty:
            st.caption(t("price.no_quotes_for_chart"))
            return

        names = list(RANGES)
        rng = st.radio(t("price.range"), names, index=names.index(DEFAULT_RANGE),
                       horizontal=True, label_visibility="collapsed",
                       format_func=lambda code: t(f"price.range.{code}"),
                       key=f"{section}_range")
        win = window(prices, RANGES[rng], at)
        if len(win) < 2:
            st.caption(t("price.too_few_quotes"))
            return

        pos = (positions or {}).get(symbol) or {}
        first = win["timestamp"].iloc[0]
        marks = chart_marks(trades, symbol, pos, first)
        held = marks[marks["typ"] == HELD]
        st.altair_chart(_chart(win, marks, pos.get("entry_price"), at), width="stretch")

        change = (float(win["close"].iloc[-1]) / float(win["close"].iloc[0]) - 1.0) * 100.0
        note = t("price.note.triangles") if len(marks) else ""
        # Only explain the circle when one is on screen — a legend for a mark that
        # is not there reads as a mark the reader failed to find.
        if len(held):
            note += t("price.note.circle")
        st.caption(t("price.instrument_change", change=f"{change:+.1f}", note=note))
