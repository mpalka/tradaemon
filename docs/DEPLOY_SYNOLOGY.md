# Wdrożenie na Synology NAS

Przewodnik zakłada: NAS x86_64, obraz budowany bezpośrednio na NAS-ie (Container
Manager), dostęp do panelu tylko z sieci lokalnej (bez wystawiania na świat).

## 1. Wymagania wstępne

- **DSM 7.2+** z pakietem **Container Manager** (Centrum Pakietów).
- **SSH włączone**: Panel sterowania → Terminal i SNMP → Włącz usługę SSH.
- Folder współdzielony na projekt, docelowo `/volume1/docker/trademon` — patrz niżej.

### Skąd się bierze `/volume1/docker`

Synology układa magazyn warstwowo: **dyski** → **pula pamięci masowej** (to jest
RAID) → **wolumen** (pierwszy nazywa się `Volume 1` i ma ścieżkę `/volume1`) →
**folder współdzielony** (np. `docker`, czyli `/volume1/docker`). Ścieżki
`/volumeX` istnieją same z siebie, ale katalogu pod nimi musi odpowiadać
istniejący folder współdzielony — inaczej kopiowanie odbije się o brak
uprawnień.

**Najpierw sprawdź, czy już go masz.** Instalacja Container Managera zwykle sama
tworzy folder współdzielony `docker`. Zobacz w File Station (czy na liście jest
`docker`) albo przez SSH:

```bash
ls -ld /volume1/docker
```

**Jeśli go nie ma**: Panel sterowania → Folder współdzielony → Utwórz:

- nazwa: `docker`
- lokalizacja: `Volume 1` (albo ten wolumen, na którym masz miejsce)
- **nie zaznaczaj szyfrowania** — zaszyfrowany folder nie montuje się sam po
  restarcie NAS-a, więc kontenery z `restart: unless-stopped` wstałyby z pustym
  katalogiem i księgi zaczęłyby od zera;
- kosz i migawki wedle uznania, nie mają wpływu na działanie.

Podkatalog `trademon` utworzy się sam przy pierwszym kopiowaniu (krok 2) —
nie musisz go klikać.

### Poza tym nie zakładasz żadnych katalogów ręcznie

`docker` to jedyny folder, który klikasz w DSM. Reszta powstaje sama:

| Katalog | Skąd się bierze |
|---|---|
| `trademon/` | `mkdir -p` w komendzie z kroku 2 |
| `config/`, `src/`, `scripts/` | wysyłka źródła z kroku 3 |
| `data/`, `models/`, `runtime/` | kopiowanie z kroku 2; a gdyby ich nie było, tworzy je sam kod ([config.py](../src/trademon/config.py)) przy starcie |
| `runtime/<nazwa-księgi>/` | `RuntimeStore` przy pierwszym zapisie ([engine/state.py](../src/trademon/engine/state.py)) |

**Właśnie dlatego kolejność ma znaczenie.** Jeśli odpalisz kontenery przed
skopiowaniem danych, katalogi powstaną — ale **puste**, a księgi zaczną liczyć
od zera i stracisz ciągłość historii. Najpierw krok 2 (kopiowanie), dopiero potem
krok 5 (start).

O uprawnienia nie musisz się martwić: kontenery działają jako root (`Dockerfile`
nie ustawia `USER`), więc zapiszą się do plików niezależnie od tego, na jakiego
użytkownika DSM przyjechały.

**Ile miejsca zarezerwować.** Same dane projektu to dziś ~40 MB (`data/` 33 MB,
`models/` 6 MB, `runtime/` 1 MB) i rosną wolno. Miejsce zjada obraz Dockera:
python + pandas/numpy/pyarrow/duckdb/lightgbm/scikit-learn/streamlit to ok.
1,5–2 GB, plus cache builda. **Licz ~5 GB wolnego** na wolumenie z zapasem na
kolejne rebuildy. Sprawdzisz w Menedżerze magazynu → Wolumen.

## 2. Migracja istniejącej historii z Maca na NAS

