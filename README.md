# TraDaemon 👹💰

Narzędzie edukacyjne: **dwa równoległe moduły** do zabawy algorytmem i dyscypliną.

1. **Moduł 1 — Krypto-scalper** (LightGBM, 4h, 10 par USDT, paper trading)
   Krótkoterminowy trading oparty o machine learning z triple-barrier labeling,
   walk-forward validation i backtestem uwzględniającym koszty. Backtest wykazuje
   przewagę ~0 po kosztach — moduł pełni rolę **laboratorium edukacyjnego**.

2. **Moduł 2 — Zarządca portfela** (rebalanser ETF-ów, paper trading)
   Systematyczne przywracanie docelowych proporcji koszyka SPY/TLT/GLD,
   z opcjonalnym filtrem trendu. Backtest na 10 latach pokazuje, że rebalansowanie
   przycina zwycięzców w hossie — jego wartość to dyscyplina i redukcja ryzyka, nie alpha.

3. **Moduł 3 — Ranking przekrojowy** (badanie, bez księgi na żywo)
   Kupuj najsilniejsze aktywa, sprzedawaj najsłabsze — zakład na różnicę między
   aktywami, nie na kierunek rynku. Ten sam kod na krypto i ETF-ach, oceniany na
   rozłącznych oknach. Wynik: wciąż nieodróżnialny od szumu, ale najbliżej.

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
cp .env.example .env   # musi istnieć, może zostać pusty
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

Wdrożenie na Synology NAS (build na NAS-ie, LAN-only): [docs/DEPLOY_SYNOLOGY.md](docs/DEPLOY_SYNOLOGY.md).

## Dashboard (localhost:8501)

### Ekran dla początkującego (domyślny widok)

Bez żargonu — wszystko po polsku:

- **„Ile masz"** — wartość portfela + zmiana (🟢/🔴)
- **Status bota** — 🟢 działa / 🔴 czeka (ostatni odczyt rynku)
- **„Jak to szło"** — krzywa kapitału vs szara linia „kup i trzymaj"; przełącznik 7d / 30d / całość
- **„Co bot trzyma"** — otwarte pozycje jako zdania (np. „kupił ETH za 100 $ — teraz +2 $")
- **„Dziennik zdarzeń"** — oś czasu z ikonami (kupił, sprzedał, limit strat)
- **Podgląd kursu** — instrumenty w obu tych sekcjach są klikalne: kliknięcie rozwija
  **pod tym wierszem** wykres kursu z transakcjami bota (▲ kupno, ▼ sprzedaż), linią
  ceny wejścia i — gdy otwarty z dziennika — znacznikiem chwili zdarzenia. Samo najechanie pokazuje dymek
  z ceną i zmianą 24 h / 7 dni (wykresu na hover Streamlit nie potrafi bez własnego
  komponentu JS). Wybór trzyma się w sesji, więc odświeżanie co 15 s go nie zamyka.
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

**Krypto-scalper · Zarządca portfela · Badania** — trzy ekrany.

Pierwsze dwa prowadzą portfel i odświeżają się co 15 s. **Badania** to co innego:
narzędzia, które nie trzymają żadnej pozycji, tylko odpowiadają na pytanie „czy ten
pomysł się broni?". Zakładka czyta ostatni zapisany raport z `models/reports/`
i pozwala go przeliczyć na danych z dysku (bez pobierania, żeby nie blokować panelu):

- **Ranking przekrojowy** (Moduł 3) — macierz rynek × kierunek × okno, miara
  „odchyleń od zera" i ostrzeżenie o błędzie przetrwania;
- **Przesiew dywersyfikacji** — tabela korelacji z werdyktami; przebieg `--as-of`
  jest wyraźnie oznaczony, żeby historyczny przesiew nie udawał aktualnego.

### Uczciwe liczby: ile pieniędzy naprawdę gra

Scalper ma sufit ekspozycji (`position_pct` × `max_open_positions` = 30%), więc
większość konta stoi w gotówce. To **nie jest wada strategii** — przy przewadze ≈ 0
dokładanie pieniędzy zwiększyłoby stratę. Jest natomiast pułapką pomiaru, którą panel
teraz nazywa wprost:

- **„w grze: X% pieniędzy"** — ile konta naprawdę siedzi w rynku (scalper ~20–30%,
  zarządca portfela 100%);
- **dwie liczby obok siebie** — „wynik od wszystkich pieniędzy" vs „wynik od pieniędzy
  w grze"; ta druga jest ok. 4× ostrzejsza i uczciwiej ocenia sam sygnał;
- **dwie linie odniesienia** na wykresie — „wszystko w rynku" (jasna) i „tyle w rynku
  co bot" (ciemna). Ta ciemna to sprawiedliwa poprzeczka: porównanie z kimś, kto włożył
  wszystko, chwali bota za samą **nieobecność** w spadkach.

Przelicznik jest przybliżeniem (zakłada liniowe skalowanie) i **celowo się nie
pokazuje**, gdy bot był w rynku bardzo rzadko — w backteście per para pozycja jest
otwarta na ~6–11% świec, więc średnia ekspozycja ~0,6% mnożyłaby wynik ×166. Raport
podaje wtedy same fakty: średnią ekspozycję i czas w rynku.

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


## Przesiew dywersyfikacji (Moduł 2)

Odpowiada na pytanie o ryzyko, nie o prognozę: **jeśli rynek światowy spada, co w
koszyku nie spada razem z nim?** Benchmark to `VT` (Vanguard Total World — USD-owy
odpowiednik FTSE All-World z najdłuższą historią na Yahoo).

```bash
python scripts/correlation_screen.py                      # ostatnie 10 lat
python scripts/correlation_screen.py --as-of 2016-07-30   # co metoda wybrałaby WTEDY
```

