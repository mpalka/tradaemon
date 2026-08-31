"""Plain-language layer for the beginner dashboard.

Turns raw engine data (signal reasons, alert kinds, exit reasons, positions) into
sentences a first-time investor understands, in whichever language the viewer picked.
Shared by the crypto and portfolio views so the wording stays consistent. Pure
functions — no Streamlit here, so this module stays unit-testable and is the natural
anchor for the message catalogues in `tradaemon.locales`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

import pandas as pd

from tradaemon.i18n import t

GOOD, BAD, MUTED = "#0ca30c", "#d03b3b", "#999999"

# Why the crypto bot did / didn't trade on the last candle (engine `signals`).
# `no_atr` and `features_nan` deliberately share a sentence: the distinction is
# real in the engine and meaningless to the reader.
REASON_CODES = ("in_position", "warmup", "risk_blocked", "features_nan", "no_atr",
                "below_threshold", "enter_long", "enter_short")

# How a position closed.
EXIT_CODES = ("tp", "sl", "timeout")

# Jargon that earns a tooltip (`help=`) wherever it appears.
GLOSSARY_TERMS = ("sharpe", "max_drawdown", "profit_factor", "win_rate", "buy_hold",
                  "rebalance", "drift", "cagr", "volatility", "kill_switch",
                  "money_at_work", "return_total", "time_in_market", "return_at_work",
                  "bh_fair")

# Alert kinds -> emoji. Language-independent, so it stays a plain dict.
ALERT_EMOJI = {
    "trade_open": "🟢",
    "trade_close": "🔁",
    "trade_rollover": "⏩",
    "connection": "📡",
    "config": "⚙️",
    "kill_switch": "🛑",
    "drawdown": "⚠️",
    "rebalance": "⚖️",
    "initial_allocation": "🎯",
}


def reason(code: str) -> str:
    """Engine signal reason -> a sentence. Unknown codes pass through unchanged."""
    return t(f"reason.{code}") if code in REASON_CODES else code


def exit_reason(code: str) -> str:
    """`tp` / `sl` / `timeout` -> a sentence."""
    return t(f"exit.{code}") if code in EXIT_CODES else code


def glossary(term: str) -> str:
    """One-line explanation of a piece of jargon, for a `help=` tooltip."""
    return t(f"glossary.{term}")


# ---------- formatting ----------

def dec(text: str) -> str:
    """Swap the decimal point for whatever the language writes — `0,58` in Polish.

    Applied to an already-formatted number, not to the float, so `f"{x:.2f}"` keeps
    deciding the precision and this only decides how it is punctuated.
    """
    return text.replace(".", t("fmt.decimal_separator"))


def md(text: str) -> str:
    """Escape a rendered sentence for Streamlit's markdown.

    A pair of `$` in one string is LaTeX to Streamlit, so a caption naming two amounts
    silently loses both currency symbols and renders the numbers between them as maths.
    `st.metric` is unaffected, which is why the bug hid in the captions only.
    """
    return text.replace("$", r"\$")


def money(x: float) -> str:
    return t("fmt.money", amount=f"{x:,.0f}")


def money2(x: float) -> str:
    return t("fmt.money", amount=f"{x:,.2f}")


def signed_money(x: float) -> str:
    return t("fmt.money", amount=f"{x:+,.2f}")


def to_local(ts, tz: tzinfo | None = None):
    """UTC/ISO timestamps -> local wall-clock (tz-naive).

    Charts are drawn from naive local times on purpose: Altair would otherwise
    re-interpret them in the *browser's* zone, so the same candle would sit at a
    different hour depending on who is looking. Accepts a Series or a scalar.
    """
    out = pd.to_datetime(ts, utc=True)
    if tz is not None:
        out = out.dt.tz_convert(tz) if hasattr(out, "dt") else out.tz_convert(tz)
    return out.dt.tz_localize(None) if hasattr(out, "dt") else out.tz_localize(None)


def _fmt_time(ts: str | datetime | None, tz: tzinfo | None = None) -> str:
    """Format a UTC timestamp as 'DD.MM HH:MM'. With `tz`, convert to that zone
    first so the wall-clock shown matches the viewer's local time."""
    if not ts:
        return "?"
    try:
        dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(ts)
        if tz is not None and dt.tzinfo is not None:
            dt = dt.astimezone(tz)
        return dt.strftime("%d.%m %H:%M")
    except (ValueError, TypeError):
        return str(ts)[:16].replace("T", " ")


# ---------- cards & events ----------

def position_card(pos: dict, last_price: float | None) -> dict:
    """A crypto position rendered as a human sentence + colour."""
    symbol = pos.get("symbol", "?")
    qty = float(pos.get("qty", 0.0))
    entry = float(pos.get("entry_price", 0.0))
    side = pos.get("side", "long")
    sign = 1 if side == "long" else -1
    price = float(last_price) if last_price else entry
    invested = qty * entry
    pnl = sign * qty * (price - entry)
    pct = (pnl / invested * 100.0) if invested else 0.0
    base = symbol.split("/")[0]
    title_key = "card.position.long" if side == "long" else "card.position.short"
    return {
        "symbol": symbol,
        "title": t(title_key, asset=base, amount=money(invested)),
        "detail": t("card.position.now", pnl=signed_money(pnl), pct=f"{pct:+.1f}"),
        "pnl": pnl,
        "pct": pct,
        "emoji": "🟢" if pnl >= 0 else "🔴",
        "color": GOOD if pnl > 0 else (BAD if pnl < 0 else MUTED),
    }


