# Jak to działa (od środka)

README opisuje **co** ten projekt robi i **jakie dał wyniki**. Ten plik opisuje
**mechanizm**: jaką drogę przechodzi jedna świeca od giełdy do zlecenia, jak wygląda
gra, którą bot faktycznie prowadzi (§4), kto pisze i kto czyta które pliki, i dlaczego
kilka rzeczy jest zrobionych inaczej, niż wyglądałaby wersja oczywista.

Sekcje 1–3 są o **budowie**. Sekcja 4 i podsekcje „Mechanika" w kolejnych rozdziałach
są o **zachowaniu**: co każdy komponent robi w kolejnych minutach, dniach i tygodniach,
i co robi w przypadkach, w których nic ciekawego się nie dzieje — bo to jest jego
domyślny stan.

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
   tylko do siostrzanego `config/config.overrides.yaml` (patrz §8).

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
  3. _maybe_reload_config()   – czy panel zmienił parametry? (§8)
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

## 4. Mechanika gry: co bot robi przy stole

Sekcja 3 opisuje, z czego bot jest zbudowany. Ta opisuje, w co on właściwie **gra** —
jakie ma zasady, co robi w typowej turze i co się dzieje w przypadkach brzegowych.

### 4.1 Zasady gry

| | |
|---|---|
| **Plansza** | 10 par USDT, każda niezależnie |
| **Tura** | zamknięcie świecy 4h — 6 tur na dobę na parę, 60 decyzji dziennie łącznie |
| **Ręka** | maksymalnie 3 otwarte pozycje jednocześnie, po 10% kapitału każda |
| **Limit stołu** | 1 pozycja na parę — nie ma dokładania ani uśredniania |
| **Kierunek** | domyślnie tylko long; `direction: long_short` włącza drugi model |
| **Koniec tury** | take-profit, stop-loss, timeout po 12 barach (2 dni) albo przedłużenie |
| **Wykluczenie z gry** | strata zrealizowana ≥ 3% kapitału z początku doby — do końca doby UTC |
| **Stawka** | wirtualna, dopóki `mode: paper` |

Bot nie ma dźwigni, nie ma trailing stopu, nie skaluje wejść i nie przenosi stopa na
poziom wejścia. Każda pozycja to **jeden zakład o ustalonej z góry wypłacie i ustalonym
z góry terminie**. To jest świadomy wybór: przy przewadze bliskiej zeru każdy dodatkowy
mechanizm dokłada tylko parametr do dopasowania.

### 4.2 Życie jednej pozycji, z liczbami

Kapitał 1000 USDT, ETH po 2000, ATR(14) = 40 USDT (2% ceny), model daje `p_long` = 0,58
przy progu 0,55.

```
1. WIELKOŚĆ      1000 × 10%  = 100 USDT  →  100 / 2000 = 0,05 ETH
2. WEJŚCIE       poślizg 2 bps: 2000 × 1,0002 = 2000,40
                 prowizja 0,1%: 0,10 USDT      →  z gotówki schodzi 100,12
3. BARIERY       TP = 2000,40 + 1,5 × 40 = 2060,40   (+3,0%)
                 SL = 2000,40 − 2,0 × 40 = 1920,40   (−4,0%)
                 deadline = teraz + 12 × 4h = 48 godzin
4. CZEKANIE      co świecę: czy high ≥ TP? czy low ≤ SL? czy minął deadline?
                 świeca dotykająca OBU barier liczy się jako SL
5. WYJŚCIE (TP)  sprzedaż po 2060,40 × 0,9998 = 2059,99, prowizja 0,10
                 PnL = 0,05 × (2059,99 − 2000,40) − 0,10 − 0,10 ≈ +2,78 USDT
```

Runda kosztuje **0,24% nominału** (2 × prowizja 0,1% + 2 × poślizg 0,02%), czyli
tu ~0,24 USDT. Dlatego raport backtestu drukuje `median_tp_pct` obok
`round_trip_cost_pct`: jeśli mediana odległości do TP nie przekracza kosztu rundy
z zapasem, strategia nie ma z czego żyć — i dokładnie to unieważniło pomysł grania
na świecach 1-minutowych.

Pozycja idzie do `state.json` natychmiast. Do `trades.jsonl` trafia dopiero w kroku 5 —
przy zamknięciu (§3.9).

### 4.3 Arytmetyka barier: dlaczego próg jest tam, gdzie jest

