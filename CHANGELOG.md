# Historia zmian

Najnowsze na górze. Numer wersji z tego pliku musi zgadzać się z `__version__`
w `src/trademon/__init__.py` — pilnuje tego `tests/test_version.py`.

## 0.1.13 — 2026-08-10

- **Podniesienie sufitu ekspozycji pyta, zanim wejdzie.** Okno z potwierdzeniem łapie
  każdy wzrost iloczynu `position_pct × max_open_positions` — 5 × 10% → 10 × 10% tak
  samo jak 5 × 10% → 5 × 20% — i mówi to, czego ekran wcześniej nie mówił: że skutek
  przychodzi jedną świecą później, a **powrót do niższej wartości niczego nie zamyka**.
  Obniżenie limitu zapisuje się bez pytania.
- **Sekcja „Ryzyko" pokazuje kolejkę do zwolnionego miejsca**: ile par przekroczyło
  próg i zostało odrzuconych przez sam sufit, z najwyższym prawdopodobieństwem w tej
  grupie, osobno dla każdej księgi. Kill-switch celowo się nie liczy — jego odrzuceń
  podniesienie limitu nie odblokuje. Ta liczba ma sens dopiero od 0.1.12, kiedy silnik
  zaczął pytać model **przed** sprawdzeniem limitu.
- Powód, dla którego to powstało, opisany w `howitworks.md` §4.8: 9.08 o 17:51 UTC
  limit poszedł z 5 na 10 i wrócił o 22:43, ale świeca 20:00 zdążyła otworzyć cztery
  pozycje i podnieść `prog_050` z 50% na 90% konta. Zostały po cofnięciu ustawienia,
  trzy wyszły po bezpieczniku i **kosztowały 7,07 USDT — 51% całego obsunięcia**;
  rynek w tym czasie dał −1,60%, a uczciwa poprzeczka przy tej ekspozycji −1,04% wobec
  −1,30% księgi. Kontrola: `prog_065` i `ryzyko_100` nie dobrały wtedy ani jednej
  pozycji i spadły −0,90% / −1,34% — tyle było rynkiem.
- `journals.book_states` czyta `state.json` wszystkich ksiąg krypto; ekran ustawień
  potrzebuje żywego stanu, a nie może importować `app.py` (to `app` importuje
  `config_view`).
- Poprawiona nieaktualna tabela w §4.7: trzy księgi progowe mają dziś sufit 5 × 10%,
  nie 3 × 10%.

## 0.1.12 — 2026-08-10

- **Ciemna linia na „Jak to szło" idzie teraz za ekspozycją bota świeca po świecy**
  (`matched_exposure_curve`), zamiast skalować cały koszyk jedną średnią z okna. Stara
  wersja rozjeżdżała się dokładnie wtedy, kiedy ustawienia ryzyka zmieniały się
  w locie: książka, która trzy tygodnie chodziła na 30%, a potem na 90%, dostawała
  benchmark dla ~40% — nietrafiony w obie połowy. Gorzej, ta średnia zależała od
  wybranego zakresu, więc **przełączenie 7 dni / 30 dni zmieniało nie tylko okres, ale
  i samą miarę** (31% vs 39% ekspozycji), a werdykt „bot bije / nie bije" potrafił się
  przez to odwrócić. Teraz kształt linii w danym odcinku jest ten sam niezależnie od
  okna, a podniesienie ryzyka widać w benchmarku od razu.
- Ekspozycja wchodzi do wzoru **opóźniona o świecę**: silnik zapisuje `cash` przy
  zamknięciu świecy, więc ta z indeksu `t` wie już, jak `t` poszło — bez przesunięcia
  benchmark handlowałby ruchem, na którym jest mierzony.
- **Podpis pod wykresem pokazuje obie liczby ekspozycji** — średnią z okna i stan
  bieżący. Nagłówek czyta chwilowe `(equity-cash)/equity` ze `state.json`, wykres
  średnią z księgi, i po zmianie ustawień te dwie liczby rozjeżdżały się bez słowa
  wyjaśnienia (90% w nagłówku, 31% pod wykresem).