def holding_card(symbol: str, value: float, weight: float, target: float) -> dict:
    """A portfolio holding rendered as a human sentence + drift colour."""
    drift = (weight - target) * 100.0
    off = abs(drift) >= 3.0
    return {
        "symbol": symbol,
        "title": f"{symbol} — {money(value)}",
        "detail": t("card.holding.weight", weight=f"{weight * 100:.0f}",
                    target=f"{target * 100:.0f}"),
        "emoji": "⚖️" if off else "✅",
        "color": MUTED if not off else "#c47f00",
    }


def event_line(record: dict, tz: tzinfo | None = None) -> dict:
    """Turn one alert/trade record into {emoji, time, text} for the timeline.

    Records written from 0.2.0 onward carry `kind` plus a `params` dict, so the
    sentence is composed here and reads in the viewer's language. Older records —
    and every line already sitting in a running deployment's `alerts.jsonl` — hold
    only a pre-rendered Polish `message`, which we show verbatim. Retranslating
    history is not possible; losing it would be worse than showing it in one
    language.
    """
    kind = record.get("kind", "")
    emoji = ALERT_EMOJI.get(kind, "•")
    if kind == "trade_close" and "pnl" in record:
        emoji = "💰" if float(record.get("pnl", 0)) >= 0 else "🔻"
    if kind == "connection":
        # Same topic, two states, and the difference has to survive scanning: an
        # open alarm must not look like the line that ends it. Missing `ok` means
        # an outage — rows written before the flag existed are all outages, and
        # reading one of those as an all-clear is the failure worth avoiding.
        emoji = "✅" if record.get("ok", False) else "📡"
    return {"emoji": emoji, "time": _fmt_time(record.get("timestamp"), tz),
            "text": _event_text(record, kind)}


def _event_text(record: dict, kind: str) -> str:
    """Structured params first, then a stored message, then a bare fallback."""
    key = record.get("msg_key")
    params = record.get("params")
    if key and isinstance(params, dict):
        return t(key, **params)
    stored = record.get("message")
    if stored:
        return str(stored)
    if "exit_reason" in record:  # raw trade rows carry no friendly message at all
        return t("event.trade_closed", symbol=record.get("symbol", ""),
                 how=exit_reason(record["exit_reason"]))
    return kind or t("event.generic")


def bot_status(last_candle_ts: dict, timeframe_ms: int, now: datetime,
               tz: tzinfo | None = None) -> dict:
    """🟢/🔴 status line from the freshest heartbeat across pairs.

    `last_candle_ts` holds each pair's last *closed* candle by its OPEN time, so
    that candle only finalized `timeframe_ms` later — on 4h bars its open time
    naturally sits 4–8h behind the wall clock even when the bot is perfectly
    healthy. We reason about the candle's CLOSE time (open + timeframe) so the
    number matches intuition, and flag trouble only once a whole extra candle is
    overdue.
    """
    if not last_candle_ts:
        return {"ok": False, "emoji": "🔴", "text": t("status.bot.no_read")}
    try:
        latest_open = datetime.fromisoformat(max(last_candle_ts.values()))
    except ValueError:
        return {"ok": False, "emoji": "🔴", "text": t("status.bot.unknown_time")}
    bar = timedelta(milliseconds=timeframe_ms)
    closed_at = latest_open + bar          # when that candle actually finalized
    next_at = closed_at + bar              # when the next one is due
    overdue_ms = (now - closed_at).total_seconds() * 1000
    fresh = overdue_ms <= timeframe_ms + 15 * 60_000  # healthy until a full bar is missed
    when = _fmt_time(closed_at, tz)
    if fresh:
        return {"ok": True, "emoji": "🟢",
                "text": t("status.bot.running", when=when, next=_fmt_time(next_at, tz))}
    return {"ok": False, "emoji": "🔴", "text": t("status.bot.stale", when=when)}


# A stalled ticker is the earliest honest sign of trouble, so the panel may not
# wait longer than this before saying so. Five minutes is four missed refreshes:
# short enough to catch a real outage while it is still news, long enough that a
# single slow request does not cry wolf.
CONNECTION_STALE_SECONDS = 300


def _ago(seconds: float) -> str:
    """How long ago, in words that dodge plural rules — "3 minuty" vs "5 minut" is
    a distinction this line does not need to make, in any language."""
    if seconds < 90:
        return t("ago.just_now")
    minutes = int(seconds // 60)
    if minutes < 60:
        return t("ago.minutes", minutes=minutes)
    return t("ago.hours", hours=minutes // 60, minutes=minutes % 60)


def connection_status(updated_at: str | datetime | None, now: datetime) -> dict:
    """Is the bot actually reaching the exchange *right now*?

    `bot_status` answers a different question — whether a candle is overdue — and
    on 4h bars it stays green for hours after the exchange has gone silent. This
    reads `state.json`'s `updated_at`, which the ticker rewrites every 60 s and
    only ever on a successful call, so it is the sharpest liveness signal we have.

    It exists because the alert journal could not answer this. A dropped
    connection files an outage alert, but the matching all-clear is written by the
    process that saw the outage — and a container that restarts in between starts
    clean and never writes it. The alarm then hangs there, truthful about the past
    and misleading about the present. A heartbeat cannot go stale that way: it
    either ticked recently or it did not.
    """
    if not updated_at:
        return {"ok": False, "emoji": "📡", "text": t("status.conn.none")}
    try:
        ts = updated_at if isinstance(updated_at, datetime) else datetime.fromisoformat(
            str(updated_at))
    except ValueError:
        return {"ok": False, "emoji": "📡", "text": t("status.conn.unknown_time")}
    seconds = (now - ts).total_seconds()
    if seconds <= CONNECTION_STALE_SECONDS:
        return {"ok": True, "emoji": "📡", "text": t("status.conn.ok", ago=_ago(seconds))}
    return {"ok": False, "emoji": "📡", "text": t("status.conn.stale", ago=_ago(seconds))}
