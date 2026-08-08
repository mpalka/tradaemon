# Jak to działa (od środka)

README opisuje **co** ten projekt robi i **jakie dał wyniki**. Ten plik opisuje
**mechanizm**: jaką drogę przechodzi jedna świeca od giełdy do zlecenia, kto pisze
i kto czyta które pliki, i dlaczego kilka rzeczy jest zrobionych inaczej, niż
wyglądałaby wersja oczywista.

Wersja kodu, którą opisuje ten dokument: `0.1.8`.

---

## 1. Widok z góry

TraDaemon to **cztery procesy nad jednym katalogiem plików**. Nie ma bazy danych,
nie ma kolejki, nie ma API między procesami. Cała komunikacja idzie przez dysk:

```
                   config/            data/            models/           runtime/
                   ───────            ─────            ───────           ────────
  bot          czyta ──────►     czyta ──────►    czyta ──────►      PISZE ──────►
  portfolio    czyta ──────►     czyta/pisze ►                        PISZE ──────►
  refresher    czyta ──────►     PISZE ──────►    PISZE ──────►       pisze status
  dashboard    czyta + PISZE     czyta ──────►    czyta ──────►       tylko czyta
                (overrides)
```

Dwie zasady, z których wynika reszta architektury:

1. **Silnik jest jedynym pisarzem stanu księgi.** `runtime/*/state.json` i dzienniki
   `*.jsonl` pisze wyłącznie proces handlujący. Panel ich nigdy nie dotyka — czyta.
   Dzięki temu dwa procesy nad tym samym bind-mountem nie potrzebują żadnego
   zamka.
2. **Panel jest jedynym pisarzem konfiguracji** — i to nie do `config/config.yaml`,
   tylko do siostrzanego `config/config.overrides.yaml` (patrz §7).

Ruch w drugą stronę — panel chce coś zmienić w silniku — idzie przez ten sam dysk:
zapis nakładki (silnik podnosi ją sam) albo plik-flaga `runtime/restart_requested`
(silnik wychodzi, Docker go wskrzesza).

---

## 2. Trzy moduły, jedno wspólne dno

| | Moduł 1 — scalper | Moduł 2 — zarządca portfela | Moduł 3 — ranking |
|---|---|---|---|
| Pyta o | „czy ten instrument wzrośnie" | „czy proporcje się rozjechały" | „które aktywo jest silniejsze od reszty" |
| Zegar | świeca 4h | dzień | ~20 dni |
| Decyduje | model ML (LightGBM) | reguła (drift/kadencja) | ranking momentum |
| Księga na żywo | tak (4 warianty) | tak (1) | **nie** — samo badanie |
| Dane | Binance przez CCXT | Yahoo Finance | oba źródła |

Wspólne dla wszystkich: `execution/fills.py` (model kosztów), `engine/state.py`
(`RuntimeStore` — persystencja i dzienniki), `backtest/metrics.py` (Sharpe,
obsunięcie, ekspozycja) i panel.

To nie jest współdzielenie dla oszczędności linii. **Backtest i handel papierowy
przechodzą przez ten sam plik od fillów**, więc „to, co zmierzył backtest" i „to, co
robi bot" to dosłownie ta sama ścieżka wykonania — nie dwie implementacje tej samej
umowy, które rozjeżdżają się przy pierwszej poprawce.

---

## 3. Moduł 1: droga od świecy do zlecenia

### 3.1 Dane

`scripts/download_data.py` → `data/ingestion.py` → Parquet, jeden plik na
(giełda, para, interwał): `data/binance_BTC-USDT_4h.parquet`.

- Pobieranie jest **przyrostowe**: przy kolejnym uruchomieniu dociąga tylko to,
  czego nie ma — od ostatniej zapisanej świecy w przód, a przy większym `--days`
  także wstecz, przed najstarszą.
- **Świeca wciąż otwarta jest odrzucana** (`df[df.timestamp < cutoff]`). To samo
  odcięcie robi silnik przy starcie (`raw[:-1]`) i w feedzie. Świeca otwarta ma
  ruchome `high`/`low`/`close` — sygnał z niej byłby sygnałem z przyszłości.
- `storage.find_gaps` raportuje dziury w historii; interwał czyta z `TIMEFRAME_MS`.

### 3.2 Cechy (`features/engineering.py`)

