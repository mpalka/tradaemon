# Historia zmian

Najnowsze na górze. Numer wersji z tego pliku musi zgadzać się z `__version__`
w `src/trademon/__init__.py` — pilnuje tego `tests/test_version.py`.

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