TP = 1,5 ATR, SL = 2,0 ATR. Bot **ryzykuje więcej, niż celuje** — więc sama wygrana
częściej niż przegrana nie wystarcza:

```
próg opłacalności = SL / (TP + SL) = 2,0 / 3,5 ≈ 57% trafień
```

To nie jest przypadek, że model jest uczony dokładnie na tym zdarzeniu: etykieta
triple-barrier (§3.3) brzmi „TP przed SL" przy tych samych mnożnikach, więc
`prob_threshold` porównuje się bezpośrednio z tym progiem. Domyślne 0,55 leży
**poniżej** 57% — bot świadomie wpuszcza zakłady z lekko ujemną wartością oczekiwaną
z samych barier, w zamian za częstsze granie.

Dwa zastrzeżenia, żeby ten rachunek nie brzmiał ostrzej niż jest: dotyczy tylko wyjść
przez bariery (timeout wychodzi po cenie zamknięcia, gdziekolwiek ona jest), i zakłada
skalibrowany model. Ale wyjaśnia, czemu `prob_threshold` to najczęściej ruszany
parametr w panelu, i czemu jeden z wariantów A/B testuje 0,65.

### 4.4 Co bot robi przez większość czasu: nic

To jest najważniejsza część mechaniki i najłatwiejsza do przeoczenia. W backteście
pozycja jest otwarta na **6–11% świec na parę**. Przez pozostałe ~90% czasu tura
kończy się wpisem w `signals[symbol]` i niczym więcej.

Ranking powodów, od najczęstszego:

| Powód | Co znaczy |
|---|---|
| `below_threshold` | model policzył prawdopodobieństwo, wyszło za mało — **stan normalny** |
| `in_position` | ta para jest już zajęta |
| `risk_blocked` | trzy pozycje otwarte albo kill-switch |
| `warmup` | bufor krótszy niż 300 barów (po świeżym starcie bez historii) |
| `features_nan` / `no_atr` | dziura w danych albo świeca bez zakresu |

Panel czyta to jeden do jednego w zakładce „Model: dlaczego nie handluje". Nuda
w dzienniku zdarzeń nie jest awarią — to jest domyślny tryb pracy tej strategii.
Skutek uboczny: **~70–80% konta stoi w gotówce**, i to właśnie ten fakt wymusza dwa
benchmarki w panelu zamiast jednego (§7).

### 4.5 Dzień, w którym bot przegrywa

Kill-switch liczy tylko **stratę zrealizowaną** od początku doby UTC, licząc od
kapitału z jej początku. Po przekroczeniu 3%:

- nowe wejścia są zablokowane na wszystkich parach do północy UTC (`can_open` zwraca
  `risk_blocked`);
- otwarte pozycje **dalej żyją** — TP, SL i timeout działają normalnie, bo zamykanie
  jest wyjściem z ryzyka, nie wchodzeniem w nie;
- przedłużenie pozycji (rollover) jest wyłączone, bo zastępuje wejście, które i tak
  byłoby zablokowane;
- do `alerts.jsonl` idzie jeden alarm `kill_switch`, nie jeden na świecę.

Dzień jest częścią stanu księgi, więc restart kontenera w środku złego dnia **nie
kasuje limitu** — `RiskManager.restore` odczytuje datę, kapitał początkowy doby
i zrealizowany wynik.

Osobno działa alarm obsunięcia: przy spadku o `drawdown_alert_pct` od szczytu leci
jedno powiadomienie, a próg odwieszenia jest o połowę niższy niż próg alarmu —
histereza, żeby księga drgająca wokół granicy nie wysyłała alarmu co świecę.

### 4.6 Rytm doby: co się dzieje między świecami

Silnik nie stoi bezczynnie między decyzjami. Cztery pętle chodzą równolegle,
z bardzo różnymi zegarami:

```
co 5 s     REST polling (fallback, gdy WebSocket padł) — szuka nowej zamkniętej świecy
co 10 s    _restart_watcher — czy panel poprosił o restart?
co 60 s    _ticker_loop — świeże ceny → mark_to_market → state.json.  NIE HANDLUJE
co 4 h     zamknięcie świecy → on_candle → jedyny moment, w którym powstaje zlecenie
```

Stąd bierze się pozorna sprzeczność w panelu: „ile masz" zmienia się co minutę,
a transakcje pojawiają się kilka razy na tydzień. Wycena jest ciągła, decyzja jest
dyskretna.