- `buy_hold_curve` traci parametr `exposure` — jasna linia zawsze była wywołaniem
  domyślnym, a ciemna ma teraz własną funkcję.

## 0.1.11 — 2026-08-10

- **Plansza rośnie z 10 do 18 par USDT** (dochodzą DOT, TRX, ATOM, BCH, XLM, UNI,
  ETC, NEAR), a `max_open_positions` z 3 na **5**. Powód był widoczny w księgach:
  `prog_050` z limitem podniesionym w panelu do 10 trzymał **9 z 10 par** przy 99 USDT
  wolnej gotówki — plansza była wyczerpana.
- **Najważniejszy wynik pomiaru dotyczy limitu, nie planszy.** Poszerzenie płaci
  **wyłącznie przy ciasnym limicie**: +0,78 pp na okno przy limicie 3, −0,31 pp przy 5
  i **−2,32 pp przy 10**. Sam limit to najsilniejszy zmierzony efekt w całym projekcie:
  na osiemnastu parach limit 3 bije limit 10 o **+4,49 pp na okno, w 8 oknach na 10,
  t = +2,73** (przy `best_first` t = +3,50) — jedyny wynik tutaj przekraczający zwykły
  próg istotności. Mechanizm: szeroka plansza jest pulą **do wybierania**, nie listą do
  zapełnienia; przy dziesięciu slotach książka bierze wszystko, co zasygnalizuje (2609
  transakcji zamiast 1713 przy tej samej ekspozycji 80%), więc dodatkowe pary dokładają
  wyłącznie obrót i prowizje. Wdrożone 18 par + limit 5: poszerzenie jest przy piątce
  neutralne, ale piątka bije dziesiątkę na obu planszach, a trójka trzymałaby w rynku
  o połowę mniej kapitału.
- **Nowy backtest całej książki (`backtest/book.py`) i skrypt `scripts/book_backtest.py`.**
  `runner.py` daje każdej parze osobny portfel i nieograniczone sloty, więc przy takim
  liczeniu dorzucenie par podnosi średnią z definicji — dopisuje kolejny rachunek, a nie
  konkurenta. `book.py` liczy jedną gotówkę, jeden limit i ten sam `RiskManager` co
  silnik, i zwraca liczbę, której `runner.py` nie umie wyprodukować: ile sygnałów
  książka wyrzuciła z braku wolnego slotu. Tryb `maker` odrzuca wyjątkiem, bo nie ma
  w silniku odpowiedzi na to, czy niewypełniony limit trzyma slot. Bramka promocji
  w `refresh.py` została nietknięta — mierzy inne pytanie.
- **Zmierzone i odrzucone: oddawanie slotu najsilniejszemu sygnałowi.** Nowy
  `scripts/research/universe.py` — model trenowany od nowa przed każdym oknem, osobno
  dla każdej planszy, bo poszerzenie planszy poszerza też zbiór treningowy i to jest
  część zmiany, a nie confounder do wyzerowania. Ranking po prawdopodobieństwie daje
  **−0,6 do +0,7 pp**, pięć z sześciu porównań na zero albo minus — nie płaci nawet
  tam, gdzie limit odrzuca 3000 kandydatów. Najprostsze wyjaśnienie: prawdopodobieństwo
  z modelu jest zbyt słabo informatywne, żeby się nim dało sortować. Nie wdrożono.
- **Skrypt badawczy nie może po cichu porównywać rzeczy z nią samą.** Pierwsza wersja
  `universe.py` brała wąskie ramię z `config.exchange.symbols` — więc w chwili, w której
  jego własny wniosek trafił do configu, „base" i „wide" stały się tymi samymi
  osiemnastoma parami i skrypt wydrukował schludną tabelkę czterech identycznych co do
  ostatniego miejsca po przecinku wierszy. Obie plansze są teraz przypięte w kodzie
  (`--base` / `--add`), a identyczne ramiona kończą się błędem zamiast raportem.
