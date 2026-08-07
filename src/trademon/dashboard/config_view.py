"""Changing the bot's parameters from the browser.

Edits go to `config/config.overrides.yaml`, never to `config.yaml` — the baseline keeps
its research commentary, and "restore default" is a deleted key rather than a retyped
number. Every write is validated through pydantic first (config_store.apply_changes) and
journalled afterwards, so an invalid value cannot reach a running engine and a valid one
leaves a trace on the equity chart.

Two speeds of change, made explicit in the UI rather than left as a footgun:

* fields the engine re-reads each candle take effect on the next bar (⚡)
* fields read once at startup need the engine to come back (🔄) — the screen writes a
  flag, the engine persists its books and exits, and Docker restarts it
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from trademon import config_store
from trademon.config import Config, config_path
from trademon.dashboard import auth, humanize, layout
from trademon.data.storage import TIMEFRAME_MS
from trademon.portfolio.config import PortfolioConfig
from trademon.portfolio.config import _find_config_path as _portfolio_config_path

HOT = "⚡"
RESTART = "🔄"

# Booleans shown as a Polish on/off selectbox rather than a bare True/False.
BOOL_CHOICES = ("trend.enabled", "strategy.timeout_rollover")


@dataclass
class Field:
    path: str
    label: str
    kind: str                      # float | int | choice | symbols | text
    help: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    fmt: str | None = None
    choices: list[str] | None = None

    @property
    def hot(self) -> bool:
        return self.path in config_store.HOT_FIELDS

    @property
    def marker(self) -> str:
        return HOT if self.hot else RESTART


CRYPTO_SECTIONS: dict[str, list[Field]] = {
    "Strategia": [
        Field("strategy.prob_threshold", "Próg pewności modelu", "float",
              "Minimalne prawdopodobieństwo, przy którym bot otwiera pozycję. "
              "Niżej = więcej transakcji i więcej prowizji.",
              min=0.0, max=1.0, step=0.01, fmt="%.2f"),
        Field("strategy.tp_atr_mult", "Take-profit (× ATR)", "float",
              "Jak daleko od ceny wejścia ustawiany jest cel zysku, w jednostkach "
              "zmienności (ATR).", min=0.1, max=10.0, step=0.1, fmt="%.1f"),
        Field("strategy.sl_atr_mult", "Stop-loss (× ATR)", "float",
              "Jak daleko ustawiany jest bezpiecznik. Mniej = szybciej ucina straty, "
              "ale częściej wyrzuca z dobrej pozycji.",
              min=0.1, max=10.0, step=0.1, fmt="%.1f"),
        Field("strategy.horizon_bars", "Maksymalny czas trzymania (świece)", "int",
              "Po tylu świecach pozycja zamyka się niezależnie od wyniku.",
              min=1, max=500, step=1),
        Field("strategy.timeout_rollover", "Przedłużanie po terminie", "choice",
              "Gdy mija maksymalny czas trzymania, a model wciąż daje sygnał powyżej "
              "progu, bot przedłuża pozycję (nowe widełki i termin) zamiast zamykać "
              "i zaraz otwierać ją ponownie za podwójną prowizję.",
              choices=["wyłączony", "włączony"]),
        Field("strategy.atr_period", "Okres ATR", "int",
              "Ile świec wstecz liczy się zmienność.", min=2, max=200, step=1),
        Field("strategy.direction", "Kierunek", "choice",
              "long = tylko zakłady na wzrost (zgodne ze spotem). long_short = także "
              "zakłady na spadek; realne shorty wymagają konta futures.",
              choices=["long", "long_short"]),
        Field("strategy.warmup_bars", "Rozgrzewka (świece)", "int",
              "Ile historii bot musi zebrać, zanim policzy cechy. Zmiana wymaga "
              "restartu, bo od tego zależy rozmiar bufora świec.",
              min=50, max=2000, step=10),
    ],
    "Ryzyko": [
        Field("risk.position_pct", "Wielkość pozycji (część kapitału)", "float",
              "Jaka część konta idzie w jedną pozycję. 0,10 = 10%.",
              min=0.01, max=1.0, step=0.01, fmt="%.2f"),
        Field("risk.max_open_positions", "Maksimum otwartych pozycji", "int",
              "Razem z powyższym wyznacza maksymalną ekspozycję. Pary krypto są mocno "
              "skorelowane, więc otwarte pozycje zwykle zachowują się podobnie.",
              min=1, max=20, step=1),
        Field("risk.daily_loss_limit_pct", "Dzienny limit straty", "float",
              humanize.GLOSSARY["Kill-switch"], min=0.005, max=0.5, step=0.005, fmt="%.3f"),
        Field("risk.drawdown_alert_pct", "Próg alertu o obsunięciu", "float",
              "Przy jakim spadku od szczytu kapitału panel ma ostrzegać.",
              min=0.01, max=0.9, step=0.01, fmt="%.2f"),
    ],
    "Koszty": [
        Field("costs.taker_fee", "Prowizja taker", "float",
              "Prowizja od zleceń rynkowych. Binance spot domyślnie 0,001 = 0,1%.",
              min=0.0, max=0.01, step=0.0001, fmt="%.4f"),
        Field("costs.maker_fee", "Prowizja maker", "float",
              "Prowizja od zleceń limit czekających w księdze.",
              min=0.0, max=0.01, step=0.0001, fmt="%.4f"),
        Field("costs.slippage_bps", "Poślizg (punkty bazowe)", "float",
              "Zakładane niekorzystne odchylenie ceny wykonania. 2 bps = 0,02%.",
              min=0.0, max=50.0, step=0.5, fmt="%.1f"),
    ],
    "Rynek i kapitał": [
        Field("exchange.timeframe", "Interwał świecy", "choice",
              "Co ile bot podejmuje decyzję. Zmiana wymaga restartu i unieważnia "
              "model wytrenowany na innym interwale.", choices=list(TIMEFRAME_MS)),
        Field("exchange.symbols", "Pary", "symbols",
              "Lista par oddzielona przecinkami. Model kosztów jest uczciwy dla par "
              "o dużej płynności; cieńsze będą handlować gorzej niż backtest sugeruje."),
        Field("paper.initial_capital", "Kapitał startowy (paper)", "float",
              "Dotyczy nowych ksiąg. Istniejące księgi trzymają swój stan w state.json "
              "i nie zmienią salda po tej edycji.", min=10.0, max=1_000_000.0, step=100.0,
              fmt="%.2f"),
        Field("primary_variant", "Księga na ekranie głównym", "choice",
              "Który wariant A/B panel nazywa „Twoim portfelem\"."),
    ],
    "Trenowanie": [
        Field("model.train_window_days", "Okno treningowe (dni)", "int",
              "Ile historii trafia do treningu. Ustawia też okno cotygodniowego "
              "pobierania danych, więc mała wartość po cichu ogranicza zbierane dane.",
              min=30, max=4000, step=10),
        Field("model.validation_days", "Okno walidacji (dni)", "int",
              "Ile dni z końca każdego foldu służy do oceny.", min=7, max=365, step=1),
        Field("model.n_folds", "Liczba foldów", "int",
              "Ile kroków walidacji kroczącej (walk-forward).", min=2, max=20, step=1),
    ],
}

PORTFOLIO_SECTIONS: dict[str, list[Field]] = {
    "Portfel": [
        Field("initial_capital", "Kapitał startowy", "float",
              "Dotyczy nowej księgi portfela.", min=100.0, max=10_000_000.0, step=100.0,
              fmt="%.2f"),
        Field("rebalance.cadence_days", "Rebalans co (dni)", "int",
              "Najrzadszy dopuszczalny rytm przywracania proporcji.",
              min=1, max=730, step=1),
        Field("rebalance.drift_threshold_pct", "Próg driftu (pkt proc.)", "float",
              humanize.GLOSSARY["Drift"], min=0.5, max=50.0, step=0.5, fmt="%.1f"),
        Field("trend.enabled", "Filtr trendu", "choice",
              "Gdy włączony, aktywo poniżej swojej średniej trafia do aktywa "
              "bezpiecznego. To premia za ryzyko, nie darmowy obiad.",
              choices=["wyłączony", "włączony"]),
        Field("trend.ma_days", "Średnia dla filtru trendu (dni)", "int",
              "Klasycznie 200 sesji.", min=20, max=500, step=10),
    ],
}


# ---------- widgets ----------

def _widget(f: Field, current: Any, key: str) -> Any:
    label = f"{f.marker} {f.label}"
    if f.kind == "float":
        return st.number_input(label, value=float(current), min_value=f.min,
                               max_value=f.max, step=f.step, format=f.fmt,
                               help=f.help, key=key)
    if f.kind == "int":
        return st.number_input(label, value=int(current), min_value=int(f.min),
                               max_value=int(f.max), step=int(f.step),
                               help=f.help, key=key)
    if f.kind == "choice":
        choices = f.choices or []
        if f.path in BOOL_CHOICES:
            current = "włączony" if current else "wyłączony"
        idx = choices.index(current) if current in choices else 0
        return st.selectbox(label, choices, index=idx, help=f.help, key=key)
    if f.kind == "symbols":
        text = ", ".join(current or [])
        return st.text_area(label, value=text, help=f.help, key=key, height=80)
    return st.text_input(label, value=str(current or ""), help=f.help, key=key)


def _parse(f: Field, raw: Any) -> Any:
    if f.kind == "symbols":
        return [s.strip().upper() for s in str(raw).replace("\n", ",").split(",") if s.strip()]
    if f.kind == "int":
        return int(raw)
    if f.kind == "float":
        return float(raw)
    if f.path in BOOL_CHOICES:
        return raw == "włączony"
    return raw


# ---------- one editable section ----------

def effective_values(effective: dict, model_cls: type) -> dict:
    """Effective config *including* the defaults the YAML leaves unsaid.

    config.yaml spells out only the values worth commenting on — `strategy.direction`
    and `risk.drawdown_alert_pct`, for instance, live purely in the pydantic model.
    Reading widget values off the raw dict would hand `None` to a number input, so the
    form reads them off a validated model instead.
    """
    try:
        return model_cls.model_validate(effective).model_dump(mode="json")
    except ValidationError:
        return effective


def _render_section(
    title: str, fields: list[Field], cfg_path: Path, runtime_dir: Path,
    effective: dict, overrides: dict, model_cls: type, scope: str,
) -> None:
    overridden = [f.path for f in fields if config_store.get_path(overrides, f.path) is not None]
    header = f"{title} ({len(overridden)} zmienionych)" if overridden else title

    defaults_filled = effective_values(effective, model_cls)
    with st.expander(header, expanded=bool(overridden)):
        with st.form(f"form_{scope}_{title}"):
            values: dict[str, Any] = {}
            for f in fields:
                current = config_store.get_path(defaults_filled, f.path)
                if f.path == "primary_variant":
                    f.choices = [v.get("name") for v in effective.get("variants", [])] or ["—"]
                values[f.path] = _widget(f, current, key=f"{scope}.{f.path}")
            saved = st.form_submit_button("Zapisz", type="primary")

        if saved:
            changes = {}
            for f in fields:
                try:
                    changes[f.path] = _parse(f, values[f.path])
                except (TypeError, ValueError):
                    st.error(f"Nie rozumiem wartości pola „{f.label}\".")
                    return
            _apply(cfg_path, runtime_dir, changes, model_cls, scope)

        if overridden and st.button(f"Przywróć domyślne w „{title}\"",
                                    key=f"reset_{scope}_{title}"):
            _apply(cfg_path, runtime_dir, dict.fromkeys(overridden), model_cls, scope)


def _apply(cfg_path: Path, runtime_dir: Path, changes: dict,
           model_cls: type, scope: str) -> None:
    if not auth.can_write():
        st.error("Brak uprawnień do zmiany ustawień.")
        return
    try:
        report = config_store.apply_changes(
            cfg_path, runtime_dir, changes, actor=auth.current_user(),
            model_cls=model_cls, scope=scope)
    except config_store.ConfigWriteError as exc:
        st.error(str(exc))
        return

    if not report.changed:
        st.info("Nic się nie zmieniło.")
        return
    lines = "\n".join(f"- `{k}`: {old} → **{new}**" for k, (old, new) in report.applied.items())
    st.success(f"Zapisano:\n{lines}")
    if report.needs_restart:
        st.session_state["pending_restart"] = report.needs_restart
    else:
        st.info("⚡ Wchodzi w życie przy najbliższej świecy — bez restartu.")
    st.rerun()


# ---------- restart handshake ----------

@st.dialog("Zrestartować silnik?")
def _restart_dialog(runtime_dir: Path, fields: list[str]) -> None:
    st.write("Te ustawienia silnik czyta tylko przy starcie:")
    st.markdown("\n".join(f"- `{f}`" for f in fields))
    st.caption("Silnik zapisze stan wszystkich ksiąg i zakończy się czysto. Kontener "
               "podniesie się sam (`restart: unless-stopped`), a otwarte pozycje i "
               "gotówka wrócą ze `state.json`. Poza Dockerem trzeba uruchomić go ręcznie.")
    c1, c2 = st.columns(2)
    if c1.button("Zrestartuj", type="primary", width="stretch"):
        config_store.request_restart(runtime_dir, actor=auth.current_user())
        st.session_state.pop("pending_restart", None)
        st.session_state["restart_sent"] = True
        st.rerun()
    if c2.button("Później", width="stretch"):
        st.session_state.pop("pending_restart", None)
        st.rerun()


# ---------- history ----------

def _render_history(runtime_dir: Path) -> None:
    rows = config_store.load_history(runtime_dir, limit=100)
    st.subheader("Historia zmian")
    if not rows:
        st.caption("Jeszcze nic nie zmieniano — bot działa na wartościach z config.yaml.")
        return
    st.caption("Te momenty są też zaznaczone przerywaną kreską na wykresie kapitału, "
               "żeby było widać, od kiedy wynik dotyczy innych ustawień.")
    df = pd.DataFrame(rows)
    df["czas"] = pd.to_datetime(df["timestamp"]).dt.strftime("%d.%m.%Y %H:%M")
    view = df[["czas", "field", "old", "new", "actor"]].rename(
        columns={"field": "pole", "old": "było", "new": "jest", "actor": "kto"})
    if layout.is_mobile():
        layout.cards(view, "pole", ["czas", "było", "jest"])
    else:
        st.dataframe(view, width="stretch", hide_index=True)


# ---------- entry ----------

def render() -> None:
    st.caption("Zmiany trafiają do `config.overrides.yaml`. Plik `config.yaml` zostaje "
               "nietknięty jako udokumentowany wzorzec — „przywróć domyślne\" po prostu "
               "usuwa nadpisanie.")
    st.markdown(f"{HOT} — wchodzi przy najbliższej świecy · {RESTART} — wymaga restartu silnika")
    layout.layout_switch()

    if st.session_state.pop("restart_sent", False):
        st.success("Wysłano prośbę o restart. Silnik zejdzie w ciągu ~10 sekund "
                   "i wróci z nowymi ustawieniami.")

    cfg_path = config_path()
    runtime_dir = _runtime_dir()

    if pending := st.session_state.get("pending_restart"):
        st.warning("Zapisano ustawienia, które silnik czyta tylko przy starcie.")
        if st.button("🔄 Zrestartuj silnik", type="primary"):
            _restart_dialog(runtime_dir, pending)

    scope = st.segmented_control("Moduł", ["Krypto-scalper", "Zarządca portfela"],
                                 default="Krypto-scalper",
                                 label_visibility="collapsed") or "Krypto-scalper"

    if scope == "Krypto-scalper":
        effective = config_store.effective_config(cfg_path)
        overrides = config_store.load_overrides(cfg_path)
        for title, fields in CRYPTO_SECTIONS.items():
            _render_section(title, fields, cfg_path, runtime_dir, effective, overrides,
                            Config, "crypto")
        _render_variants(cfg_path, runtime_dir, effective, overrides)
    else:
        p_path = _portfolio_config_path(None)
        effective = config_store.effective_config(p_path)
        overrides = config_store.load_overrides(p_path)
        st.caption("Pętla portfela jest dzienna, więc każda zmiana i tak wchodzi przy "
                   "najbliższym przebiegu — nie ma tu hot-reloadu.")
        for title, fields in PORTFOLIO_SECTIONS.items():
            _render_section(title, fields, p_path, runtime_dir, effective, overrides,
                            PortfolioConfig, "portfolio")

    st.divider()
    _render_history(runtime_dir)


def _render_variants(cfg_path: Path, runtime_dir: Path,
                     effective: dict, overrides: dict) -> None:
    """A/B books, edited as a grid. Adding or removing one changes which books exist,
    so this is restart-only by nature."""
    with st.expander(f"{RESTART} Warianty A/B"):
        st.caption("Każdy wiersz to osobna księga handlująca tymi samymi świecami. "
                   "Puste pole = wartość z sekcji wyżej. Zmiana listy wymaga restartu.")
        variants = effective.get("variants", []) or []
        cols = ["name", "prob_threshold", "tp_atr_mult", "sl_atr_mult",
                "horizon_bars", "direction", "timeout_rollover",
                "position_pct", "max_open_positions"]
        df = pd.DataFrame(variants)
        for c in cols:
            if c not in df:
                df[c] = None
        edited = st.data_editor(df[cols], num_rows="dynamic", width="stretch",
                                hide_index=True, key="variants_editor")
        if st.button("Zapisz warianty", key="save_variants"):
            rows = [
                {k: v for k, v in rec.items() if v is not None and v != ""}
                for rec in edited.to_dict("records")
                if str(rec.get("name") or "").strip()
            ]
            _apply(cfg_path, runtime_dir, {"variants": rows}, Config, "crypto")
        if config_store.get_path(overrides, "variants") is not None and st.button(
                "Przywróć domyślne warianty", key="reset_variants"):
            _apply(cfg_path, runtime_dir, {"variants": None}, Config, "crypto")


def _runtime_dir() -> Path:
    from trademon.config import load_config
    return load_config().paths.runtime_dir