Przy zerwanej sieci rytm się rozjeżdża świadomie: każda pętla ma własny backoff
(5 s → 10 s → … → 300 s), po trzeciej nieudanej próbie startu do dzienników idzie
alarm `connection` z `ok=False`, a po powrocie — para z `ok=True` (§3.8).

### 4.7 Cztery księgi grają tę samą rozdaną kartę

`variants:` w konfiguracji to nie cztery boty. To **jeden strumień świec i cztery
niezależne portfele**, które dostają dokładnie te same dane w tej samej chwili:

| Księga | Próg | Sizing | Sufit ekspozycji |
|---|---|---|---|
| `prog_050` (główna) | 0,50 | 3 × 10% | 30% |
| `prog_055` | 0,55 | 3 × 10% | 30% |
| `prog_065` | 0,65 | 3 × 10% | 30% |
| `ryzyko_100` | 0,50 | 5 × 20% | **100%** |

Trzy pierwsze różnią się wyłącznie progiem, więc różnica w ich krzywych kapitału jest
różnicą progu i niczego więcej. Czwarta ma **identyczny sygnał co `prog_050`** —
zmienia się tylko apetyt. To jest eksperyment z z góry postawioną tezą: na zmierzonych
zwrotach dziennych optymalna frakcja Kelly'ego wychodzi ~0,47, więc 100% ekspozycji
jest mniej więcej dwa razy za daleko, gdzie kara za wariancję (rośnie z kwadratem)
przegania zysk (rośnie liniowo). `primary_variant` przypina `prog_050` do ekranu
głównego, żeby ta księga nigdy nie trafiła na niego jako „Twój portfel".

Każda księga ma własny katalog w `runtime/`, własną gotówkę i własny kill-switch.
Wspólne mają: świece, model i egzekutora.

---

## 5. Moduł 2: zarządca portfela

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

### 5.1 Mechanika: jak wygląda rok w życiu tej księgi

Zasady gry są odwrotnością modułu 1 — nie ma prognozy, jest **pasmo i termin**:

| | |
|---|---|
| **Plansza** | 3 ETF-y: SPY 50% / TLT 30% / GLD 20% |
| **Tura** | jeden dzień giełdowy |
| **Wyzwalacz** | 90 dni od ostatniego rebalansu **LUB** dowolna waga odchylona o ≥ 5 pkt proc. |
| **Ruch** | sprzedaj to, czego jest za dużo; kup to, czego za mało; wróć do wag docelowych |
| **Koniec gry** | nie ma — księga jest zawsze w 100% zainwestowana |

Typowy rok to **2–4 ruchy**. Reszta dni kończy się dopisaniem wiersza do `equity.jsonl`
i niczym więcej. Przykład jednej tury, która coś zmienia:

```
Wartość 11 000 $ po dobrym kwartale akcji:
  SPY  6 160 $  (56,0%)   cel 50%  →  5 500 $    SPRZEDAJ 660 $
  TLT  2 750 $  (25,0%)   cel 30%  →  3 300 $    KUP      550 $
  GLD  2 090 $  (19,0%)   cel 20%  →  2 200 $    KUP      110 $

max drift = 6,0 pkt ≥ 5,0  →  rebalans
sprzedaże idą pierwsze, żeby miały czym sfinansować kupna
```

Zwróć uwagę, co się właśnie stało: bot **sprzedał to, co rosło**, i dokupił tego, co
spadało. To nie jest błąd, to jest cała strategia — i to samo jest powodem, dla którego
na 10 latach przegrywa z „kup i trzymaj" o 33 pkt, przycinając zwycięzcę w hossie,
a jednocześnie ma o 9,6 pkt płytsze obsunięcie. Wartością jest dyscyplina, nie alfa.

Trzy szczegóły zachowania, które łatwo przeoczyć:

- **Pierwszy dzień jest wyjątkiem.** Świeża księga trzyma 10 000 $ gotówki i nie ma
  driftu do zmierzenia, więc `on_day` wykonuje `initial_allocation` bezwarunkowo, poza
  regułą kadencji.
- **Kupno jest ograniczane gotówką**, a sprzedaż stanem posiadania (`settle_orders`).
  Prowizja nigdy nie wprowadzi księgi na debet, nawet gdy zaokrąglenia się nie zgadzają.
