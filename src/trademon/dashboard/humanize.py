"""Plain-Polish translation layer for the beginner dashboard.

Turns raw engine data (signal reasons, alert kinds, exit reasons, positions) into
sentences a first-time investor understands. Shared by the crypto and portfolio
views so the wording stays consistent. Pure functions — no Streamlit here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

import pandas as pd

GOOD, BAD, MUTED = "#0ca30c", "#d03b3b", "#999999"

# Why the crypto bot did / didn't trade on the last candle (engine `signals`).
REASON_PL = {
    "in_position": "trzyma pozycję",
    "warmup": "rozgrzewa się (zbiera dane)",
    "risk_blocked": "wstrzymany limitem ryzyka",
    "features_nan": "czeka na komplet danych",
    "no_atr": "czeka na komplet danych",
    "below_threshold": "nie widzi wystarczającej okazji",
    "enter_long": "otwiera pozycję (stawia na wzrost)",
    "enter_short": "otwiera pozycję (stawia na spadek)",
}

# How a position closed.
EXIT_PL = {
    "tp": "z zyskiem (cel osiągnięty)",
    "sl": "ze stratą (bezpiecznik)",
    "timeout": "po upływie czasu",
}

# Alert kinds -> (emoji, short label). Alert messages are already Polish, so the
# emoji + time is usually all we add; labels are a fallback when a message is absent.
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

# One-line explanations shown as tooltips (`help=`) next to jargon.
GLOSSARY = {
    "Sharpe": "Zysk w stosunku do wahań. Wyżej = lepiej. Powyżej 1 to dobrze, "
              "poniżej 0 oznacza stratę względem ryzyka.",
    "Max drawdown": "Największy spadek od szczytu do dołka. -20% znaczy, że w "
                    "najgorszym momencie portfel był o piątą część niżej niż na maksimum.",
    "Profit factor": "Ile zarobiono na każdą 1 $ straty. Powyżej 1 = więcej zysków niż strat.",
    "Win rate": "Odsetek transakcji zakończonych na plusie.",
    "Buy & hold": "Kupujesz raz i nic nie robisz. To poprzeczka: bot ma sens tylko, "
                  "jeśli jest lepszy niż zwykłe trzymanie.",
    "Rebalans": "Przywrócenie zaplanowanych proporcji koszyka (np. z powrotem 50/30/20), "
                "gdy ceny je rozjadą.",
    "Drift": "O ile proporcje koszyka odjechały od planu (w punktach procentowych).",
    "CAGR": "Średnioroczne tempo wzrostu — ile procent na rok wychodziłoby średnio.",
    "Zmienność": "Jak mocno wartość skacze w górę i w dół. Niżej = spokojniej.",
    "Kill-switch": "Bezpiecznik: po zbyt dużej stracie w ciągu dnia bot przestaje "
                   "otwierać nowe pozycje.",
    "Pieniądze w grze": "Jaka część konta naprawdę siedzi w rynku. Reszta czeka w gotówce "
                        "i nic nie robi — ani nie zarabia, ani nie traci.",
    "wynik_calosc": "Wynik policzony od wszystkich pieniędzy — także tych, które leżały "
                    "bezczynnie. Dlatego wygląda łagodniej, niż zasługuje sam pomysł bota.",
    "Czas w rynku": "Jak często bot w ogóle miał otwartą pozycję. Niski wynik znaczy, "
                    "że przez większość czasu tylko czekał.",
    "wynik_w_grze": "Ten sam wynik, ale policzony tylko od pieniędzy, które faktycznie grały. "
                    "To uczciwsza ocena samego pomysłu: gdyby bot grał całym kontem, "
                    "wyszłoby mniej więcej tyle. Przybliżenie, nie wyrocznia — a gdy bot "
                    "był w rynku bardzo rzadko, pokazujemy „—”, bo przeliczanie takiej "
                    "resztki na całe konto to już zgadywanie.",
    "Tyle w rynku co bot": "Ktoś, kto włożył w rynek tyle samo pieniędzy co bot i po prostu "
                           "czekał. To sprawiedliwa poprzeczka — porównanie z kimś, kto "
                           "włożył wszystko, chwali bota za samą nieobecność w spadkach.",
}


# ---------- formatting ----------

def money(x: float) -> str:
    return f"{x:,.0f} $"


def money2(x: float) -> str:
    return f"{x:,.2f} $"


def signed_money(x: float) -> str:
    return f"{x:+,.2f} $"


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
    verb = "Kupił" if side == "long" else "Gra na spadek"
    return {
        "symbol": symbol,
        "title": f"{verb} {base} za {money(invested)}",
        "detail": f"teraz {signed_money(pnl)} ({pct:+.1f}%)",
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
        "detail": f"{weight * 100:.0f}% portfela (cel {target * 100:.0f}%)",
        "emoji": "⚖️" if off else "✅",
        "color": MUTED if not off else "#c47f00",
    }


def event_line(record: dict, tz: tzinfo | None = None) -> dict:
    """Turn one alert/trade record into {emoji, time, text} for the timeline."""
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
    text = record.get("message")
    if not text:  # fallback for raw trade rows without a friendly message
        if "exit_reason" in record:
            text = f"{record.get('symbol', '')} zamknięte {EXIT_PL.get(record['exit_reason'], '')}"
        else:
            text = kind or "zdarzenie"
    return {"emoji": emoji, "time": _fmt_time(record.get("timestamp"), tz), "text": text}


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
        return {"ok": False, "emoji": "🔴", "text": "bot jeszcze nie odczytał rynku"}
    try:
        latest_open = datetime.fromisoformat(max(last_candle_ts.values()))
    except ValueError:
        return {"ok": False, "emoji": "🔴", "text": "nieznany czas ostatniego odczytu"}
    bar = timedelta(milliseconds=timeframe_ms)
    closed_at = latest_open + bar          # when that candle actually finalized
    next_at = closed_at + bar              # when the next one is due
    overdue_ms = (now - closed_at).total_seconds() * 1000
    fresh = overdue_ms <= timeframe_ms + 15 * 60_000  # healthy until a full bar is missed
    when = _fmt_time(closed_at, tz)
    if fresh:
        return {"ok": True, "emoji": "🟢",
                "text": f"działa — ostatnia świeca zamknięta {when}, "
                        f"następna około {_fmt_time(next_at, tz)}"}
    return {"ok": False, "emoji": "🔴",
            "text": f"może nie odpowiadać — ostatnia świeca zamknięta {when}"}


# A stalled ticker is the earliest honest sign of trouble, so the panel may not
# wait longer than this before saying so. Five minutes is four missed refreshes:
# short enough to catch a real outage while it is still news, long enough that a
# single slow request does not cry wolf.
CONNECTION_STALE_SECONDS = 300


def _ago(seconds: float) -> str:
    """How long ago, in words that dodge Polish plurals — "3 minuty" vs "5 minut"
    is a rule this line does not need to know."""
    if seconds < 90:
        return "przed chwilą"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min temu"
    return f"{minutes // 60} h {minutes % 60} min temu"


def connection_status(updated_at: str | datetime | None, now: datetime) -> dict:
    """Is the bot actually reaching the exchange *right now*?

    `bot_status` answers a different question — whether a candle is overdue — and
    on 4h bars it stays green for hours after the exchange has gone silent. This
    reads `state.json`'s `updated_at`, which the ticker rewrites every 60 s and
    only ever on a successful call, so it is the sharpest liveness signal we have.

    It exists because the alert journal could not answer this. A dropped
    connection files "brak połączenia z giełdą", but the matching all-clear is
    written by the process that saw the outage — and a container that restarts in
    between starts clean and never writes it. The alarm then hangs there,
    truthful about the past and misleading about the present. A heartbeat cannot
    go stale that way: it either ticked recently or it did not.
    """
    if not updated_at:
        return {"ok": False, "emoji": "📡", "text": "brak kontaktu z giełdą"}
    try:
        ts = updated_at if isinstance(updated_at, datetime) else datetime.fromisoformat(
            str(updated_at))
    except ValueError:
        return {"ok": False, "emoji": "📡", "text": "nieznany czas kontaktu z giełdą"}
    seconds = (now - ts).total_seconds()
    if seconds <= CONNECTION_STALE_SECONDS:
        return {"ok": True, "emoji": "📡",
                "text": f"kontakt z giełdą: {_ago(seconds)}"}
    return {"ok": False, "emoji": "📡",
            "text": f"brak kontaktu z giełdą od {_ago(seconds)} — bot czeka i ponawia"}