**Zrób to zanim odpalisz cokolwiek na NAS-ie.** `runtime/<book>/state.json`,
`trades.jsonl`, `equity.jsonl` to cała dotychczasowa historia działania
(stan ksiąg, dziennik transakcji, krzywa equity). `RuntimeStore` przy braku
tych plików startuje księgę od zera — więc jeśli chcesz kontynuować, a nie
zaczynać od nowa, musisz je skopiować.

**Najpierw wgraj klucz SSH** — bez niego każda kolejna komenda pyta o hasło,
a część narzędzi (patrz niżej) w ogóle się nie zaloguje:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/synology2 -N "" -C "mac -> synology2"
ssh-copy-id -i ~/.ssh/synology2.pub <user>@<nas>
ssh <user>@<nas> 'chmod 755 ~ && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys'
```

Ostatnia linia jest istotna: DSM zostawia katalog domowy zapisywalny dla grupy,
a sshd wtedy **po cichu ignoruje klucz** i wraca do pytania o hasło. Warto też
dodać wpis w `~/.ssh/config` (`Host`, `User`, `IdentityFile`).

Sam transfer — z Maca, z katalogu projektu:

```bash
tar czf - data models runtime config | ssh <nas> 'mkdir -p /volume1/docker/trademon && tar xzf - -C /volume1/docker/trademon'
```

> **Nie licz na rsync.** Na tym NAS-ie `rsync -avz ... <nas>:/volume1/...`
> kończy się `Permission denied, please try again` i błędami
> `io_read_nonblocking` / `io_read_buf`. Wygląda to jak odmowa logowania, ale
> `ssh -v` pokazuje coś innego: `Authenticated ... using "publickey"`, sesja
> wstaje, komenda `rsync --server ...` idzie do NAS-a i **dopiero zdalna strona**
> odmawia. Czyli blokada jest po stronie DSM, nie w uwierzytelnianiu. Prawdopodobne
> lekarstwo (niesprawdzone): Panel sterowania → Usługi plików → rsync → włącz
> usługę. `tar` i `scp` działają bez tego, więc najprościej ich użyć.

Co dokładnie warto skopiować:

- `runtime/` — historia transakcji i equity, dla każdej księgi osobno.
- `data/` — cache OHLCV (parquet), oszczędza ponowne pobieranie z Binance/Yahoo.
- `models/` — wytrenowane modele + raporty z `models/reports/`.
- `config/*.overrides.yaml` — ustawienia zapisane przez panel (np. przypięty
  wariant A/B).
- `.env` (jeśli używasz `ALERT_WEBHOOK_URL`) — kopiuj przez SFTP/SSH,
  **nigdy przez git**, to sekret.

## 3. Pobranie kodu na NAS

**DSM nie ma gita** (`git: command not found`), a repo jest prywatne — klonowanie
na NAS-ie wymagałoby pakietu Git Server z Centrum Pakietów **i** tokenu GitHuba.
Prościej wysłać źródło tym samym kanałem co dane.

Z Maca, z katalogu projektu:

```bash
COPYFILE_DISABLE=1 tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'
```

Lista jest jawna z rozmysłem: całe źródło waży ~1 MB, ale `.venv` obok niego
718 MB. Przy `--exclude` łatwo o pomyłkę, przy wyliczeniu — nie.

`COPYFILE_DISABLE=1` powstrzymuje `tar` z macOS przed dopisywaniem plików
`._nazwa` — kopii rozszerzonych atrybutów. Nie psują builda (Python ich nie
zaimportuje), ale zaśmiecają obraz i sprawiają, że porównanie źródła NAS-a z
Makiem nie wychodzi na zero, co przy diagnozie kosztuje czas.

Do builda wystarczy to, co `Dockerfile` kopiuje (`pyproject.toml`, `src`,
`config`, `scripts`) plus `docker-compose.yml`. `README.md` i `docs` jadą dla
wygody.

Na koniec utwórz `.env` — musi istnieć, nawet pusty:

```bash
ssh <nas> 'cd /volume1/docker/trademon && cp -n .env.example .env'
```

Dlaczego wymagany: Container Manager ma starszą Compose, która nie zna
rozszerzonej składni `env_file` (`- path: .env` + `required: false`) i wywala
się na `services.bot.env_file.0 must be a string`. Dlatego
`docker-compose.yml` używa zwykłego `- .env`, a ta forma nie umie być
opcjonalna. Puste wartości nie przeszkadzają — klucze giełdy są potrzebne
dopiero w trybie live.

## 4. DNS dla kontenerów (już ustawiony w `docker-compose.yml`)

Nic tu nie musisz robić — `docker-compose.yml` ustawia wszystkim czterem usługom
`dns: [1.1.1.1, 1.0.0.1, 8.8.8.8]`. Warto jednak wiedzieć, po co, bo objaw jest
mylący i kosztował już jedną cichą awarię.

Bez tego bot wstaje, odtwarza księgi i dopiero przy pierwszym pobraniu świec
wywala się na `socket.gaierror: [Errno -3] Temporary failure in name
resolution` (ccxt nie dosięga `api.binance.com`). Mylące jest to, że **build
działa** — `docker build` używa DNS hosta wprost, a `docker compose` tworzy
własną sieć bridge z resolverem `127.0.0.11`, który przekazuje zapytania do
`/etc/resolv.conf` NAS-a. Jeśli stoi tam adres pętli zwrotnej (typowe na DSM,
np. przy pakiecie DNS Server), wewnątrz kontenera wskazuje on na sam kontener.

Wcześniej stał tu przepis na `docker-compose.override.yml` kładziony na NAS-ie
poza repo. Brzmiało czysto, ale plik nie jest w gicie ani w paczce z kroku 8, więc
po prostu zniknął — a `restart: unless-stopped` zamienił to w 826 restartów w
pięć godzin. Dlatego resolwery są teraz w repo. Wszystkie hosty, do których
sięgamy, są publiczne, więc nadpisanie resolwera hosta nie może popsuć nazwy
lokalnej.

**Wolisz swój router?** Podmień listę w `docker-compose.yml` na jego adres —
`ssh <nas> 'cat /etc/resolv.conf'` pokaże, czym posługuje się sam NAS.

**Sprawdzenie po starcie — bez roota, samym SSH z kluczem.** Nie zaglądaj do
kontenera (to wymaga `sudo`, patrz krok 5); zajrzyj do plików, które silnik
zapisuje na dysku NAS-a:

```bash
ssh <nas> 'python3 -c "import json;s=json.load(open(\"/volume1/docker/trademon/runtime/prog_050/state.json\"));print(s[\"updated_at\"], len(s[\"last_close\"]), \"par\")"'
```

Ma pokazać świeży czas i **10 par**. Zero par oznacza, że silnik nie dosięgnął
giełdy i przewrócił się przed pierwszym pobraniem świec — czyli DNS nadal nie
działa i nie ma sensu szukać przyczyny w kodzie bota. Drugi sygnał: `ls -l` na
`runtime/prog_050/equity.jsonl` — jeśli `state.json` jest sprzed sekund, a
`equity.jsonl` sprzed godzin, to trwa pętla restartów.

Podgląd logów kontenera masz w Container Manager → *Kontener* → `trademon-bot-1`
→ *Dziennik*.

## 5. Start kontenerów

**Container Manager GUI — to jest droga, która działa.** Zakładka *Projekt* →
*Utwórz* → wskaż folder z `docker-compose.yml` → build. Przy kolejnych zmianach
kodu: *Projekt* → zaznacz projekt → *Akcja* → **Kompiluj**. To odpowiednik
`docker compose up -d --build`; samo *Uruchom* **nie przebudowuje obrazu** i
zostawia stary kod, co wygląda jak wdrożenie, które nic nie zmieniło.

**Dlaczego nie po SSH.** Kuszące jest `ssh <nas> 'sudo docker compose up -d
--build'`, ale wykłada się dwa razy i za każdym razem inaczej:

1. W nieinteraktywnym `ssh <nas> '<komenda>'` PATH jest okrojony i `docker`
   kończy się `command not found` — binarka leży w `/usr/local/bin/docker`.
2. Nawet z pełną ścieżką `sudo` na DSM **żąda hasła** (`sudo -n` zwraca
   „a password is required"), a socket `/var/run/docker.sock` należy do
   `root:root` z prawami `srw-rw----`, więc bez roota nie ma dostępu. Konta w
   grupie `administrators` to nie zmienia — nie ma tu grupy `docker`.

Zostaje `ssh -t <nas>` i wpisanie hasła ręcznie, ale skoro i tak siadasz do
klawiatury, GUI jest szybsze i mniej zawodne. Do **odczytu** SSH nadaje się
świetnie i klucz wystarcza — patrz weryfikacja niżej.

`docker-compose.yml` ma już `restart: unless-stopped` na każdym serwisie, więc
po restarcie NAS-a kontenery wracają same — warto tylko zweryfikować w
Container Manager, że projekt ma włączone "Uruchom przy starcie".

## 6. Dostęp z LAN

Panel: `http://<adres-ip-nas>:8501`, w sieci domowej.

- **Nie** przekierowuj portu 8501 na routerze.
- Jeśli zapora DSM jest włączona, rozważ regułę w Panel sterowania →
  Zabezpieczenia → Zapora ograniczającą port 8501 do podsieci LAN.
- Warto ustawić NAS-owi stały adres IP (rezerwacja DHCP na routerze), żeby
  link się nie zmieniał.

## 7. Zasoby: serwis `refresher`

`refresher` trenuje LightGBM raz w tygodniu (`scripts/refresh.py`). Na
słabszym NAS-ie (mało RAM/CPU) może to być zauważalnie wolniejsze niż na
Macu. Dwie opcje:

- Zostaw jak jest — i tak działa w tle, raz na 7 dni, nie blokuje dashboardu.
- Wyłącz na NAS-ie (`docker compose stop refresher` albo zakomentuj serwis w
  `docker-compose.yml`) i dalej trenuj lokalnie na Macu, wysyłając potem samo
  `models/` (`tar czf - models | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'`).

## 8. Aktualizacja aplikacji później

Bez gita na NAS-ie aktualizacja to dwa kroki: wysyłka źródła (SSH, klucz
wystarcza) i przebudowa obrazu (GUI, bo wymaga roota — patrz krok 5).

**1. Wyślij źródło.** Z Maca, po `git pull` u siebie:

```bash
COPYFILE_DISABLE=1 tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'
```

**2. Przebuduj obraz.** Container Manager → *Projekt* → `trademon` → *Akcja* →
**Kompiluj**. Nie *Uruchom* — to podniesie stary obraz i nic się nie zmieni.

**3. Sprawdź, że naprawdę się przebudowało.** Otwórz `http://<nas>:8501` i
przeczytaj numer wersji pod tytułem. Musi zgadzać się z `__version__` w
`src/trademon/__init__.py` z tego wdrożenia. To jedyny wiarygodny dowód — `src/`
jest wkompilowane w obraz (`COPY src` + `pip install .`), a nie zamontowane, więc
świeże pliki na dysku NAS-a **nie** znaczą świeżego kodu w kontenerze.

`config/`, `data/`, `models/`, `runtime/` są zamontowane z zewnątrz kontenera
(bind mount), więc rebuild obrazu nigdy nie rusza historii. Uwaga: tar
**nadpisuje** bazowe `config/*.yaml` wersją z Maca, ale nie kasuje
`config/*.overrides.yaml` — ustawienia zapisane przez panel na NAS-ie zostają.

## 9. Backup

`runtime/` to jedyny katalog z realną, nieodtwarzalną historią (transakcje,
equity). Warto objąć `/volume1/docker/trademon` istniejącym mechanizmem
Synology — Hyper Backup albo migawki wolumenu — zamiast liczyć wyłącznie na
to, że dysk NAS-a nigdy nie padnie.
