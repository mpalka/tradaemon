# TraDaemon 👹💰

*[English](README.md) · Polski*

> **To projekt edukacyjny.** Wszystko działa jako **paper trading** — pieniądze
> symulowane, żadnych prawdziwych zleceń. To nie jest porada inwestycyjna ani produkt.
> Zmierzona przewaga modułu krypto wynosi **około zera po kosztach** i ten README mówi
> to wszędzie tam, gdzie mówią to liczby. Zanim potraktujesz to poważnie, przeczytaj
> [czego się spodziewać](#czego-się-spodziewać-po-takim-bocie) oraz
> [DISCLAIMER.md](DISCLAIMER.md).

Narzędzie edukacyjne: **trzy równoległe moduły** do zabawy algorytmem i dyscypliną.

1. **Moduł 1 — Krypto-scalper** (LightGBM, 4h, 18 par USDT, paper trading)
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

Panel i dokumentacja są dostępne **po polsku i po angielsku**. Język wybierasz
w prawym górnym rogu panelu albo parametrem `?lang=pl` / `?lang=en` w adresie.

## Start od zera

Ta sekcja nie zakłada niczego: ani Pythona, ani danych, ani wytrenowanego modelu. Przejdź
ją od góry do dołu, a skończysz z botem handlującym symulowanymi pieniędzmi i panelem,
który pokazuje, co zrobił.

### 1. Czego potrzebujesz

| | Potrzebne | Sprawdzisz przez |
|---|---|---|
| **Python 3.12 lub nowszy** | język, na którym to wszystko chodzi | `python3 --version` |
| **Git** | żeby pobrać kod | `git --version` |
| ~1 GB wolnego dysku | pobrane świece i wytrenowane modele | |

Opcjonalnie, ale warto:

- **`libomp`** — biblioteka wielowątkowości dla LightGBM. Bez niej kod automatycznie
  używa `HistGradientBoostingClassifier` ze scikit-learn, który działa poprawnie, tylko
  wolniej. Pominięcie tego kroku niczego nie psuje.
- **Docker** — jeśli wolisz uruchomić wszystkie cztery serwisy naraz; patrz [Docker](#docker-orbstack--docker-desktop).

<details>
<summary><b>Instalacja wymagań — macOS</b></summary>

```bash
# Homebrew (pomiń, jeśli już masz): https://brew.sh
brew install python@3.12 git libomp
```

Działa i na Apple Silicon, i na Intelu.
</details>

<details>
<summary><b>Instalacja wymagań — Linux (Debian/Ubuntu)</b></summary>

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git libgomp1
```

Na Fedorze/RHEL: `sudo dnf install python3.12 git libgomp`. Na Archu:
`sudo pacman -S python git openmp`.
</details>

<details>
<summary><b>Instalacja wymagań — Windows</b></summary>

Najprościej, w PowerShellu:

```powershell
winget install --id Python.Python.3.12 -e ; winget install --id Git.Git -e
```

Potem **zamknij i otwórz PowerShell na nowo**, żeby nowe `python` i `git` trafiły do
PATH. Windowsowe paczki LightGBM mają własny runtime OpenMP, więc kroku z `libomp` tu
nie ma.

Jeśli wolisz środowisko uniksowe, [WSL2](https://learn.microsoft.com/windows/wsl/install)
też działa — w środku postępuj według instrukcji dla Linuksa.
</details>

### 2. Pobierz kod i zainstaluj

Komendy różnią się wyłącznie sposobem aktywacji środowiska.

<details open>
<summary><b>macOS / Linux</b></summary>

```bash
git clone https://github.com/mpalka/tradaemon.git
cd tradaemon
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # może zostać pusty; tryb paper nie potrzebuje kluczy
```
</details>

<details>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
git clone https://github.com/mpalka/tradaemon.git
cd tradaemon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env   # może zostać pusty; tryb paper nie potrzebuje kluczy
```

Jeśli PowerShell odmówi uruchomienia skryptu aktywacji, pozwól mu na tę sesję:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`.
</details>

Po aktywacji w wierszu poleceń pojawia się `(.venv)`, a zwykłe `python` i `pytest`
odnoszą się do tego środowiska. **Wszystkie komendy niżej zakładają aktywne
środowisko.** Jeśli wolisz go nie aktywować, poprzedzaj je `.venv/bin/` na macOS/Linuksie
albo `.venv\Scripts\` na Windowsie.

Zanim pójdziesz dalej, sprawdź, czy instalacja jest zdrowa:

```bash
pytest -q
```

Powinny przejść 294 testy — nie potrzebują ani sieci, ani danych.

### 3. Pobierz dane rynkowe

Publiczne endpointy Binance — bez klucza API, bez konta.

```bash
python scripts/download_data.py --days 2000
```

Ściąga około pięciu i pół roku świec 1-minutowych dla 18 skonfigurowanych par do
katalogu `data/`. Trwa chwilę i jest najwolniejszym krokiem tutaj. **Używaj pełnej
historii**: na roku danych (jeden reżim bessy) wnioski w tym projekcie wychodziły
odwrotnie — patrz [uwaga o danych](#uwaga-o-danych). Na pierwsze spojrzenie wystarczy
`--days 180`, ale nie ufaj wynikom z takiego okna.

### 4. Wytrenuj model

```bash
python scripts/train.py
```

Walidacja krocząca, raport AUC per fold. Model ląduje w `models/`. Silnik bez modelu nie
wystartuje i powie ci o tym wprost.

### 5. Zobacz, co mówi backtest

```bash
python scripts/backtest.py
```

Drukuje wynik per para po kosztach i zapisuje raport HTML do `models/reports/`. Spodziewaj
się przewagi bliskiej zeru — to jest uczciwy wynik, a nie zepsuta instalacja.

### 6. Uruchom bota na symulowanych pieniądzach

```bash
python -m tradaemon.engine
```

To jest **długo działająca pętla**, a nie polecenie jednorazowe: nadrabia świece, które
przegapił, potem czeka na kolejne zamknięcie 4h i chodzi tak, dopóki go nie zatrzymasz
Ctrl-C. Pierwszy przebieg może zająć kilka minut, bo wczytuje historię wszystkich 18 par.
Nie przyjmuje żadnych argumentów — zostaw go w osobnym terminalu albo uruchom jako usługę
przez [Dockera](#docker-orbstack--docker-desktop).

Nic tutaj nie składa prawdziwego zlecenia. `mode: paper` w `config/config.yaml` jest
domyślny, a przejście na live to [osobna, świadoma decyzja](#tryb-live-moduł-1--świadoma-decyzja).

### 7. Otwórz panel

W drugim terminalu, z aktywnym środowiskiem:

```bash
streamlit run src/tradaemon/dashboard/app.py
```

Potem wejdź na <http://localhost:8501>. Dopóki silnik nie przejdzie choć raz, panel
napisze to wprost, zamiast pokazywać pusty wykres.

### 8. Opcjonalnie — moduł portfela

Niezależny od powyższego i niepotrzebujący wytrenowanego modelu. Dane dzienne z Yahoo
Finance, za darmo i bez klucza.

```bash
python scripts/portfolio_backtest.py --years 10   # rebalans vs kup i trzymaj
python -m tradaemon.portfolio --backfill           # replay pełnej historii i koniec
python -m tradaemon.portfolio --once               # jeden dzień i koniec
python -m tradaemon.portfolio                      # pętla dzienna (Ctrl-C, żeby zatrzymać)
```

Panel sam wykryje księgi portfela.

### Gdzie co ląduje

Nic poza katalogiem projektu nie jest ruszane. Cztery katalogi powstają przy pierwszym
użyciu i żadnego z nich nie ma w gicie:

| Katalog | Zapisuje | Trzyma |
|---|---|---|
| `data/` | `download_data.py`, refresher | pobrane świece (Parquet) |
| `models/` | `train.py`, refresher | wytrenowane modele i raporty |
| `runtime/` | silnik, pętla portfela | stan i dzienniki każdej księgi |
| `.venv/` | ty, w kroku 2 | środowisko Pythona |

Skasowanie `runtime/` resetuje księgi paper do kapitału startowego. Skasowanie `data/`
i `models/` oznacza powtórzenie kroków 3 i 4.

## Docker (OrbStack / Docker Desktop)

```bash
cp .env.example .env   # musi istnieć, może zostać pusty
docker compose up --build
```

Uruchamia **cztery serwisy**:

| Serwis | Rola |
|--------|------|
| `bot` | Moduł 1: krypto-scalper, 3 warianty A/B na 18 parach USDT |
| `dashboard` | Panel na `localhost:8501` (oba moduły, UI dla początkującego) |
| `portfolio` | Moduł 2: zarządca portfela, rebalancing ETF-ów |
| `refresher` | Cotygodniowe trenowanie (bramka bezpieczeństwa: promuje tylko + wynik) |

Dane, modele i stan runtime montowane z `./data`, `./models`, `./runtime`.
Każdy serwis ma własny dziennik (logs): `docker compose logs -f bot` itp.

> **Panel nie ma logowania.** Nasłuchuje na `0.0.0.0:8501` i pozwala każdemu, kto go
> dosięgnie, zmienić konfigurację działającego bota. Trzymaj go w zaufanej sieci
> lokalnej i nigdy nie przekierowuj tego portu z internetu.

Wdrożenie na Synology NAS (build na NAS-ie, LAN-only): [docs/DEPLOY_SYNOLOGY.pl.md](docs/DEPLOY_SYNOLOGY.pl.md).

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

Scalper ma sufit ekspozycji (`position_pct` × `max_open_positions` = 50%), więc
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

- `pairs` — lista par USDT (domyślnie 18 najpłynniejszych)
- `strategy` — timeframe (4h), TP/SL w ATR, horyzont, próg prawdopodobieństwa
- `costs` — prowizja, poślizg na każdym fillu
- `risk` — wielkość pozycji, max pozycji otwartych, dzienny kill-switch, próg alertu DD
- `variants` — A/B: kilka wariantów testuje się równolegle na tych samych świecach,
  każdy z własnym `runtime/<name>/`, porównywane w zakładce Warianty. Brak = jedna księga.
- `primary_variant` — który wariant pokazać jako „Twój portfel" na głównym ekranie
- `display_timezone` — strefa IANA, w której rysowane są znaczniki czasu (silnik zawsze
  zapisuje UTC)
- `display_language` — `pl` albo `en`, dla wszystkiego bez widza: alerty silnika,
  wiadomości webhooka, drukowane raporty. W panelu każdy wybiera język na swoją sesję.

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
python -m tradaemon.portfolio --backfill   # replay pełnej historii (5452 dni) i koniec
python -m tradaemon.portfolio --once       # jeden dzień i koniec
python -m tradaemon.portfolio              # pętla dzienna (śpi 6h; Ctrl-C, żeby zatrzymać)

W odróżnieniu od silnika krypto ten moduł **przyjmuje** `--once` i `--backfill`.
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

Skrót poniżej pokazuje przepływ danych. Pełny opis mechanizmu — droga jednej świecy
od giełdy do zlecenia, kto pisze i czyta które pliki, co wchodzi na gorąco a co
wymaga restartu — jest w [howitworks.pl.md](howitworks.pl.md).

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
   `tradaemon.backtest.runner`, który dzieli `execution/fills.py` z silnikiem.
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

# Czy szersza plansza i inna reguła przydziału slotów pomagają całej książce?
.venv/bin/python scripts/research/universe.py --windows 10 --window-days 90
```

`universe.py` mierzy coś, czego pozostałe skrypty zmierzyć nie mogą, bo idą przez
`backtest/runner.py` — a ten daje **każdej parze osobny portfel i nieograniczoną
liczbę slotów**. Przy takim liczeniu dorzucenie par może wynik tylko podnieść, bo
to zwykłe dopisanie kolejnego rachunku do średniej. Prawdziwa księga ma jeden
portfel i `risk.max_open_positions` miejsc, o które pary konkurują. Ten skrypt
liczy tę konkurencję przez [`backtest/book.py`](src/tradaemon/backtest/book.py) —
wspólna gotówka, wspólny limit, ten sam `RiskManager` co silnik.

### Wynik (2026-08): o wyniku decyduje limit, nie plansza

Powód badania był praktyczny: `prog_050` z limitem podniesionym w panelu do 10 trzymał
**9 z 10 par** przy 99 USDT wolnej gotówki. Plansza była wyczerpana — pytanie brzmiało,
czy dołożyć par.

Dziesięć okien po 90 dni, model trenowany od nowa przed każdym oknem, osobno dla każdej
planszy, wszystkie pary konkurujące o jeden portfel:

**1. Poszerzenie planszy płaci wyłącznie przy ciasnym limicie** (18 par minus 10 par):

| limit | różnica | okna na plus |
|---|---|---|
| 3 | **+0,78 pp** | 7/10 |
| 5 | −0,31 pp | 5/10 |
| 10 | **−2,32 pp** | 3/10 |

**2. Sam limit to najsilniejszy zmierzony efekt w tym projekcie** (limit 3 minus limit 10):

| plansza | różnica | okna na plus | t |
|---|---|---|---|
| 18 par | **+4,49 pp** | 8/10 | **+2,73** |
| 10 par | +1,39 pp | 5/10 | +0,90 |

To jedyny wynik tutaj, który przekracza zwykły próg istotności. Mechanizm jest spójny:
szeroka plansza jest wartościowa jako **pula do wybierania**, nie jako lista do
zapełnienia. Przy 10 slotach książka bierze wszystko, co zasygnalizuje — 2609
transakcji zamiast 1713 przy tej samej ekspozycji 80% — więc dodatkowe pary dokładają
obrót i prowizje, i nic poza tym.

**3. Oddawanie slotu najsilniejszemu sygnałowi nie płaci**: −0,6 do +0,7 pp, pięć z
sześciu porównań na zero albo minus, nawet tam, gdzie limit odrzuca 3000 kandydatów.
Najprostsze wyjaśnienie: prawdopodobieństwo z modelu jest zbyt słabo informatywne, żeby
się nim dało sortować. Rankingu **nie wdrożono**. Silnik dostał z tego tylko
diagnostykę: pyta model **przed** sprawdzeniem limitu, więc panel pokazuje, jak dużą
okazję limit odrzucił, zamiast pustej kolumny obok „wstrzymany limitem ryzyka".

Wdrożono 18 par i limit 5 — poszerzenie jest przy piątce neutralne, ale piątka bije
dziesiątkę na obu planszach, a trójka (najlepsza w pomiarze) trzymałaby w rynku
o połowę mniej kapitału.

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

**294 testy**, pokrycie:

- **Moduł 1**: backtest (ceny, koszty, benchmark), engine (paper), features (engineering),
  labeling (triple-barrier), fills (prosty/maker/short), funding (alt-data), risk (kill-switch)
- **Moduł 2**: allocator (drift, trend filter, brak look-ahead), backtest (kapitał,
  benchmark, koszty rebalansowania), book (izolacja dwóch ksiąg), data (parser Yahoo)
- **Moduł 3**: sygnał (brak look-ahead), ocena na rozłącznych oknach
- **Dashboard**: humanize (mapowanie surowych danych na zdania), arytmetyka ekranu
  ustawień, podgląd kursu, dzienniki
- **i18n**: że każdy język definiuje te same klucze z tymi samymi placeholderami i że
  żaden klucz użyty w kodzie nie brakuje w katalogu

Lint: `ruff check .`

---

## Czego się spodziewać po takim bocie

Ta sekcja istnieje, bo uczciwą odpowiedź łatwo zgubić wśród tabel wyżej.
**Realistycznie oczekiwanym wynikiem uruchomienia tego bota na prawdziwych pieniądzach
jest strata** — i nie jest to pesymizm co do tego konkretnego kodu, tylko to, co
konsekwentnie znajdują badania nad handlem detalicznym.

**Co mówią pomiary z tego projektu.** Przewaga modułu krypto w backteście wynosi około
zera po kosztach. Moduł portfela przegrywa z kup&trzymaj na dziesięciu latach. Badanie
przekrojowe dochodzi do 1,11 odchylenia standardowego od zera, gdzie zwykłą poprzeczką
jest ~2. Żaden z trzech modułów nie dał wyniku przekraczającego próg istotności, a ten
README raportuje każdy z nich tak, jak został zmierzony, a nie tak, jak by się chciało.

**Co mówi szersza literatura.** Sprawdź to sam, zamiast wierzyć plikowi README; poniższe
wyniki są dobrze replikowane i łatwe do znalezienia:

- Barber i Odean, *Trading Is Hazardous to Your Wealth* (2000): najbardziej aktywni
  inwestorzy indywidualni wypadali po kosztach wyraźnie gorzej niż rynek — im więcej
  handlowali, tym gorzej.
- Barber, Lee, Liu i Odean na danych z Tajwanu (2014): tylko bardzo mała część
  day-traderów — grubo poniżej 1% — była trwale rentowna po opłatach, a straty
  większości utrzymywały się rok po roku.
- Chague, De-Losso i Giovannetti (2020) na brazylijskich kontraktach terminowych: wśród
  tych, którzy handlowali dłużej niż 300 dni, przeważająca większość traciła pieniądze.
- Prace López de Prado o przeuczeniu backtestu: jeśli przetestujesz dość wariantów na tej
  samej historii, imponujący Sharpe pojawi się **przypadkiem**. Backtest nie jest dowodem,
  dopóki nie policzysz, ile rzeczy sprawdziłeś.

**Dlaczego to jest strukturalne, a nie pech.** Przeciwko detalicznemu botowi działają
naraz trzy siły — i ten projekt potrafi zmierzyć wszystkie trzy:

1. **Koszty kumulują się z obrotem.** Każda runda płaci prowizję i poślizg. Strategia
   handlująca często potrzebuje realnej przewagi, żeby w ogóle wyjść na zero —
   `scripts/research/fee_grid.py` istnieje właśnie po to, żeby pokazać, ile z pozornej
   przewagi zjada cennik giełdy.
2. **Po drugiej stronie są profesjonaliści.** Cokolwiek model gradientowy znajdzie
   w publicznych danych OHLCV, firmy z szybszymi danymi, niższymi opłatami i większym
   kapitałem już tego szukały. To, co łatwe, jest już w cenie.
3. **Backtesty zawyżają.** Zakładają wykonanie po modelowych cenach, ignorują awarie
   i są dopasowane do reżimu, który już się wydarzył. Ten projekt został zaskoczony
   dokładnie w ten sposób — wnioski z roku danych odwróciły się na pięciu i pół.

**Do czego to się naprawdę nadaje.** Do zrozumienia, jak ta maszyneria się składa; do
wyrobienia nawyku mierzenia się z uczciwą poprzeczką; do wyczucia, jak łatwo prawdopodobnie
wyglądający wynik okazuje się szumem. To są realne rzeczy i to dla nich ten projekt
istnieje. Zarabianie pieniędzy nie jest na tej liście.

Jeśli masz zapamiętać jedną liczbę: trzy moduły dały tu wynik ≈0, −33,6 punktu
procentowego względem poprzeczki i 1,11 odchylenia standardowego. Tego się spodziewaj.

---

## Licencja i zastrzeżenia

MIT — patrz [LICENSE](LICENSE).

Pełne zastrzeżenie, po polsku i po angielsku, jest w [DISCLAIMER.md](DISCLAIMER.md).
W skrócie: projekt edukacyjny, handel na papierze, to nie porada inwestycyjna, brak
gwarancji, a panel nie ma logowania, więc jego miejsce jest wyłącznie w zaufanej sieci
lokalnej.