26 kolumn (+ 4 opcjonalne z funding rate), wszystkie liczone wyłącznie z przeszłości
— `rolling`, `ewm`, `shift`, nigdy `shift(-1)`. Cztery rodziny:

- **zwroty i zmienność** — log-zwroty na 1/3/5/15/30/60 barach, odchylenia na 15 i 60
  oraz ich stosunek (czy zmienność właśnie rośnie);
- **klasyczne wskaźniki** — RSI 14, ATR znormalizowany ceną, EMA 9/21 i odległość od EMA 50;
- **kształt świecy i wolumen** — `body_ratio`, zakres świecy, z-score wolumenu;
- **kontekst reżimu** — `trend_42`/`trend_180`, `mom_42`/`mom_180`, `vol_regime`,
  `dd_180` (jak daleko od 180-barowego szczytu). Na 4h to mniej więcej tydzień i miesiąc.

Gwarancja „wartość cechy w barze *t* nie zmienia się, gdy przyjdą kolejne bary" jest
zapięta testem (`tests/test_features.py`), a nie tylko konwencją.

### 3.3 Etykiety: triple-barrier (`labeling/triple_barrier.py`)

Etykieta nie brzmi „czy cena wzrosła", tylko **„czy wchodząc tutaj, trafiłbym w
take-profit przed stop-lossem"**. Dla sygnału z zamknięcia bara *t*:

- wejście po **otwarciu bara t+1** (nie po zamknięciu t — tego nie da się kupić),
- bariery: `wejście ± mult × ATR(t)`,
- skan barów t+1…t+H; etykieta 1 tylko wtedy, gdy TP zostało dotknięte **ściśle
  wcześniej** niż SL,
- **bar, który dotyka obu barier, liczy się jako SL**. Kolejności ruchów wewnątrz
  bara nie znamy, więc zakładamy gorszy wariant. To samo założenie ma symulator
  fillów, więc etykieta i egzekucja nie kłócą się o ten sam bar.

Ostatnie `H+1` barów nie da się zaetykietować (nie mają pełnego horyzontu) —
zostają jako NaN i wypadają z treningu.

### 3.4 Trening: walk-forward z purge (`models/train.py`)

Okna rozszerzające się: fold *i* uczy się na wszystkim od początku do
`test_start − purge`, testuje na następnym kawałku. Kluczowy jest **purge gap** ≥
horyzontu etykiety: bez niego etykieta z końcówki zbioru treningowego zagląda w bary,
które są już w teście — i AUC wychodzi ładne z powodu wycieku, nie z powodu sygnału.

Model: LightGBM (`n_estimators=400`, `learning_rate=0.03`, `min_child_samples=200`).
Bez `libomp` (typowe na macOS) kod sam schodzi na `HistGradientBoostingClassifier`
ze sklearn — ten sam interfejs, brak natywnych zależności.

`ModelBundle` zapisuje **własną listę kolumn cech** obok modelu. Backtest i silnik
czytają listę z bundla, nie ze stałej w kodzie — inaczej dodanie cechy unieważniałoby
po cichu każdy zapisany model.

### 3.5 Model kosztów (`execution/fills.py`)

Trzy funkcje i jedna decyzja: **taker płaci poślizg + prowizję, maker płaci prowizję
po cenie limitu**. Domyślnie 0,1% prowizji i 2 bps poślizgu, z `config.yaml`.

```
buy_fill:  cena_efektywna = cena × (1 + poślizg),  prowizja = nominał × taker_fee
sell_fill: cena_efektywna = cena × (1 − poślizg),  prowizja = nominał × taker_fee
```

`check_bracket_exit` odpowiada na pytanie „którą barierę dotyka ten bar" — i to jest
funkcja, którą wołają **jednocześnie** backtester i silnik na żywo.

### 3.6 Silnik (`engine/loop.py`)

Dwie warstwy, celowo rozdzielone:

- **`Book`** — jedna księga (gotówka, pozycje, ryzyko, własny `RuntimeStore`).
  W pełni synchroniczna: karmisz ją zamkniętymi świecami przez `on_candle` i
  sprawdzasz stan. Dlatego da się ją przetestować bez sieci i bez asyncio.
- **`TradingEngine`** — cienka warstwa async. Strumieniuje świece **raz** i rozsyła
  każdą zamkniętą do wszystkich ksiąg. Cztery warianty A/B nie oznaczają czterech
  razy więcej zapytań do giełdy.

