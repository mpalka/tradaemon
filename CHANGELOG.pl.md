# Historia zmian

*[English](CHANGELOG.md) · Polski*

Najnowsze na górze. Numer wersji z tego pliku musi zgadzać się z `__version__`
w `src/tradaemon/__init__.py`, a angielska historia zmian musi obejmować te same wersje —
pilnuje obu rzeczy `tests/test_version.py`.

## 0.2.1 — 2026-08-31

- **Pakiet nazywa się `tradaemon`, nie `trademon`.** Projekt odzywał się na trzy pisownie
  naraz: repozytorium to `Tradaemon`, import `trademon`, a dokumentacja pisała
  `TraDaemon`. Prawdziwą niespójnością było brakujące „a", a publiczne repozytorium to złe
  miejsce, żeby je trzymać. `src/trademon/` to teraz `src/tradaemon/`, a za tym idą
  wszystkie importy, komendy i ścieżki — `python -m tradaemon.engine`, `streamlit run
  src/tradaemon/dashboard/app.py`. Stylizowana nazwa wyświetlana zostaje jako
  **TraDaemon**, zgodnie z tą samą konwencją, którą stosuje PyTorch i podobne projekty:
  identyfikator małymi literami, znak firmowy z wielkimi.
- Starsze wpisy w historii zmian też przepisano na nową ścieżkę modułu. Historia cytująca
  ścieżki, które już nie istnieją, nie jest uczciwsza — jest tylko mniej użyteczna.
- **Istniejące wdrożenie nie wymaga zmiany nazwy katalogu.** Nazwa katalogu nadrzędnego
  jest kosmetyczna — pakiet zmienia nazwę w środku, a `docker-compose.yml` i `Dockerfile`
  już wskazują nowe ścieżki. Wysłanie źródła do katalogu, który już masz, i przebudowa to
  cała aktualizacja. Zmiana nazwy jest opcjonalna i nie jest darmowa: nazwa projektu
  w Compose bierze się z katalogu, więc `/volume1/docker/tradaemon` dałoby
  `tradaemon-bot-1` i nową sieć `tradaemon_default` — co ma znaczenie, jeśli reguła zapory
  DSM jest przypięta do starej podsieci. Na żywej księdze zostaw jak jest.

## 0.2.0 — 2026-08-31

Wydanie, po którym to repozytorium da się opublikować. Trzy rzeczy musiały być prawdziwe,
zanim ktokolwiek inny mógł z niego skorzystać, a jedna z nich była błędem niewidocznym od
pierwszego commita.

- **Klon tego repozytorium się nie importował.** `.gitignore` miał gołe wpisy `data/`
  i `models/`, a te pasują do katalogu o takiej nazwie na **dowolnej** głębokości — więc
  `src/tradaemon/data/` (4 pliki) i `src/tradaemon/models/` (2 pliki) nigdy nie trafiły do
  gita. Są importowane z kilkunastu miejsc, w tym z silnika, backtestera i panelu. Nikt
  tego nie zauważył, bo pliki istnieją na maszynie, na której projekt powstał. Każdy
  katalog artefaktów najwyższego poziomu jest teraz zakotwiczony ukośnikiem, a sześć
  plików jest w gicie. Doszedł też `scripts/research/prob_calibration.py`: nigdy nie był
  scommitowany, a `config/config.yaml` i historia zmian cytują go z nazwy.
- **Licencja MIT i zastrzeżenie mówiące, czym to jest.** `LICENSE` plus `DISCLAIMER.md`
  w obu językach: handel na papierze, brak porady inwestycyjnej, brak gwarancji i to, że
  panel nie ma logowania. `pyproject.toml` niesie licencję i klasyfikatory.
- **Panel i dokumentacja mówią po angielsku tak samo jak po polsku.** Nowy moduł
  `tradaemon.i18n` i dwa katalogi komunikatów w `tradaemon.locales` — zwykłe słowniki, bez
  gettextu, bez nowej zależności. Panel wybiera język na sesję (prawy górny róg albo
  `?lang=`), co ma znaczenie, bo jeden proces Streamlita obsługuje kilku widzów; silnik,
  webhook i drukowane raporty czytają `display_language` z konfiguracji, bo nie mają kogo
  zapytać. Polski zostaje domyślny i źródłowy. `tests/test_i18n.py` wywala się, gdy
  katalogi się rozjadą, gdy brakuje klucza użytego w kodzie albo gdy `{placeholder}` ginie
  w tłumaczeniu.