- **`risk_blocked` przestaje kłamać i zaczyna nieść liczbę.** `_maybe_enter` pyta model
  **przed** sprawdzeniem limitu. Przy starej kolejności zablokowana para nie miała jeszcze
  policzonego prawdopodobieństwa, więc panel pokazywał „wstrzymany limitem ryzyka" obok
  pustej kolumny `p(long)` — co mogło znaczyć zarówno odrzuconą okazję 0,92, jak i
  niewypał 0,31; a pod tym samym powodem lądowały pary daleko poniżej progu, które i tak
  by nie weszły. Teraz `risk_blocked` to zawsze realnie odrzucona okazja, z jej
  prawdopodobieństwem i stroną obok. Żadna transakcja się nie zmienia — `can_open` dalej
  bramkuje każde wejście, tylko o jedno wywołanie później.
- Dziennik zdarzeń w panelu pokazuje 60 wpisów zamiast 30: księga z pięcioma slotami
  potrafi na jednej świecy zamknąć pięć pozycji i otworzyć pięć nowych, więc trzydzieści
  wierszy to były trzy świece, czyli pół doby.
- Naprawione przy okazji: `book.py` stemplował wejście świecą **sygnału**, a nie świecą
  **wypełnienia** (wejście jest po `open` następnego bara, jak w `runner.py`), przez co
  dziennik transakcji cofał każde wejście o jedną świecę i pozycje wyglądały na
  zachodzące na siebie mimo trzymanego limitu.

## 0.1.10 — 2026-08-09

- **Zdarzenia mają godzinę zamknięcia świecy, a nie jej otwarcia.** `bar["timestamp"]`
  z ccxt to czas *otwarcia*, a świeca trafia do silnika dopiero po domknięciu —
  więc każdy wpis w dzienniku, każda transakcja i każdy punkt krzywej kapitału był
  cofnięty o cały timeframe. Przy 4h wyglądało to tak, jakby bot przestał
  cokolwiek robić cztery godziny temu: transakcje ze świecy zamkniętej o 22:00
  leżały pod godziną 18:00. Poprawka to jedna linijka w `Book.on_candle`, ale
  przechodzi przez nią wszystko — dziennik, `trades.jsonl`, `equity.jsonl`,
  `deadline` pozycji, `updated_at` w `state.json` i granica doby dla kill-switcha.
  `last_candle_ts` zostaje czasem otwarcia, bo `bot_status` i `live_drift` same
  dodają timeframe; dwie konwencje w sąsiednich linijkach są teraz opisane
  komentarzem. Jednorazowy koszt: na styku starych i nowych zapisów historia
  equity przeskakuje o 4 h, a pozycje otwarte przed wdrożeniem mogą wygasnąć
  o jedną świecę wcześniej.
- **Wykres pokazuje ostatnie wejścia.** Znaczniki transakcji były przycinane do
  prawej krawędzi notowań, a notowania dociąga `refresher` raz na tydzień —
  więc wszystko, co bot zrobił od ostatniego pobrania, znikało z wykresu.
  Przycinamy już tylko od lewej (wybrany zakres). Sama linia kursu też nie
  kończy się w zeszłym tygodniu: `crypto_prices` przedłuża zapisane świece
  zamknięciami, które silnik i tak journaluje przy equity.
- Wpis o zmianie ustawień ma w dzienniku ikonę ⚙️ zamiast gołej kropki,
  a lista zdarzeń pokazuje 30 wierszy zamiast 15 — przy dziesięciu parach
  i dziesięciu pozycjach jedna świeca potrafi zapisać kilkanaście wierszy.

## 0.1.9 — 2026-08-08

- `strategy.timeout_rollover` nazywa się teraz `strategy.rollover` i ma jawny
  próg kosztowy: przedłuża, gdy przewaga ceny wyjścia nad ceną ponownego wejścia
  nie pokrywa dwóch prowizji. Przy timeoucie obie ceny to zamknięcie tej samej
  świecy, więc warunek jest zawsze spełniony — zachowanie bez zmian. Stop-loss
  nie przedłuża nigdy: to porzucenie limitu ryzyka, nie oszczędność.