- **Filtr trendu jest wyłączony i taki ma zostać.** Włączony zamienia rebalanser
  w strategię: aktywo poniżej średniej 200-dniowej ląduje w TLT albo w gotówce. To jest
  pole do eksperymentów, nie ulepszenie — README pokazuje, że w hossie kosztuje zwrot.

---

## 6. Moduł 3: ranking przekrojowy (badanie)

Nie ma księgi ani kontenera — jest skrypt i raport. Sygnał to momentum
`lookback_days` z **pominięciem** ostatnich `skip_days` (najświeższy ruch ma skłonność
do odwrotu; liczenie go wmieszałoby sygnał rewersji w sygnał momentum).
`select_legs` przycina nogi tak, żeby się nie nakładały — przy wąskim uniwersum
5 long + 5 short z 8 nazw kupowałoby i sprzedawało to samo.

Ten sam kod chodzi na krypto i na ETF-ach, na **czterech rozłącznych oknach**, i raport
pokazuje wszystkie — bo trzy razy w tym projekcie „najlepszy" wynik z jednego okna
okazał się szumem.

### 6.1 Mechanika: jedna tura rankingu

```
co ~20 dni:
  1. policz wynik każdego z 25 (krypto) / 29 (ETF) aktywów:
     zwrot od −125 do −5 dnia  ← ostatnie 5 dni celowo pominięte
  2. posortuj; weź 5 najsilniejszych (long) i 5 najsłabszych (short)
  3. przytnij nogi, żeby się nie nakładały
  4. przebuduj koszyk do równych wag; koszty przez ten sam fills.py
  5. trzymaj przez kolejne 20 dni, nie patrząc na nic
```

Trzy różnice w zachowaniu wobec modułu 1, które są istotą tego badania: zakład dotyczy
**różnicy między aktywami**, a nie kierunku rynku; nie ma stop-lossa ani take-profitu
(pozycja żyje dokładnie do następnego przerankowania); i nie ma tu żadnego uczenia —
sygnałem jest jawny wzór, nie model.

Dlatego poprzeczka jest inna dla każdego wariantu: long-only mierzy się z koszykiem
kup&trzymaj, a long-short z **gotówką** — książka o ekspozycji netto 0,4% jest
praktycznie neutralna rynkowo, więc porównanie z w pełni długim koszykiem zawyżałoby
ją w każdym spadku.

---

## 7. Backtest i uczciwość pomiaru

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

## 8. Konfiguracja: co wchodzi na gorąco, a co wymaga restartu

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

### 8.1 Mechanika: co się dzieje po kliknięciu „Zapisz"

```
panel                                        silnik (każda z 4 ksiąg, osobno)
─────                                        ────────────────────────────────
1. walidacja pydantic (scalony config)
2. zapis config.overrides.yaml (atomowy)
3. wiersz do config_history.jsonl
   (kto, kiedy, z czego na co)
4a. pole HOT      → koniec, czekaj             ...co świecę: hash treści się zmienił?
                                               → wczytaj, porównaj pole po polu
                                               → podmień self.cfg, alarm „zmieniono
                                                 ustawienia: prob_threshold: 0,55 → 0,60"
                                               → od tego bara handluje po nowemu
4b. pole RESTART  → dopisz flagę               ...co 10 s: flaga nowsza niż mój start?
    runtime/restart_requested                  → zapisz księgi, anuluj feedy, wyjdź
                                               → Docker wskrzesza, restore() wraca
                                                 z gotówką i pozycjami
```

Zmiana jest widoczna z drugiej strony: `state.json` niesie `live_config` — parametry,
które księga **w tej chwili egzekwuje** — a ekran ustawień porównuje je z dyskiem
i ostrzega przy rozjeździe. Ostrzeżenie czeka na świecę, przy której zmiana powinna
była wejść, i porównuje każdą księgę z jej własnym wariantem, żeby nie straszyć zaraz
po zapisie ani nie mylić `ryzyko_100` z awarią.

Zmiana parametrów w locie robi z krzywej kapitału mieszankę dwóch strategii — i to jest
powód istnienia dziennika z punktu 3. Panel rysuje szew, zamiast po cichu uśrednić.

---

## 9. Refresher: cotygodniowa bramka

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

### 9.1 Mechanika: co dzieje się w tygodniu, w którym bramka odrzuca

Domyślnym wynikiem tego rytuału jest **„nic się nie zmienia"** — i tak ma być.

