# Tradaemon

Narzędzie edukacyjne: **dwa równoległe moduły** do zabawy algorytmem i dyscypliną.

1. **Moduł 1 — Krypto-scalper** (LightGBM, 4h, 10 par USDT, paper trading)
   Krótkoterminowy trading oparty o machine learning z triple-barrier labeling,
   walk-forward validation i backtestem uwzględniającym koszty. Backtest wykazuje
   przewagę ~0 po kosztach — moduł pełni rolę **laboratorium edukacyjnego**.

2. **Moduł 2 — Zarządca portfela** (rebalanser ETF-ów, paper trading)
   Systematyczne przywracanie docelowych proporcji koszyka SPY/TLT/GLD,
   z opcjonalnym filtrem trendu. Backtest na 10 latach pokazuje, że rebalansowanie
   przycina zwycięzców w hossie — jego wartość to dyscyplina i redukcja ryzyka, nie alpha.

> **Ostrzeżenie**: Oba moduły to **paper trading** (wirtualne środki).
> Decyzja o realnych środkach, gitHub kluczach API czy live tradingu to Twoja
> osobna, świadoma decyzja. To nie jest porada inwestycyjna.

## Szybki start (lokalnie)

### Moduł 1: Krypto-scalper

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 1. Pobierz historię 1m (Binance, publiczne API, bez klucza)
.venv/bin/python scripts/download_data.py --days 180

# 2. Wytrenuj model (walk-forward, raport AUC per fold)
.venv/bin/python scripts/train.py

# 3. Backtest po kosztach
.venv/bin/python scripts/backtest.py

# 4. Paper trading (jeden dzień lub pętla)
.venv/bin/python -m trademon.engine --once        # jeden dzień
.venv/bin/python -m trademon.engine                # pętla 4h (śpi między świecami)
```

### Moduł 2: Zarządca portfela

```bash
# Backtest vs "kup i trzymaj" na 10 latach (pobiera z Yahoo)
.venv/bin/python scripts/portfolio_backtest.py --years 10

