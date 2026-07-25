"""Plain-Polish translation layer for the beginner dashboard.

Turns raw engine data (signal reasons, alert kinds, exit reasons, positions) into
sentences a first-time investor understands. Shared by the crypto and portfolio
views so the wording stays consistent. Pure functions — no Streamlit here.
"""

from __future__ import annotations

from datetime import datetime

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
}


# ---------- formatting ----------

def money(x: float) -> str:
    return f"{x:,.0f} $"


def money2(x: float) -> str:
    return f"{x:,.2f} $"


def signed_money(x: float) -> str:
    return f"{x:+,.2f} $"


def _fmt_time(ts: str | None) -> str:
    if not ts:
        return "?"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%d.%m %H:%M")
    except ValueError:
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


def event_line(record: dict) -> dict:
    """Turn one alert/trade record into {emoji, time, text} for the timeline."""
    kind = record.get("kind", "")
    emoji = ALERT_EMOJI.get(kind, "•")
    if kind == "trade_close" and "pnl" in record:
        emoji = "💰" if float(record.get("pnl", 0)) >= 0 else "🔻"
    text = record.get("message")
    if not text:  # fallback for raw trade rows without a friendly message
        if "exit_reason" in record:
            text = f"{record.get('symbol', '')} zamknięte {EXIT_PL.get(record['exit_reason'], '')}"
        else:
            text = kind or "zdarzenie"
    return {"emoji": emoji, "time": _fmt_time(record.get("timestamp")), "text": text}


def bot_status(last_candle_ts: dict, timeframe_ms: int, now: datetime) -> dict:
    """🟢/🔴 status line from the freshest heartbeat across pairs."""
    if not last_candle_ts:
        return {"ok": False, "emoji": "🔴", "text": "bot jeszcze nie odczytał rynku"}
    latest = max(last_candle_ts.values())
    try:
        age_ms = (now - datetime.fromisoformat(latest)).total_seconds() * 1000
    except ValueError:
        return {"ok": False, "emoji": "🔴", "text": "nieznany czas ostatniego odczytu"}
    fresh = age_ms <= timeframe_ms * 1.5 + 15 * 60_000
    when = _fmt_time(latest)
    if fresh:
        return {"ok": True, "emoji": "🟢", "text": f"działa — ostatni odczyt rynku {when}"}
    return {"ok": False, "emoji": "🔴", "text": f"nie odpowiada — ostatni odczyt {when}"}