### Wynik: ujemnie skorelowanych aktywów praktycznie nie ma

Na 36 kandydatach, 119 miesięcy do lipca 2026, ujemną korelację z VT ma 8 — i **każde
z nich traci pieniądze z konstrukcji** (SH −14%/rok, VIXY −46%/rok). Wśród aktywów
o dodatnim zwrocie najniżej jest UUP (−0,44) i złoto (+0,21).

**Kolumna, która niesie treść, to zakres kroczący, nie średnia:**

| Aktywo | Korelacja | Zakres 3-letni | CAGR |
|---|---|---|---|
| **GLD** | +0,21 | **−0,02 … +0,40** | **+11,8%** |
| TLT | +0,21 | −0,47 … **+0,75** | **−5,2%** |
| UUP | −0,44 | −0,67 … −0,28 | +1,3% |
| SH (odwrotny S&P) | −0,95 | −0,97 … −0,92 | −14,2% |

TLT wygląda jak dywersyfikator średnio, ale skoczył do **+0,75** w 2022 — przestał
chronić dokładnie wtedy, gdy był potrzebny, a przez dekadę stracił 5,2% rocznie.
Dlatego werdykty to `KANDYDAT` / `NIESTABILNY` / `TRACI` / `PUŁAPKA`, a nie sam ranking.

### Najważniejsze: test bez wiedzy o przyszłości (`--as-of`)

Przesiew na danych **do 2016** wskazałby jako dwa najlepsze **UUP i TLT** — TLT miało
wtedy korelację −0,27, nigdy dodatnią (max −0,08) i +5,4%/rok. Idealny dywersyfikator
wg tej metody. Zastosowany na kolejne 10 lat:

| Koszyk | Wynik | CAGR | Sharpe | Obsunięcie |
|---|---|---|---|---|
| wg przesiewu z 2016 (SPY/UUP/TLT) | +87,2% | 6,50% | 0,75 | **−15,4%** |
| obecny (SPY/TLT/GLD) | +112,5% | 7,87% | 0,77 | −24,9% |
| wg przesiewu z 2026 (SPY/GLD/UUP) | +179,5% | 10,87% | 1,06 | −18,1% |

**Metoda wskazała w 2016 aktywo, które potem zawiodło** — bo korelacje i zwroty są
własnością reżimu, a 10-letnie okno opisuje reżim, który się właśnie skończył.
Trzecia linia wygląda najlepiej wyłącznie dlatego, że wybierano ją **po fakcie**.

To, co przetrwało uczciwy test: **najniższe obsunięcie (−15,4%)**. Przesiew nie
podnosi zwrotu, ale realnie ogranicza ryzyko — i to jest jego uczciwa wartość.

## Moduł 3: Ranking przekrojowy (badanie, bez księgi na żywo)

Zamiast „czy BTC wzrośnie" (hipoteza Modułu 1, zmierzona na ≈ zero) pyta: **które
aktywa są najsilniejsze względem pozostałych?** Kupuje liderów, opcjonalnie sprzedaje
maruderów, przeranguje co ~20 dni. Zakład dotyczy **różnicy między aktywami**, nie
kierunku rynku.

```bash
python scripts/crosssec_backtest.py --refresh        # pobierz dane i policz macierz
python scripts/crosssec_backtest.py --market etf     # jeden rynek
python scripts/crosssec_backtest.py --lookback 250 --rebalance 60
```

Ten sam kod chodzi na **25 parach krypto i 29 ETF-ach**, w dwóch wariantach
(tylko long / long-short), na **4 rozłącznych oknach** — bo trzy razy w tym projekcie
„najlepszy" wynik z jednego okna okazał się szumem. Raport pokazuje **wszystkie okna**
i nie wybiera zwycięzcy.

### Wynik (2026-07): nadal zero, ale ciekawiej

| Rynek | Wariant | Wynik | Poprzeczka | Odchyleń od zera |
|---|---|---|---|---|
| krypto | long-short | **+66,3%** | gotówka | +1,11 — nieodróżnialne |
| krypto | tylko long | −9,6% | koszyk (−20,2%) | +0,80 — nieodróżnialne |
| ETF | tylko long | +57,7% | koszyk (+128,1%) | +1,08 — nieodróżnialne |
| ETF | long-short | −28,5% | gotówka | −1,04 — nieodróżnialne |

Krypto long-short jest dodatnie w **3 z 4 okien** i +66% przez 5,5 roku przy
ekspozycji netto 0,4% (realnie neutralne rynkowo) — najciekawszy wynik w tym
projekcie. **Ale 1,11 odchylenia od zera to nie jest przewaga** — potrzeba ~2. Do tego
ETF-y, gdzie momentum przekrojowe jest najlepiej udokumentowane, są **spójnie ujemne
w 4 z 4 okien**. Gdyby efekt był własnością metody, pokazałby się na obu rynkach.

**Poprzeczka zależy od ekspozycji** (ta sama lekcja co w Module 1): long-only mierzy
się z koszykiem kup&trzymaj, long-short z **gotówką** — porównywanie książki neutralnej
rynkowo z w pełni długim koszykiem zawyżałoby ją w każdym spadku.

> **Główne zastrzeżenie: błąd przetrwania.** 25 par krypto to te, które **dotrwały** do
> dziś i są dziś płynne. Brak LUNA, FTT i innych, które umarły — a to zaburza wynik
> w nieznanym kierunku. Dodatkowo long-short na krypto wymaga kontraktów wieczystych
> (nie spot), a **koszt funding nie jest w ogóle modelowany**. Traktować jako pomiar
> hipotezy, nie jako strategię.

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