Co się dzieje na jednej zamkniętej świecy, w tej kolejności:

```
on_candle(symbol, bar)
  1. dopisz bar do bufora (ostatnie warmup + horizon + 50 barów)
  2. _maybe_reload_models()   – czy refresher podmienił model?
  3. _maybe_reload_config()   – czy panel zmienił parametry? (§7)
  4. _manage_position()       – TP / SL / timeout na OTWARTEJ pozycji
  5. _maybe_enter()           – dopiero teraz rozważ nowe wejście
  6. dopisz wiersz do equity.jsonl
  7. sprawdź alarmy (kill-switch, obsunięcie)
  8. zapisz state.json (atomowo: tmp + os.replace)
```

Kolejność 4 → 5 nie jest przypadkowa: pozycja musi mieć szansę się zamknąć, zanim
limit „max otwartych pozycji" zablokuje cokolwiek innego.

**Wejście** wymaga przejścia przez cztery bramki: nie ma już pozycji na tym symbolu,
bufor przekroczył `warmup_bars`, `RiskManager.can_open` przepuszcza, i model daje
prawdopodobieństwo ≥ `prob_threshold`. Każde „nie" ląduje w `signals[symbol]` z
powodem (`warmup`, `risk_blocked`, `below_threshold`, `in_position`, `features_nan`,
`no_atr`) — to jest źródło zakładki „Model: dlaczego nie handluje".

**Wyjście**: TP, SL albo timeout po `horizon_bars`. Timeout ma wyjątek —
`_maybe_rollover`: jeśli deadline mija, a sygnał wciąż jest powyżej progu, pozycja
zostaje **przedłużona** (nowe TP/SL od bieżącego ATR, nowy deadline) zamiast zostać
zamknięta i natychmiast otwarta na tej samej świecy za podwójną prowizję i poślizg.
Na dniu z aktywnym kill-switchem rollover nie działa — bo ponowne wejście, które
zastępuje, też byłoby zablokowane.

### 3.7 Ryzyko (`risk/manager.py`)

Trzy proste reguły, świadomie bez finezji:

- **wielkość pozycji** = `position_pct` × bieżący kapitał (nie początkowy — sizing
  sam się kurczy po stratach);
- **sufit ekspozycji** = `max_open_positions`. Pary krypto są mocno skorelowane, więc
  otwarte pozycje i tak zwykle idą w tę samą stronę; 3 × 10% = 30% konta w rynku;
- **kill-switch dzienny**: po stracie zrealizowanej ≥ `daily_loss_limit_pct` startowego
  kapitału dnia — koniec nowych wejść do końca doby UTC. Istniejące pozycje dalej się
  domykają. Dzień jest częścią stanu (`snapshot`/`restore`), więc restart kontenera nie
  kasuje limitu.

### 3.8 Feed i awarie sieci

WebSocket (`ccxt.pro`) z **automatycznym zejściem na REST polling**, gdy się wywali.
Świeca jest rozsyłana dopiero, gdy zobaczymy jej następczynię — to jest definicja
„zamknięta".

Osobna pętla `_ticker_loop` co 60 s odświeża wyceny do panelu przez `mark_to_market` —
i **nigdy nie handluje**. Panel pokazuje żywe „ile masz", chociaż decyzje zapadają raz
na 4 godziny.

Trzy rzeczy tu wyglądają na nadmiarowe, a nie są (każda ma swój wpis w CHANGELOG):

- **Retry z backoffem przy starcie.** Bez tego proces umierał na `fetch_ohlcv`, a
  `restart: unless-stopped` wracał w tę samą awarię — 826 restartów przez pięć godzin.
  Teraz: 5 s → 10 s → … → 300 s, w nieskończoność, bo bot na 4h nic nie traci przez
  czekanie.
- **Alarm o połączeniu jest zamykany.** `connection` z `ok=False` to stan, nie zdarzenie
  — więc po powrocie sieci dopisywana jest para z `ok=True`. Bezwarunkowo przy każdym
  starcie, bo wisząca awaria zwykle należy do **poprzedniego** kontenera.
- **Log nie jest zalewany.** Traceback leci raz, potem tylko `WARNING` z licznikiem.
  Synology nie rotuje logów kontenerów.

### 3.9 Co zostaje na dysku

Na wariant, w `runtime/<nazwa>/`:

| Plik | Co zawiera | Kto go czyta |
|---|---|---|
| `state.json` | migawka: gotówka, pozycje, ostatnie ceny, sygnały per symbol, stan ryzyka, `live_config` | panel (zapis atomowy, więc nigdy nie złapie połowy) |
| `trades.jsonl` | **zamknięte** transakcje (wejście, wyjście, powód, prowizje, PnL) | panel: dziennik, analityka |
| `equity.jsonl` | jeden wiersz na przetworzoną świecę: kapitał i gotówka | panel: krzywa kapitału, ekspozycja |
| `alerts.jsonl` | zdarzenia: otwarcie, zamknięcie, rollover, kill-switch, obsunięcie, połączenie, zmiana configu | panel: oś czasu |

JSONL, nie baza — świadomie. Zachowuje `tail -f` na żywym bocie, `jq`, czytelny
`git diff`, a uszkodzony zapis kosztuje jeden wiersz, nie plik.

Uwaga na pułapkę, którą ten format kiedyś tu zastawił: `trades.jsonl` dostaje wiersz
dopiero przy **zamknięciu** pozycji, więc sam dziennik transakcji nie wie nic o tym,
co bot trzyma teraz. Otwarte pozycje są w `state.json` i panel musi czytać oba źródła.

---

## 4. Moduł 2: zarządca portfela

Ten sam szkielet, inny zegar i inna decyzja. `PortfolioBook.on_day(dzień, ceny, panel)`
zamiast `on_candle`.

Logika mieści się w czterech czystych funkcjach (`portfolio/allocator.py`, zero I/O):

```
effective_weights(historia, wagi_bazowe, trend)   → wagi docelowe (opcjonalny filtr trendu)
max_drift_pct(...)                                → największy rozjazd w punktach proc.
should_rebalance(dni_od_ostatniego, drift, cfg)   → kadencja LUB próg driftu
rebalance_orders(...)                             → zlecenia; sprzedaże przed kupnami
```

Sprzedaże są sortowane przed kupnami, żeby uwolniona gotówka miała czym finansować
kupna. Filtr trendu (domyślnie **wyłączony**) parkuje aktywo poniżej średniej `ma_days`
w `safe_asset` albo w gotówce.

Rebalans jest **idempotentny w obrębie doby** — powtórzenie tego samego dnia nic nie
zmienia. Dlatego pętla może budzić się co 6 h bez ryzyka podwójnego wykonania, a
`--backfill` może przepuścić całą historię (5452 dni) przez dokładnie ten sam kod, co
handel na żywo.

---

## 5. Moduł 3: ranking przekrojowy (badanie)

Nie ma księgi ani kontenera — jest skrypt i raport. Sygnał to momentum
`lookback_days` z **pominięciem** ostatnich `skip_days` (najświeższy ruch ma skłonność
do odwrotu; liczenie go wmieszałoby sygnał rewersji w sygnał momentum).
`select_legs` przycina nogi tak, żeby się nie nakładały — przy wąskim uniwersum
5 long + 5 short z 8 nazw kupowałoby i sprzedawało to samo.

Ten sam kod chodzi na krypto i na ETF-ach, na **czterech rozłącznych oknach**, i raport
pokazuje wszystkie — bo trzy razy w tym projekcie „najlepszy" wynik z jednego okna
okazał się szumem.

---

## 6. Backtest i uczciwość pomiaru

`backtest/runner.py` jest event-driven i przechodzi przez `fills.py` (§3.5). Poza tym
liczy się kilka rzeczy w `backtest/metrics.py`, które zmieniają interpretację wyniku:

- `avg_exposure_pct` i `time_in_market_pct` — ile konta naprawdę siedzi w rynku;
- `return_on_risked_pct` — wynik przeliczony na pieniądze, które grały;
- benchmark jest liczony **dwa razy**: „wszystko w rynku" i „tyle w rynku co bot".

Powód jest prosty: scalper trzyma ~20–30% konta, więc porównanie z kimś, kto włożył
wszystko, chwali bota za samą **nieobecność** w spadkach. Przelicznik na ekspozycję
celowo się nie pokazuje, gdy bot był w rynku bardzo rzadko — mnożnik ×166 nie jest
informacją, tylko artefaktem.

`scripts/research/` to osobny zestaw skryptów odpowiadających na pytanie „czy to
w ogóle ma przewagę", na trzech zasadach: rozłączne okna z modelem uczonym od nowa,
ten sam model kosztów co produkcja, i **naiwne kontrole** (zawsze long, zawsze short,
losowo, nie handluj). Strategia, która nie bije kontroli, niczego nie udowodniła.