# Paper: jeden dzień, pętla dzienna, lub replay historii
.venv/bin/python -m trademon.portfolio --once     # jeden dzień
.venv/bin/python -m trademon.portfolio --backfill # pełna historia (5452 dni)
.venv/bin/python -m trademon.portfolio             # pętla dzienna
```

### Dashboard (oba moduły)

```bash
# Terminal osobny: http://localhost:8501
.venv/bin/streamlit run src/trademon/dashboard/app.py
```

**macOS**: LightGBM wymaga `brew install libomp` (bez niego kod automatycznie
używa sklearn `HistGradientBoostingClassifier`).

## Docker (OrbStack / Docker Desktop)

```bash
docker compose up --build
```

Uruchamia **cztery serwisy**:

| Serwis | Rola |
|--------|------|
| `bot` | Moduł 1: krypto-scalper, 3 warianty A/B na 10 parach USDT |
| `dashboard` | Panel na `localhost:8501` (oba moduły, UI dla początkującego) |
| `portfolio` | Moduł 2: zarządca portfela, rebalancing ETF-ów |
| `refresher` | Cotygodniowe trenowanie (bramka bezpieczeństwa: promuje tylko + wynik) |

Dane, modele i stan runtime montowane z `./data`, `./models`, `./runtime`.
Każdy serwis ma własny dziennik (logs): `docker compose logs -f bot` itp.

## Dashboard (localhost:8501)

### Ekran dla początkującego (domyślny widok)

Bez żargonu — wszystko po polsku:

- **„Ile masz"** — wartość portfela + zmiana (🟢/🔴)
- **Status bota** — 🟢 działa / 🔴 czeka (ostatni odczyt rynku)
- **„Jak to szło"** — krzywa kapitału vs szara linia „kup i trzymaj"; przełącznik 7d / 30d / całość
- **„Co bot trzyma"** — otwarte pozycje jako zdania (np. „kupił ETH za 100 $ — teraz +2 $")
- **„Dziennik zdarzeń"** — oś czasu z ikonami (kupił, sprzedał, limit strat)
- **„Szczegóły dla dociekliwych"** (zwinięte) — siedem zakładek technicznych z objaśnieniami

### Zakładki techniczne (pod expander)

- **Przegląd** — metryki (Sharpe, drawdown, win-rate), benchmark
- **Analityka** — per para, rozkład wyników, powody wyjścia
- **Model** — Why nie handluje: prawdopodobieństwa vs próg
- **Warianty** — porównanie A/B trei ksiąg live
- **Eksperymenty** — dziennik backtestów, eksport raportów
- **Zdrowie** — świeżość danych, kill-switch, alerty, status refreshera
- **(Portfel)** — gdy wybrany moduł 2: alokacja, rebalanse, drift wag

### Przełącznik modułu (u góry)

**Krypto-scalper · Zarządca portfela** — zmienia ekran na drugi moduł.

## Utrzymanie (automatyczne — Moduł 1)

Serwis `refresher` co tydzień:

1. Pobiera świeże dane (1m z Binance)
2. Trenuje kandydata bez ostatnich `validation_days` (validation window)
3. Backtest OOS na validation_days
4. **Bramka** (gate): promuje model TYLKO jeśli:
   - Nie katastrofa (PnL < -10%)
   - Bije buy & hold (porównanie na tych samych 60 dniach)
5. Podmienia model, bot łapie go przez hot-reload bez restartu

Ręcznie: `python scripts/refresh.py` (exit: 0=promocja, 2=bramka odrzuca, 1=błąd).

**Moduł 2** nie ma automatycznego trenowania (to rebalanser, nie prognosta).

## Konfiguracja

### Moduł 1: Krypto-scalper

[config/config.yaml](config/config.yaml):

- `pairs` — lista par USDT (domyślnie 10 najpłynniejszych)
- `strategy` — timeframe (4h), TP/SL w ATR, horyzont, próg prawdopodobieństwa
- `costs` — prowizja, poślizg na każdym fillu
- `risk` — wielkość pozycji, max pozycji otwartych, dzienny kill-switch, próg alertu DD
- `variants` — A/B: kilka wariantów testuje się równolegle na tych samych świecach,
  każdy z własnym `runtime/<name>/`, porównywane w zakładce Warianty. Brak = jedna księga.
- `primary_variant` — której wariantu pokazać jako „Twój portfel" na głównym ekranie

**Alerty**: opcjonalny `ALERT_WEBHOOK_URL` w `.env` (Discord/Slack). Domyślnie: dziennik + panel.

### Moduł 2: Zarządca portfela

[config/portfolio.yaml](config/portfolio.yaml):

- `assets` — koszyk ETF-ów z wagami (domyślnie SPY 50% / TLT 30% / GLD 20%)
- `rebalance` — cadence (dni) i próg driftu (%)
- `trend` — filtr: czy trzymać aktywo tylko powyżej średniej (edukacyjny — zmniejsza zwrot w hossie)
- `costs` — TER roczny (drag), prowizja transakcji
- `initial_capital` — wirtualny kapitał (domyślnie 10000 $)

## Moduł 2: Zarządca portfela (wolne inwestowanie)

Drugi, niezależny moduł — **rebalanser, nie prognosta**. Wartość = dyscyplina + redukcja
ryzyka, nie „alfa". Paper only; dane dzienne z **Yahoo Finance** (za darmo, bez klucza).

### Backtest

```bash
python scripts/portfolio_backtest.py --years 10
```

Wynik na 10 latach (2016–2026) **SPY/TLT/GLD koszyka domyślnego** (50%/30%/20%):

| Metryka | Strategia | Benchmark (kup&hold) | Różnica |
|---------|-----------|---------------------|---------|
| Zwrot | +113,9% | +147,5% | –33,6 pkt ❌ |
| CAGR | 7,94% | 10,38% | –2,44 ppt |
| Sharpe | 0,77 | 0,69 | +0,08 |
| Max DD | –24,9% | –34,5% | +9,6 ppt ✓ |

**Lekcja**: rebalansowanie przycina zwycięzców w hossie akcji (dzieje się co kwartał),
ale zmniejsza obsunięcia. Edukacyjny tool, nie strategia do bogacenia się.

### Paper trading

```bash
python -m trademon.portfolio --backfill   # replay pełnej historii (5452 dni)
python -m trademon.portfolio --once       # jeden dzień
python -m trademon.portfolio              # pętla dzienna (śpi 6h między checks)
```

Dashboard automatycznie odkrywa księgi z `runtime/portfolio/*/state.json` i pokazuje:
- Kapitał, zmianę, drift wag od celu
- Wykres vs benchmark
- Dziennik rebalansów (ikony + opisy zdarzeń)
- Panel zdrowia (świeżość danych, ostatni rebalans)


## Tryb live (Moduł 1 — świadoma decyzja)

> **Moduł 2 (portfel) to paper-only** — rebalancing realnym pieniędzem to
> osobna decyzja (konto maklerskie, podatki, transfer środków).

Jeśli zdecydujesz się na live trading w Module 1:

1. **Nie rób tego** — backtest wykazuje przewagę ~0 po kosztach; paper trading
   może pokazać lepiej przez shuffle lub szczęście.
2. Jeśli naprawdę chcesz: zweryfikuj paper trading (kilka dni, 10+ transakcji
   bez dużych strat).
3. Utwórz klucz API na Binance **z uprawnieniem TRADE ONLY** (bez withdrawals).
4. Wpisz do `.env` (wzór: [.env.example](.env.example)).
5. Zmień `mode: live` w `config/config.yaml`.
6. Testuj z małą pozycją — zawsze możliwe są błędy, glitche API, edge casey.

## Architektura

### Moduł 1 — Krypto-scalper

```
CCXT (1m, publiczne API)
    ↓ Parquet (ohlcv_binance_*.parquet)
    ↓
Cechy (engineering.py) + Triple-barrier labeling
    ↓
Walk-forward LightGBM ← Backtest (rekonsyliacja z kosztami)
    ↓
Silnik (loop.py: feedy > sygnały > orders > executors)
    ├─→ Paper Executor (simulation)
    └─→ Live Executor (CCXT) [opcjonalnie]
        ↓
Runtime (state.json, trades.jsonl, equity.jsonl, alerts.jsonl)
        ↓
Dashboard (panel dla początkującego + techniczne)
```

**Kluczowe**: backtester i silnik paper/live dzielą `fills.py` (tę samą symulację
kosztów), więc paper testing to dokładnie ten kod, który pójdzie na produkcję.

### Moduł 2 — Zarządca portfela

```
Yahoo Finance API (daily, bezpłatnie)
    ↓ Parquet (ohlcv_yahoo_SPY_1d.parquet, itp.)
    ↓
Allocator (effective_weights, drift, rebalance_orders)
    ↓
Backtest (daily loop, benchmark = buy&hold raz)
        ↓
Paper Executor (rebalancing, simulate costs)
    ↓
Runtime (state.json, trades.jsonl, equity.jsonl, alerts.jsonl)
    ↓
Dashboard (portfel view: alokacja, rebalanse, zdrowie)
```

**Obie moduły**: wspólny `RuntimeStore` (persystencja, dzienniki), wspólny model
kosztów, wspólne metryki (Sharpe annualizacja), wspólny dashboard.

## Badania ([scripts/research](scripts/research))

Osobny zestaw skryptów do odpowiadania na pytanie „czy ta strategia w ogóle ma
przewagę". Nie dotykają produkcji — liczą i drukują raport.

Trzy zasady, na których stoją (bo bez nich liczby kłamią):

1. **Model nigdy nie widzi danych, na których go sprawdzamy.** Historia jest
   cięta na rozłączne 60-dniowe okna; dla każdego okna model uczy się od nowa
   wyłącznie na świecach sprzed niego.
2. **Ten sam model kosztów co produkcja** — backtest idzie przez
   `trademon.backtest.runner`, który dzieli `execution/fills.py` z silnikiem.
3. **Naiwne punkty odniesienia.** „Zawsze graj na wzrost", „zawsze na spadek",
   „losowo". Strategia, która ich nie bije, niczego nie udowodniła — a przy
   porównaniu tylko do „kup i trzymaj" łatwo się oszukać (w bessie każda
   strategia umiejąca grać na spadek wygląda genialnie).

```bash
# Ile z przewagi zjadają opłaty? Ten sam model, różne cenniki giełdy.
.venv/bin/python scripts/research/fee_grid.py --windows 30

# Czy poziomy zysku/straty są dobrze ustawione? Przegląd kombinacji TP/SL.
.venv/bin/python scripts/research/rr_grid.py --windows 30 --every 3

# Czy warto wybierać transakcje po opłacalności, a nie tylko po pewności modelu?
.venv/bin/python scripts/research/ev_gate.py --windows 30
```

Każdy skrypt dzieli wynik według tego, **co robił rynek** (wzrosty / bok /
spadki). To jest najważniejsza tabela w raporcie: strategia dodatnia tylko w
jednym rodzaju rynku to zakład kierunkowy, nie przewaga.

Raporty lądują w `models/reports/research_*.json`.

**Uwaga o danych**: rok historii to za mało. Na danych 2025–2026 (sama bessa)
wnioski wychodziły odwrotne do tych z 5,5 roku. Pobierz pełną historię:

```bash
.venv/bin/python scripts/download_data.py --days 2000
```

## Testy

```bash
pytest
```

**74 testy**, pokrycie:

- **Moduł 1**: backtest (ceny, koszty, benchmark), engine (paper), features (engineering),
  labeling (triple-barrier), fills (prosty/maker/short), funding (alt-data), risk (kill-switch)
- **Moduł 2**: allocator (drift, trend filter, brak look-ahead), backtest (kapitał,
  benchmark, koszty rebalansowania), book (izolacja dwóch ksiąg), data (parser Yahoo)
- **Dashboard**: humanize (mapowanie surowych danych na polskie zdania, emoji)

Ruff lint: 100% czysty.