```
tydzień N     dociągnięcie danych  →  trening kandydata  →  backtest OOS
              kandydat −0,38%  vs  „nic nie rób" +0,00%   →  ODRZUCONY
              models/*.joblib nietknięte, bot handluje dalej starym modelem
              runtime/refresh_status.json: {"status": "gate_failed", "detail": "..."}
              kod wyjścia 2; docker-compose loguje komunikat i śpi 7 dni
```

Ostatni realny przebieg (2026-08-07) wyglądał dokładnie tak. Trzy konsekwencje warte
wypowiedzenia:

- **Bot nigdy nie stoi z powodu odrzucenia.** Model produkcyjny jest niezależnym
  plikiem; kandydat powstaje obok i ginie, jeśli nie przejdzie.
- **Podmiana nie wymaga restartu ani synchronizacji.** Refresher zapisuje plik,
  a każda księga zauważa nowy `mtime` przy najbliższej świecy (§8, akapit o modelu).
  Cztery księgi mogą przełączyć się na różnych barach — i to nie szkodzi, bo model
  jest bezstanowy.
- **Odrzucenie jest widoczne w panelu**, a nie tylko w logu kontenera:
  `refresh_status.json` czyta zakładka „Zdrowie". Bramka, o której nikt się nie
  dowiaduje, po kilku miesiącach nie różni się od bramki wyłączonej.

Ten sam plik jest jedynym pisarzem `data/` po stronie modułu 1: dociąganie świec
w refresherze ustala też, ile historii bot w ogóle kiedykolwiek zbierze
(`model.train_window_days`).

---

## 10. Panel (`dashboard/`)

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

### 10.1 Mechanika: cykl życia jednego kliknięcia

Streamlit nie ma zdarzeń — ma **przeliczenie całego skryptu od nowa** przy każdej
interakcji i przy każdym auto-odświeżeniu (15 s, na telefonie 60 s, bo 4h świeca
zamyka się sześć razy na dobę i częstsze pytanie kosztuje tylko transfer).

```
klik / tik odświeżenia
   → app.py leci od pierwszej linii
   → load_config()                       (tanie)
   → journals.load_*()                   ← cache kluczowany ODCISKIEM PLIKU
        plik się nie zmienił → z cache, zero parsowania
        silnik dopisał wiersz → parsuj i pokaż od razu
   → st.session_state trzyma to, co wybrał człowiek
        (rozwinięty instrument, zakres 7d/30d, moduł)
   → render
```

Dwie decyzje wynikające wprost z tego modelu:

- **Cache na treści, nie na czasie.** TTL dałby okno, w którym panel pokazuje stan
  sprzed chwili, choć plik jest już nowy. Odcisk pliku znaczy „nowy wiersz widać przy
  najbliższym odświeżeniu, ani sekundy później".
- **Wybór musi żyć w `session_state`.** Bez tego odświeżenie co 15 s zamykałoby
  rozwinięty wykres kursu — element interfejsu zamknąłby się sam, zanim ktokolwiek
  zdążyłby na niego spojrzeć.

Panel nigdy nie liczy na żywo niczego ciężkiego. Zakładka „Badania" czyta **ostatni
zapisany raport** z `models/reports/` i przelicza wyłącznie na danych z dysku, na
wyraźne żądanie — pobieranie w trakcie renderowania zablokowałoby cały ekran.

Czego panel nie może z definicji: uruchomić kontenera, zabić bota, zamknąć pozycji.
Ma dokładnie dwa kanały wpływu na silnik — nakładkę konfiguracji i flagę restartu (§8).
Gniazda Dockera nie ma i mieć nie powinien.

---

## 11. Mapa katalogów

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

## 12. Czego ten system celowo nie robi

- **Nie handluje na świecy otwartej.** Nigdzie. Trzy miejsca odcinają ją niezależnie.
  Ticker odświeża wycenę co minutę i nie ma prawa niczego kupić.
- **Nie uśrednia, nie dokłada, nie przesuwa stopa.** Jedna pozycja na parę, wypłata
  i termin ustalone przy wejściu (§4.1). Każdy dodatkowy mechanizm to kolejny parametr
  do dopasowania przy przewadze bliskiej zeru.
- **Nie używa dźwigni.** Short jest liczony po futuresowemu (margin = nominał wejścia),
  ale w backteście i na papierze; na spocie nie da się go wykonać.
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
