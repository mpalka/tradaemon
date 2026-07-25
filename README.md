# Trademon

Bot scalpingowy na kryptowaluty oparty o ML (LightGBM + triple-barrier labeling),
z backtestem uwzględniającym koszty transakcyjne i trybem **paper trading**
(wirtualne środki, realne ceny z Binance przez CCXT).

> **Ostrzeżenie**: krótkoterminowy trading algorytmiczny jest wysoce ryzykowny —
> prowizje i poślizg zjadają większość zysku, a modele łatwo się przeuczają.
> Domyślny tryb to `paper`. Nie przechodź na `live`, dopóki backtest **i** kilka
> dni paper tradingu nie pokażą dodatniego wyniku po kosztach. To nie jest
> porada inwestycyjna.

## Szybki start (lokalnie)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 1. Pobierz historię 1m (Binance, publiczne API, bez klucza)
.venv/bin/python scripts/download_data.py --days 180

# 2. Wytrenuj model (walk-forward, raport AUC per fold)
.venv/bin/python scripts/train.py

# 3. Backtest po kosztach na ostatnich 14 dniach
.venv/bin/python scripts/backtest.py

# 4. Paper trading na żywych cenach
.venv/bin/python -m trademon.engine

# 5. Dashboard (osobny terminal): http://localhost:8501
.venv/bin/streamlit run src/trademon/dashboard/app.py
```

macOS: LightGBM wymaga `brew install libomp` (bez niego kod automatycznie
używa sklearn `HistGradientBoostingClassifier`).

## Docker

```bash
docker compose up --build
```

Uruchamia bota (paper), dashboard na `localhost:8501` oraz `refresher`
(cotygodniowe utrzymanie). Dane, model i stan runtime są montowane z katalogów
`./data`, `./models`, `./runtime`.

## Dashboard (localhost:8501)

Zakładki: **Przegląd** (kapitał + metryki ryzyka + krzywa vs buy & hold),
**Analityka** (per para, rozkład wyników, powody wyjścia), **Model** (dlaczego
bot (nie) handluje — prawdopodobieństwa vs próg), **Warianty** (porównanie A/B
na żywo), **Eksperymenty** (dziennik backtestów), **Zdrowie** (świeżość danych,
kill-switch, alerty, status refreshera).

## Utrzymanie (automatyczne)

Serwis `refresher` co tydzień: pobiera dane → trenuje kandydata bez ostatnich
`validation_days` → backtest OOS → **bramka** (promuje tylko model bijący
buy & hold) → podmienia model. Bot łapie nowy model przez hot-reload bez
restartu. Ręcznie: `python scripts/refresh.py`.

## Konfiguracja

Wszystko w [config/config.yaml](config/config.yaml): pary, progi strategii
(TP/SL w ATR, horyzont, próg prawdopodobieństwa), koszty (prowizja, poślizg)
oraz limity ryzyka (wielkość pozycji, max pozycji, dzienny kill-switch, próg
alertu obsunięcia).

**Warianty A/B na żywo**: sekcja `variants:` uruchamia kilka konfiguracji
równolegle na tych samych świecach (każda z własnym portfelem w `runtime/<name>/`),
porównywanych w zakładce Warianty. Brak sekcji = jedna księga `default`.

**Alerty na zewnątrz** (opcjonalne): ustaw `ALERT_WEBHOOK_URL` w `.env`
(Discord/Slack). Bez tego alerty są tylko lokalne (dziennik + panel).

## Moduł 2: zarządca portfela (wolne inwestowanie)

Drugi, niezależny moduł obok krypto-scalpera — **rebalanser, nie predyktor**. Jego
wartość to **dyscyplina, koszty i dywersyfikacja**, nie „alfa". Trzyma zadany koszyk
ETF-ów (domyślnie SPY/TLT/GLD) i przywraca docelowe proporcje okresowo lub gdy waga
odjedzie ponad próg. Paper only; dane dzienne z Yahoo Finance (za darmo, bez klucza).

```bash
# Backtest po kosztach vs „kup i trzymaj" (pobiera dane z Yahoo)
.venv/bin/python scripts/portfolio_backtest.py --years 10

# Paper: jeden dzień (--once), pętla dzienna (bez flagi), albo pełna historia
.venv/bin/python -m trademon.portfolio --backfill   # odtworzenie realnej historii
.venv/bin/python -m trademon.portfolio              # pętla dzienna forward
```

Konfiguracja w [config/portfolio.yaml](config/portfolio.yaml): koszyk i wagi, kadencja
i próg rebalansu, opcjonalny **filtr trendu** (trzymaj aktywo tylko powyżej średniej
N-dniowej — premia za ryzyko, nie darmowy obiad). W dashboardzie przełącznik u góry:
**Krypto-scalper · Zarządca portfela**.

> Uczciwie: rebalansowanie zwykle **obniża** zwrot w silnej hossie akcji (przycina
> zwycięzców), za to ogranicza zmienność i obsunięcia. To narzędzie edukacyjne, nie
> porada inwestycyjna — realne środki i konto maklerskie to Twoja osobna decyzja.

## Panel dla początkującego

Dashboard otwiera się na ekranie bez żargonu: **„Ile masz"** (wartość + zmiana),
**status bota** (🟢/🔴), wykres **„Jak to szło"** z linią „kup i trzymaj", karty
**„co bot teraz trzyma"** po ludzku i **dziennik zdarzeń**. Wskaźniki techniczne
(Sharpe, drawdown, profit factor) z objaśnieniami siedzą pod **„Szczegóły dla
dociekliwych"**. Którą księgę A/B pokazać jako „Twój portfel" ustawia `primary_variant`
w [config/config.yaml](config/config.yaml).

## Tryb live (świadoma decyzja)

1. Zweryfikuj wyniki paper tradingu (dashboard + `runtime/trades.jsonl`).
2. Utwórz na giełdzie klucz API **tylko z uprawnieniem trade** (bez wypłat),
   wpisz do `.env` (wzór: `.env.example`).
3. Zmień `mode: live` w `config/config.yaml` i zrestartuj bota.

## Architektura

```
dane (CCXT/Parquet) -> cechy -> etykiety triple-barrier -> LightGBM (walk-forward)
                                                              |
backtest (koszty: prowizja+poślizg) <--- wspólna symulacja fill'ów ---> silnik live/paper
                                                              |
                                       runtime/ (state.json, trades.jsonl) -> dashboard
```

Kluczowa własność: backtester, paper trading i tryb live używają **tej samej**
logiki wejść/wyjść i tych samych symulacji kosztów (`trademon/execution/fills.py`),
więc paper trading testuje dokładnie ten kod, który pójdzie na produkcję.

## Testy

```bash
.venv/bin/pytest
```