- **Ustalenie, przez które ta zmiana jest mniejsza, niż miała być.** Rozszerzenie
  przedłużania na wyjścia po zysku wyglądało w backteście rewelacyjnie: średni
  wynik +146,6% → **+182,8%** na 5,5 roku i dziesięciu parach, każda para na
  plusie. To nie jest przewaga, tylko zaglądanie w przyszłość. TP wykrywamy
  z maksimum świecy — to dotknięcie **wewnątrz** świecy, wypełniane po cenie
  bariery, czyli transakcja, która zaszła, zanim świeca się domknęła. Rezygnacja
  z niej po zobaczeniu, gdzie świeca zamknęła, używa informacji z przyszłości.
  Uczciwa wersja, ograniczona do timeoutu, daje +146,56% → +146,67% i 18 USDT
  mniej prowizji — trzysta razy mniej, i tyle właśnie jest prawdziwe.
- Zostaje przy tym prawdziwy problem do rozstrzygnięcia osobno: silnik budzi się
  wyłącznie na zamknięciu świecy, a mimo to rozlicza TP po cenie bariery. To
  optymistyczne założenie dotyczy całej dotychczasowej historii pomiarów.

## 0.1.8 — 2026-08-08

- **Wykres kursu pokazuje pozycję, którą bot trzyma teraz** — jako zielone kółko
  w miejscu i czasie wejścia, obok trójkątów transakcji zakończonych. Wcześniej
  znaczniki brał wyłącznie z `trades.jsonl`, do którego silnik dopisuje wiersz
  dopiero przy **zamknięciu** pozycji, więc wykres opowiadał historię odwrotną do
  kafelka nad nim: przy LINK (kupionym i nigdy nie sprzedanym) nie było żadnych
  znaczników, a przy LTC i ADA ostatnim znacznikiem było czerwone wyjście —
  z tej samej świecy, w której bot natychmiast wszedł ponownie.

## 0.1.7 — 2026-08-08

- **Zmiana ustawień w panelu naprawdę dociera do silnika.** Przywrócenie wartości
  domyślnej kasuje `config.overrides.yaml` (nie ma już czego nadpisywać), a czujnik
  patrzył wyłącznie na datę modyfikacji tego pliku: zniknięcie dawało „0", czyli
  nigdy nie „nowszy". Bot do końca życia kontenera handlował więc na poprzednich
  parametrach, choć panel pokazywał już nowe — w praktyce „maksimum otwartych
  pozycji" wróciło na 3, a bot dalej otwierał 5, czyli 50% zamiast 30% ekspozycji.
  Silnik porównuje teraz **treść** `config.yaml` i nakładki, więc widzi każdą
  zmianę: skasowanie pliku, dwa zapisy w tej samej sekundzie, wgranie starszej
  wersji — a także ręczną poprawkę w samym `config.yaml`, której wcześniej nie
  umiał przyjąć.
- Nieudany odczyt konfiguracji nie jest już zapamiętywany jako załatwiony. Silnik
  odhaczał plik, *zanim* spróbował go wczytać, więc jeden pechowy odczyt zamrażał
  księgę na starych ustawieniach aż do restartu.
- **Panel potwierdza zapis.** Komunikat „Zapisano…" ginął w przeładowaniu strony
  zaraz po kliknięciu, więc zapisanie zmiany wyglądało identycznie jak kliknięcie
  w próżnię. Teraz przeżywa przeładowanie tak samo jak potwierdzenie restartu.
- **Widać, czym silnik naprawdę handluje.** `state.json` zapisuje wartości
  parametrów, które księga w tej chwili egzekwuje, a ekran ustawień ostrzega, gdy
  silnik rozjechał się z dyskiem. Ostrzeżenie czeka na świecę, przy której zmiana
  powinna była wejść, i porównuje każdą księgę z jej własnym wariantem — żeby nie
  straszyć zaraz po zapisaniu ani nie mylić `ryzyko_100` z awarią.

## 0.1.6 — 2026-08-08

- Dziennik zdarzeń **sam domyka swoje alarmy**. Gdy bot odzyska łączność, dopisuje
  „✅ połączenie z giełdą wróciło" — także wtedy, gdy alarm otworzył poprzedni
  kontener, bo silnik sprawdza przy starcie, czy w dzienniku nie wisi niezamknięta
  awaria. Wcześniej trzeba było czekać na przypadkowe zdarzenie (przy świecach 4 h
  nawet kilka godzin), żeby przestać widzieć na górze „brak połączenia".