---

## 7. Konfiguracja: co wchodzi na gorąco, a co wymaga restartu

Panel **nigdy nie pisze do `config/config.yaml`**. Ten plik jest udokumentowaną
bazą — nosi komentarze wyjaśniające, dlaczego 4h, dlaczego okno 2000 dni, po co
istnieje księga `ryzyko_100`. `yaml.safe_dump` skasowałby je wszystkie przy pierwszym
zapisie. Zamiast tego powstaje `config/config.overrides.yaml`, doklejany przez
`load_config`, więc „przywróć domyślne" to usunięcie klucza, a `git diff` pokazuje
tylko to, co naprawdę się zmieniło.

Dwie gwarancje `config_store.py`:

1. **nic niepoprawnego nie trafia na dysk** — zmiana jest scalana i walidowana przez
   model pydantic *przed* zapisem;
2. **każda zmiana jest w dzienniku** (`runtime/config_history.jsonl`) — zmiana
   parametrów w locie robi z krzywej kapitału mieszankę dwóch strategii, a dziennik
   pozwala panelowi narysować szew zamiast po cichu uśrednić.

Pola dzielą się na dwie klasy:

- **HOT** (`prob_threshold`, `tp/sl_atr_mult`, `horizon_bars`, `position_pct`,
  `max_open_positions`, prowizje…) — `Book` czyta je z `self.cfg` przy każdej świecy,
  więc wchodzą na następnym barze bez restartu.
- **RESTART** (`exchange.symbols`, `timeframe`, `warmup_bars`, lista `variants`,
  `initial_capital`…) — czytane raz w `__init__` albo w `run()`. Panel pisze flagę
  `runtime/restart_requested`, `_restart_watcher` ją widzi, silnik **zapisuje księgi
  i wychodzi**, Docker go wskrzesza, `Book.restore()` odczytuje gotówkę i pozycje.
  Panel nie ma gniazda Dockera i nie powinien mieć.

Sam czujnik zmiany jest **hashem treści** obu plików, nie mtime — i to jest poprawka,
która kosztowała jeden realny błąd. `mtime` porównywany przez `>` był ślepy na trzy
rzeczy naraz: skasowanie pliku (przywrócenie domyślnej wartości!) dawało 0.0, czyli
„nigdy nowszy" — na zawsze; dwa zapisy w tej samej sekundzie zlewały się w jeden;
wgranie starszej kopii było ignorowane. Skutek za każdym razem ten sam: panel pokazuje
nowe parametry, a bot do końca życia kontenera handluje na starych.

Symetryczny szczegół: **nieudany odczyt configu nie jest zapamiętywany jako
załatwiony**. Stary kod odhaczał plik, zanim spróbował go wczytać — jeden pechowy
odczyt zamrażał księgę aż do restartu.

Model podmieniany przez refreshera jest pilnowany zwykłym `mtime`, i to jest właściwy
wybór: plik ma megabajty (hash przy każdej świecy nie byłby darmowy), podmienia go
tylko jeden proces i nikt go nie kasuje.

---

## 8. Refresher: cotygodniowa bramka

`scripts/refresh.py`, w pętli `sleep 604800`:

1. dociąga świeże świece (przyrostowo),
2. trenuje **kandydata** bez ostatnich `validation_days` dni,
3. backtestuje go na tym oknie — danych, których nigdy nie widział — obok naiwnych
   kontroli na dokładnie tych samych barach,
4. **bramka**: promuje tylko kandydata, który nie jest katastrofą, bije „nie handluj"
   i bije **każdą** naiwną kontrolę,
5. po przejściu: trenuje finalny model na całości i zapisuje pod produkcyjną nazwą.

Bot łapie nowy plik przez `_maybe_reload_models` na najbliższej świecy — bez restartu.
Kod wyjścia: `0` = promocja, `2` = bramka odrzuciła (stary model zostaje), `1` = błąd.

Bramka porównywała kiedyś z „kup i trzymaj" — i to było prawie darmowe do przejścia
w spadającym rynku: kandydat, który ledwo handluje, zwraca ~0% i „bije" benchmark,
który stracił 17%. Naiwne kontrole są osiągalnymi alternatywami, więc ich pobicie
coś znaczy.

---

## 9. Panel (`dashboard/`)