- **Alerty są zapisywane jako `msg_key` + `params`, a nie jako gotowe zdanie.** To dzięki
  temu panel potrafi narysować tę samą awarię w obu językach. Wyrenderowane zdanie nadal
  jest zapisywane, bo webhook i log nie mają kogo zapytać — i dlatego, że każda linia
  leżąca już w `alerts.jsonl` działającego wdrożenia ma wyłącznie to pole.
  `humanize.event_line` się na nie cofa, więc miesiące istniejącej historii zostają
  czytelne, zamiast zamienić się w kolumnę gołych kluczy.
- **Cztery rzeczy, które popsułyby się po cichu, gdyby je zwyczajnie przetłumaczyć.**
  Wartości logiczne na ekranie ustawień były kodowane *polskim słowem*
  (`raw == "włączony"`), więc angielska etykieta zamieniłaby każdy zapis `rollover`
  i `trend.enabled` na False; widget niesie teraz prawdziwe booleany i tłumaczy je
  wyłącznie na wyświetlanie. `?layout=telefon` to parametr URL opisany w README, więc
  wewnętrzne kody stały się niezależne od języka, a polskie pisownie działają dalej jako
  aliasy. Werdykty w `models/reports/*.csv` (`KANDYDAT`, `PUŁAPKA`, …) to **dane** — każdy
  zapisany raport je trzyma, a panel po nich filtruje — więc zostają nieprzetłumaczone
  i zmieniają się tylko ich etykiety. A polskie nazwy kolumn w skryptach badawczych
  przeszły na angielskie, bo nikt ich nie odczytuje z powrotem.
- **Naprawione przy okazji: markdown Streamlita zjadał symbol waluty.** Podpis wymieniający
  dwie kwoty zawiera dwa `$`, a Streamlit czyta je jako ograniczniki LaTeX-a — więc oba
  symbole znikały, a tekst między nimi renderował się jako matematyka. Robił to również
  w polskim panelu. `humanize.md()` je escapuje w trzech miejscach.