- Otwarty alarm i jego odwołanie różnią się ikoną (📡 kontra ✅), więc widać to
  przy przewijaniu, bez czytania treści.

## 0.1.5 — 2026-08-07

- Panel pokazuje pod statusem bota **żywy kontakt z giełdą** („kontakt z giełdą:
  przed chwilą" / „brak kontaktu od 47 min"). Liczony z `updated_at`, które ticker
  odświeża co 60 s wyłącznie po udanym zapytaniu — więc reaguje w minuty, a nie
  po godzinach jak zegar świec.
- To domyka lukę z 0.1.3: alert „brak połączenia z giełdą" zapisywał ten sam
  proces, który widział awarię, więc po restarcie kontenera odwołanie nigdy nie
  powstawało i w dzienniku wisiał alarm prawdziwy o przeszłości, a mylący co do
  teraz. Bicie serca nie może się w ten sposób zdezaktualizować.

## 0.1.4 — 2026-08-07

- Wycofane wymuszanie publicznych resolwerów DNS w `docker-compose.yml`. Teoria,
  która za tym stała (DSM zostawia w `/etc/resolv.conf` adres pętli zwrotnej),
  zmierzona na NAS-ie okazała się nieprawdziwa: stoi tam router, który odpowiada
  20/20 zapytań w 5 ms — szybciej niż jakikolwiek publiczny resolwer. Wpisanie
  `1.1.1.1` wypychało każde zapytanie przez NAT i psuło rozwiązywanie nazw
  z przerwami. Domyślne zachowanie Dockera jest tu i krótsze, i pewniejsze.
- Przewodnik wdrożenia każe teraz **najpierw zmierzyć** resolwer hosta, a dopiero
  potem cokolwiek ustawiać.

## 0.1.3 — 2026-08-07

- Silnik nie umiera już na chwilowym braku sieci przy starcie. Pobranie pierwszych
  świec jest ponawiane (5 s, potem coraz rzadziej, maks. co 5 min) zamiast wywalać
  proces — na NAS-ie kończyło się to 826 restartami w pięć godzin, bo
  `restart: unless-stopped` podnosił kontener prosto w ten sam błąd DNS. Zerwane
  i odzyskane połączenie trafia do dziennika zdarzeń (📡).
- Przerwany start nie kasuje stanu ksiąg. `restore()` odtwarza też ostatnie kursy
  i czas ostatniej świecy, a stan zapisuje się tylko wtedy, gdy silnik naprawdę
  ruszył. Wcześniej nadpisywał dobry `state.json` pustym — i to dlatego wykres
  gubił obie szare linie „kup i trzymaj", zostawiając płaski ogon linii bota.
- Status bota nie świeci na czerwono przez pierwsze godziny po restarcie:
  wczytanie historii świec liczy się jako odczyt rynku.
- Panel nie dorysowuje punktu „na żywo" bez cen, których benchmark nie ma z czego
  policzyć — wszystkie trzy linie kończą się w tym samym miejscu.
- `docker-compose.yml` ustawia kontenerom resolwery DNS. Wcześniej stał na to
  przepis w przewodniku, ale plik nakładkowy żył tylko na NAS-ie, poza repo — i po
  prostu zniknął.

## 0.1.2 — 2026-08-07

- Dziennik zdarzeń nie wywraca panelu na alercie bez instrumentu (np. zmiana
  konfiguracji). Wiersze dziennika wracają teraz bez pól, których nie miały —
  wcześniej pandas dorabiał je jako NaN, a NaN przechodził przez `if sym:`.

## 0.1.1 — 2026-08-07

- Panel pokazuje numer wersji pod tytułem, na każdym module.
- Wersja trzymana w jednym miejscu (`src/trademon/__init__.py`); `pyproject.toml`
  czyta ją przy budowaniu pakietu.

## 0.1.0

- Pierwsza wersja: silnik krypto-scalpera, zarządca portfela, badania, panel.