Streamlit, **tylko do odczytu** w zakresie stanu ksiąg; pisze wyłącznie konfigurację.

- `app.py` — ekran główny, metryki, krzywe, przełącznik modułu
- `journals.py` — czytanie `*.jsonl` z cache'em kluczowanym **odciskiem pliku**, nie TTL.
  Streamlit przelicza cały skrypt przy każdym kliknięciu; bez tego przeciągnięcie
  suwaka re-parsowałoby cały dziennik kapitału. Klucz na treści, a nie czas, znaczy
  „nowy wiersz widać natychmiast, a nie po wygaśnięciu cache".
- `humanize.py` — liczby i zdarzenia na polskie zdania („kupił ETH za 100 $ — teraz +2 $")
- `price_view.py` — wykres kursu ze znacznikami transakcji; czyta `trades.jsonl` **i**
  otwarte pozycje ze `state.json`
- `config_view.py` — ekran ustawień; woła `auth.current_user()` przed każdym zapisem
- `research_view.py` — moduł 3 i przesiew korelacji, z ostatniego raportu w `models/reports/`
- `auth.py` — dziś zwraca `"local"` i `True`. To szew, nie zabezpieczenie: gdy pojawi
  się logowanie, zmienia się jedna implementacja, a nie każde miejsce zapisu.

---

## 10. Mapa katalogów

```
src/trademon/
  config.py, config_store.py   konfiguracja: model pydantic + bezpieczny zapis z panelu
  data/        ingestion.py    pobieranie przez CCXT (przyrostowe)
               storage.py      Parquet, wykrywanie dziur
               funding.py      funding rate (opcjonalne cechy)
  features/    engineering.py  26 (+4) cech, wyłącznie z przeszłości
  labeling/    triple_barrier.py
  models/      train.py        walk-forward + purge, LightGBM lub fallback
  backtest/    runner.py       event-driven, przez fills.py
               metrics.py      Sharpe, obsunięcie, ekspozycja, wynik od ryzykowanych
  execution/   fills.py        model kosztów — WSPÓLNY dla backtestu i produkcji
               executors.py    paper / live (CCXT)
  risk/        manager.py      sizing, sufit pozycji, kill-switch
  engine/      loop.py         Book + TradingEngine (moduł 1)
               state.py        RuntimeStore: state.json + JSONL
               notify.py       webhook (Discord/Slack)
  portfolio/   allocator.py    czyste funkcje rebalansu
               book.py         księga dzienna
               engine.py       pętla + --once / --backfill
               correlation.py  przesiew dywersyfikacji
  crosssec/    signal.py       momentum przekrojowe (moduł 3)
               backtest.py, validate.py, panels.py
  research/    lab.py          rozłączne okna, naiwne kontrole
               log.py          dziennik eksperymentów
  dashboard/   app.py + widoki

config/    config.yaml (baza, z komentarzami) + *.overrides.yaml (z panelu)
data/      Parquet per (giełda, symbol, interwał)
models/    *.joblib + reports/
runtime/   <wariant>/{state.json, trades.jsonl, equity.jsonl, alerts.jsonl}
           config_history.jsonl, experiments.jsonl, restart_requested
scripts/   download_data, train, backtest, refresh, portfolio_backtest,
           correlation_screen, crosssec_backtest, research/*
```

---

## 11. Czego ten system celowo nie robi

- **Nie handluje na świecy otwartej.** Nigdzie. Trzy miejsca odcinają ją niezależnie.
- **Nie zmienia struktury bez restartu.** Lepiej zejść na 20 sekund niż handlować
  konfiguracją, której połowa weszła.
- **Nie ma bazy danych ani API między procesami.** Cztery kontenery, jeden katalog,
  jeden pisarz na plik.
- **Nie wybiera zwycięskiego okna.** Raporty pokazują wszystkie okna, także te złe.
- **Nie modeluje kosztu funding** przy shortach na krypto (moduł 3 wprost to zastrzega)
  ani nie koryguje **błędu przetrwania** w uniwersum par.
- **Nie chroni panelu logowaniem** — jest przeznaczony na sieć lokalną. `auth.py`
  istnieje po to, żeby to kiedyś zmienić w jednym miejscu.
- **Nie wysyła prawdziwych zleceń bez świadomej zmiany** `mode: live` w konfiguracji
  i kluczy API w `.env`. Domyślnie wszystko jest papierowe.