- Dokumentacja chodzi teraz parami: `README.md` / `README.pl.md`, `howitworks.md` /
  `howitworks.pl.md` i tak dalej. README dostało przewodnik uruchomienia od zera
  z instrukcjami dla macOS, Linuksa i Windowsa, uczciwą sekcję
  [czego się spodziewać](README.pl.md#czego-się-spodziewać-po-takim-bocie) oraz poprawioną
  liczbę testów — deklarowało 74, jest 294. Przewodnik po Synology został uogólniony: bez
  adresów z sieci domowej, bez prywatnych nazw kluczy, a anegdoty przepisane w drugiej
  osobie.
- **Poprawione: `python -m tradaemon.engine --once` nigdy nie istniało.** README opisywało
  tę flagę jako „przetwórz jedną świecę i zakończ" od 0.1.0, ale punkt wejścia silnika nie
  parsuje żadnych argumentów — po cichu ignorował `--once` i uruchamiał pętlę 4h na stałe.
  Na NAS-ie nieszkodliwe, w przewodniku „od zera" wprost mylące, bo nowa osoba dostawała
  polecenie jednorazowe, które nigdy nie wraca. Oba README mówią teraz, co to robi.
  `python -m tradaemon.portfolio` naprawdę przyjmuje `--once` i `--backfill`; nie robi tego
  wyłącznie silnik krypto.

## 0.1.16 — 2026-08-12

- **Nowa księga `prog_060`.** 0.1.15 pokazało, że prawdopodobieństwo modelu niesie
  informację tylko przy górnej krawędzi, ale nie umiało powiedzieć, co z tym zrobić:
  tabele operowały **kwantylami wewnątrz okna** („najsłabsze trzy piąte"), a config
  przyjmuje liczbę. Nowa tabela E przemiata **stałe progi pełnym backtestem książki**,
  po jednym przebiegu na okno i próg — więc liczy też to, czego tabela D nie umiała:
  że odcięty sygnał **zwalnia slot następnemu kandydatowi**.
- **Wynik: próg 0,58–0,60 bije 0,55 o ~+2,9 pp na okno, w 5 oknach na 6** — i to samo
  wychodzi przy obu regułach przydziału slotów (`fcfs` +2,80/+2,87 pp, `best_first`
  +3,40/+3,42 pp), więc nie jest to wniosek o przydziale, tylko o progu.
  Mechanizm widać w rozbiciu na reżim: **zysk bierze się z mniejszych strat na
  spadkach** (−8,3% → −3,5% na okno), a nie z większych zysków na wzrostach
  (+13,3% → +12,3%). Powyżej 0,62 upside się załamuje (+5,3%) — odcinanie przestaje
  wtedy wybierać, a zaczyna po prostu nie handlować.
- **Ale to nie jest wynik do przestawiania configu, tylko do postawienia przed rynkiem.**
  Pod `fcfs`, czyli tym, co faktycznie robi silnik, **t = +1,0** (0,60) i **+1,2**
  (0,58) — bo okna różnią się od siebie znacznie bardziej niż progi: przy jednym
  i tym samym progu wyniki idą od −15% do +25%. Stąd księga, a nie edycja.
- **Próg 0,60, a nie 0,58 z czubka tabeli.** Różnica +2,87 vs +2,80 pp leży głęboko
  w szumie, więc wybór wyższej liczby byłby dopasowaniem się do przemiatania. 0,60 to
  domyślna wartość w `config.py`, leży równo między sąsiednimi księgami i **trzyma
  mniej**: 55% świec w rynku zamiast 82% przy 0,55, i o 30% mniej transakcji do
  oprowizjonowania.
- **`primary_variant` zostaje na `prog_050` — świadomie, mimo że przemiatanie stawia
  ją na ostatnim miejscu** (−2,58 pp wobec 0,55, lepsza tylko w 2 oknach na 6).
  Powód jest w żywych księgach, a te mówią **coś odwrotnego niż backtest**. Za ten sam
  okres (24.07–12.08, 19 dni, wszystkie na 20% × 3 z panelu):

  | księga | próg | wynik | transakcje | win % | śr. ekspozycja | maxDD |
  |---|---|---|---|---|---|---|
  | prog_050 | 0,50 | **+0,16%** | 42 | 54,8 | 36% | −1,90% |
  | prog_065 | 0,65 | −0,91% | 12 | 33,3 | 10% | −1,18% |
  | prog_055 | 0,55 | −1,31% | 30 | 50,0 | 28% | −2,43% |

  Backtest ustawia 0,60 ≈ 0,58 > 0,65 > 0,55 > 0,50; rachunek daje 0,50 > 0,65 > 0,55.
  **Obie kolejności są za słabe, żeby na nich cokolwiek przestawiać** — 19 dni przy
  rozrzucie ±1,3% to szum, a przewaga `prog_050` nad `prog_055` (1,5 pp przy trzykrotnie
  większym obrocie) mieści się w tym, co dwa tygodnie produkują z niczego. Przypięcie
  „Twojego portfela" do świeżej księgi kosztowałoby całą widoczną historię na ekranie
  głównym, więc pin zostaje do czasu, aż `prog_060` uzbiera własny okres do porównania.
- **Wdrażany `config.yaml` ma wreszcie testy.** Żaden test nie czytał dotąd
  `config/config.yaml`, więc literówka wychodziła dopiero na NAS-ie — a tam
  przebudowa idzie przez GUI Container Managera i kosztuje pełny cykl wdrożenia.
  Trzy niezmienniki: plik się parsuje, **nazwy wariantów są unikalne** (duplikat to
  dwie księgi piszące do jednego `runtime/<nazwa>/` — jeden `state.json` nadpisywany
  co minutę i dwie strategie w jednym dzienniku, bez śladu w panelu, że porównanie
  jest fikcją) i `primary_variant` wskazuje na istniejący wariant (wskazanie w próżnię
  nie krzyczy, tylko po cichu pokazuje na głównym ekranie księgę, której nikt nie wybrał).

## 0.1.15 — 2026-08-12

- **Transakcja zapisuje wreszcie prawdopodobieństwo, które ją otworzyła.** Model liczył
  `p`, silnik porównywał je z progiem, wpisywał do logu i **wyrzucał** — w rekordzie
  transakcji go nie było ani w backteście pary, ani książki, ani w dzienniku silnika.
  Skutkiem tego na pytanie „czy transakcje z wysokim p kończyły się lepiej" nie dało się
  odpowiedzieć z danych, które projekt miał. Teraz kolumna `prob` jedzie wszędzie, więc
  za kilka miesięcy odpowiedzą na to **żywe księgi z NAS-a**, a nie backtest.
  Pozycje zapisane w `state.json` sprzed tej wersji wczytują się dalej (`entry_prob=None`).
  Sprawdzone, że to sam zapis: 2148 transakcji w czterech konfiguracjach, **identycznych
  co do wiersza** przed i po.
- Przy okazji: `runner.py` przy sygnale short nie aktualizował `best_p`. Nic to nie
  zmieniało, dopóki nikt tej zmiennej nie czytał — ale rekord transakcji ją czyta, więc
  **każdy short trafiłby pod prawdopodobieństwo modelu długiego**. Test to pokazuje:
  bez poprawki 325 shortów zapisuje się pod 0,65 zamiast 0,85.
- **Zmierzone i nierozstrzygnięte: różnicowanie kwoty pozycji według prawdopodobieństwa.**
  Nowy `scripts/research/prob_calibration.py`, 6 okien × 120 dni, model trenowany osobno
  przed każdym oknem, 1669 transakcji. Wyniki:
  - **Krzywa kalibracji nie jest rampą, tylko progiem.** Trzy najniższe koszyki
    (p 0,550–0,591) są nie do odróżnienia od siebie i **wszystkie poniżej progu
    opłacalności** 57,1%: 55,4 / 53,6 / 53,9%. Dwa górne (p ≳ 0,58) jako jedyne go biją:
    **60,5% i 63,9%**, i jako jedyne mają dodatni wynik netto. Kontrola na modelu bez
    wiedzy daje krzywą płaską (53,4 / 57,0 / 52,9 / 50,6 / 56,7), więc to nie jest
    artefakt maszynerii.
  - **Sam zysk z różnicowania nie przechodzi bramki.** Rampa neutralna budżetowo daje
    +2,6 do +3,5 pp na okno, ale wobec modelu bez wiedzy to **z = +1,29 i +1,55** przy
    progu 1,65. Do tego całość siedzi we wzrostach (+6,4 pp) i znika w spadkach (+0,7 pp).
  - **Odcięcie bije zmniejszanie.** Wyrzucenie trzech najsłabszych piątych sygnałów daje
    **+3,4 pp na okno ponad odcięcie tylu samo transakcji na chybił trafił**, w 5 oknach
    na 6 — a przy okazji nie płaci od nich prowizji. Kontrola daje tu szum (±1 pp, 3/6).
    To jest dźwignia na jedno pole w configu (`prob_threshold`), a nie na nowy mechanizm.
  - Zastrzeżenie do wdrożenia: próg „0,585" z tabeli to kwantyl **wewnątrz okna**, a model
    jest trenowany od nowa przed każdym oknem, więc skala `p` dryfuje. Stała liczba
    w `config.yaml` nie jest tym samym co „odetnij najsłabsze 60% tego okna".
- **Dwa błędy metodologiczne złapane po drodze, oba przez kontrolę.** Pierwsza wersja
  uznawała rozkład zerowy z tasowania `p` między transakcjami — i przepuszczała nim
  **model bez wiedzy na percentylu 96,5**. Powód: tasowanie po pojedynczych transakcjach
  traktuje osiemnaście par krypto jako osiemnaście niezależnych obserwacji, a one chodzą
  razem, więc rozrzut wychodzi za wąski. Druga wersja porównywała rampę liniową w `p`
  z kontrolą, w której `p` ma zupełnie inny kształt rozkładu — przy ściśniętym przy progu
  `p` ta sama rampa stawia prawie wszystko na garstce transakcji, a przy równomiernym
  rozkłada się gładko. Po przypięciu rozkładu mnożnika (`matched_multipliers`) rzekome
  **z = +3,99 spadło do +1,55**.
- **`ConstantBundle` przestaje dawać wszystkim parom ten sam los.** Generator był
  odtwarzany z ziarna przy **każdym** wywołaniu `predict_proba`, więc kontrola „random"
  wręczała osiemnastu parom identyczny ciąg prawdopodobieństw. Na backteście pary to
  tylko zawężało wariancję; na książce psuło kontrolę doszczętnie, bo `best_first` nie
  miał czego rankować. Generator budowany jest teraz raz. Dotyczy wyłącznie kontroli
  `random` — `always_long` / `always_short` są bez zmian.
- `window_frames` przeniesione z `scripts/research/universe.py` do `research/lab.py`,
  bo używają go teraz dwa skrypty. Bez zmiany zachowania.

## 0.1.14 — 2026-08-11

- **Panel przestał liczyć sześćdziesiąt razy to samo.** Dziennik zdarzeń rysuje do
  sześćdziesięciu wierszy, każdy z dymkiem pokazującym kurs, a `prices=prices_for(sym)`
  było **argumentem** `preview_button` — więc liczyło się zachłannie dla każdego
  wiersza, mimo że te sześćdziesiąt wierszy wymienia zaledwie **11 różnych par**.
  Zmierzone na żywych księgach z NAS-a: **1267 ms pandas na jedno odświeżenie**,
  powtarzane co 15 s przez fragment `run_every`. Teraz `price_view.tooltips()` liczy
  dymek raz na instrument, a `price_view.memoized()` raz czyta jego notowania —
  **95 ms, czyli 13,4× szybciej** (na NAS-ie szacunkowo ~3,5 s → ~0,26 s).
- **`summary()` przestało parsować całą historię, żeby odczytać trzy liczby z ogona.**
  `pct_change` wołało `pd.to_datetime` na ~12 000 wierszy z Parquetu, i to dwa razy
  (raz na horyzont 24 h / 7 dni). Teraz kolumna parsuje się raz, na ogonie 200 świec —
  33 dni na 4h i 200 dni na notowaniach dziennych, więc horyzont 7 dni mieści się
  z zapasem w obu modułach. Wycinek ogranicza *zasięg spojrzenia wstecz*, nie odpowiedź:
  test porównuje wynik z tym samym pytaniem zadanym pełnej ramce.
- To sama warstwa prezentacji — **żadnej zmiany w logice bota, decyzjach ani księgach**.
  Dymki są identyczne co do znaku; sprawdzone przez porównanie 60 wierszy przed i po.
- Ten sam wzorzec naprawiony w module portfela (`portfolio_view.py`), gdzie był
  łagodniejszy (15 wierszy dziennika zamiast 60).
- **Panel odświeża się co 60 s zamiast co 15 s** — na obu układach, nie tylko na
  telefonie. To nie jest kompromis, tylko sufit: decyzje zapadają na zamkniętych
  świecach 4h, a pomiędzy nimi jedynym pisarzem `equity`/`last_close` jest pętla
  tickera silnika, chodząca co `TICKER_SECONDS = 60`. Odświeżanie co 15 s
  przerysowywało te same liczby trzy razy na cztery. Razem z poprawkami wyżej
  panel zużywa na NAS-ie **ok. 54× mniej czasu procesora** (~3,5 s co 15 s, czyli
  23% rdzenia bez przerwy → ~0,26 s co 60 s, czyli 0,4%).

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
- Wersja trzymana w jednym miejscu (`src/tradaemon/__init__.py`); `pyproject.toml`
  czyta ją przy budowaniu pakietu.

## 0.1.0

- Pierwsza wersja: silnik krypto-scalpera, zarządca portfela, badania, panel.
