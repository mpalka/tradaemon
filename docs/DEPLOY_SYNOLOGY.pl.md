# Wdrożenie na Synology NAS

*[English](DEPLOY_SYNOLOGY.md) · Polski*

Przewodnik zakłada: NAS x86_64, obraz budowany bezpośrednio na NAS-ie (Container
Manager), dostęp do panelu tylko z sieci lokalnej (bez wystawiania na świat).

W całym tekście `<nas>` to nazwa lub adres Twojego NAS-a, a `<user>` to konto DSM.
Podstaw własne.

## 1. Wymagania wstępne

- **DSM 7.2+** z pakietem **Container Manager** (Centrum Pakietów).
- **SSH włączone**: Panel sterowania → Terminal i SNMP → Włącz usługę SSH.
- Folder współdzielony na projekt, docelowo `/volume1/docker/tradaemon` — patrz niżej.

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

Podkatalog `tradaemon` utworzy się sam przy pierwszym kopiowaniu (krok 2) —
nie musisz go klikać.

### Poza tym nie zakładasz żadnych katalogów ręcznie

`docker` to jedyny folder, który klikasz w DSM. Reszta powstaje sama:

| Katalog | Skąd się bierze |
|---|---|
| `tradaemon/` | `mkdir -p` w komendzie z kroku 2 |
| `config/`, `src/`, `scripts/` | wysyłka źródła z kroku 3 |
| `data/`, `models/`, `runtime/` | kopiowanie z kroku 2; a gdyby ich nie było, tworzy je sam kod ([config.py](../src/tradaemon/config.py)) przy starcie |
| `runtime/<nazwa-księgi>/` | `RuntimeStore` przy pierwszym zapisie ([engine/state.py](../src/tradaemon/engine/state.py)) |

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
ssh-keygen -t ed25519 -f ~/.ssh/nas-key -N "" -C "stacja robocza -> nas"
ssh-copy-id -i ~/.ssh/nas-key.pub <user>@<nas>
ssh <user>@<nas> 'chmod 755 ~ && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys'
```

Ostatnia linia jest istotna: DSM zostawia katalog domowy zapisywalny dla grupy,
a sshd wtedy **po cichu ignoruje klucz** i wraca do pytania o hasło. Warto też
dodać wpis w `~/.ssh/config` (`Host`, `User`, `IdentityFile`).

Sam transfer — ze stacji roboczej, z katalogu projektu:

```bash
tar czf - data models runtime config | ssh <nas> 'mkdir -p /volume1/docker/tradaemon && tar xzf - -C /volume1/docker/tradaemon'
```

> **Nie licz na rsync.** Na części instalacji DSM `rsync -avz ... <nas>:/volume1/...`
> kończy się `Permission denied, please try again` i błędami
> `io_read_nonblocking` / `io_read_buf`. Wygląda to jak odmowa logowania, ale
> `ssh -v` pokazuje coś innego: `Authenticated ... using "publickey"`, sesja
> wstaje, komenda `rsync --server ...` idzie do NAS-a i **dopiero zdalna strona**
> odmawia. Czyli blokada jest po stronie DSM, nie w uwierzytelnianiu. Prawdopodobne
> lekarstwo (niesprawdzone): Panel sterowania → Usługi plików → rsync → włącz
> usługę. `tar` i `scp` działają bez tego, więc najprościej ich użyć.
>
> Na macOS jest jeszcze druga pułapka: `/usr/bin/rsync` to openrsync, który wywala
> się na samym prompcie o hasło, nawet gdy zwykłe `ssh` działa. Lekiem jest klucz
> SSH plus `chmod 755 ~` po stronie DSM.

Co dokładnie warto skopiować:

- `runtime/` — historia transakcji i equity, dla każdej księgi osobno.
- `data/` — cache OHLCV (parquet), oszczędza ponowne pobieranie z Binance/Yahoo.
- `models/` — wytrenowane modele + raporty z `models/reports/`.
- `config/*.overrides.yaml` — ustawienia zapisane przez panel (np. przypięty
  wariant A/B).
- `.env` (jeśli używasz `ALERT_WEBHOOK_URL`) — kopiuj przez SFTP/SSH,
  **nigdy przez git**, to sekret.

## 3. Pobranie kodu na NAS

**DSM nie ma gita** (`git: command not found`). Można doinstalować pakiet Git Server
i sklonować, ale przy jednym wdrożeniu prościej wysłać źródło tym samym kanałem co
dane.

Ze stacji roboczej, z katalogu projektu:

```bash
COPYFILE_DISABLE=1 tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/tradaemon'
```

Lista jest jawna z rozmysłem: całe źródło waży ~1 MB, ale `.venv` obok niego kilkaset.
Przy `--exclude` łatwo o pomyłkę, przy wyliczeniu — nie.

`COPYFILE_DISABLE=1` powstrzymuje `tar` z macOS przed dopisywaniem plików
`._nazwa` — kopii rozszerzonych atrybutów. Nie psują builda (Python ich nie
zaimportuje), ale zaśmiecają obraz i sprawiają, że porównanie źródła NAS-a z
stacją roboczą nie wychodzi na zero, co przy diagnozie kosztuje czas. Na Linuksie
zmienna jest po prostu ignorowana.

Do builda wystarczy to, co `Dockerfile` kopiuje (`pyproject.toml`, `src`,
`config`, `scripts`) plus `docker-compose.yml`. `README.md` i `docs` jadą dla
wygody.

Na koniec utwórz `.env` — musi istnieć, nawet pusty:

```bash
ssh <nas> 'cd /volume1/docker/tradaemon && cp -n .env.example .env'
```

Dlaczego wymagany: Container Manager ma starszą Compose, która nie zna
rozszerzonej składni `env_file` (`- path: .env` + `required: false`) i wywala
się na `services.bot.env_file.0 must be a string`. Dlatego
`docker-compose.yml` używa zwykłego `- .env`, a ta forma nie umie być
opcjonalna. Puste wartości nie przeszkadzają — klucze giełdy są potrzebne
dopiero w trybie live.

## 4. DNS dla kontenerów — najpierw zmierz, potem ustawiaj

**`docker-compose.yml` celowo nie ustawia `dns:`.** Kiedyś ustawiał i to była
pomyłka warta opisania, bo kosztowała wieczór.

Teoria brzmiała rozsądnie: Compose tworzy sieć bridge z resolverem `127.0.0.11`,
który przekazuje zapytania do `/etc/resolv.conf` NAS-a, a gdyby stał tam adres
pętli zwrotnej (zdarza się na DSM przy pakiecie DNS Server), wewnątrz kontenera
wskazywałby na sam kontener. Stąd pomysł na jawne, publiczne resolwery.

Zmierzone na żywym NAS-ie okazało się fałszywe. `/etc/resolv.conf` zawierał
`nameserver 192.168.1.1` — router, nie pętlę zwrotną — i odpowiadał **20/20 zapytań
w 5 ms**, szybciej niż którykolwiek publiczny resolwer. Wpisanie `1.1.1.1`
wypchnęło więc każde zapytanie przez NAT, dokładając zawodności tam, gdzie jej
nie było, i rozwiązywanie nazw zaczęło się psuć z przerwami.

**Zasada:** domyślne zachowanie (embedded resolver → resolwer hosta) jest
zarazem najkrótszą i najszybszą drogą. `dns:` dopisuj **dopiero** po
potwierdzeniu, że resolwer hosta jest naprawdę zepsuty:

```bash
ssh <nas> 'cat /etc/resolv.conf; python3 -c "import socket;print(socket.gethostbyname(\"api.binance.com\"))"'
```

Adres pętli zwrotnej w `resolv.conf` albo wyjątek z `gethostbyname` = teoria się
potwierdza, ustaw `dns:`. Cokolwiek innego = szukaj gdzie indziej.

**Uwaga, ważne:** ten sam komunikat (`Temporary failure in name resolution`)
dostaniesz również wtedy, gdy przyczyna nie ma z DNS-em nic wspólnego — patrz
„DNS czy brak NAT?" niżej. To właśnie ta pułapka wciągnęła nas w zmienianie
resolwerów, gdy problem był poziom niżej.

**Sprawdzenie po starcie — bez roota, samym SSH z kluczem.** Nie zaglądaj do
kontenera (to wymaga `sudo`, patrz krok 5); zajrzyj do plików, które silnik
zapisuje na dysku NAS-a:

```bash
ssh <nas> 'python3 -c "import json;s=json.load(open(\"/volume1/docker/tradaemon/runtime/prog_050/state.json\"));print(s[\"updated_at\"], len(s[\"last_close\"]), \"par\")"'
```

Ma pokazać świeży czas i **18 par** (tyle liczy `exchange.symbols` od 0.1.11;
wcześniej 10). Zero par oznacza, że silnik nie dosięgnął
giełdy i przewrócił się przed pierwszym pobraniem świec — czyli DNS nadal nie
działa i nie ma sensu szukać przyczyny w kodzie bota. Drugi sygnał: `ls -l` na
`runtime/prog_050/equity.jsonl` — jeśli `state.json` jest sprzed sekund, a
`equity.jsonl` sprzed godzin, to trwa pętla restartów.

Podgląd logów kontenera masz w Container Manager → *Kontener* → `tradaemon-bot-1`
→ *Dziennik*.

### Gdy bot nie dosięga giełdy — zmierz z wnętrza kontenera

`Temporary failure in name resolution` (`EAI_AGAIN`) znaczy tylko tyle, że
**resolwer nie odpowiedział**. Nie znaczy, że winny jest DNS: zapytanie, które
nie ma jak wyjść, daje identyczny komunikat. To nas raz kosztowało pół nocy
zmieniania resolwerów, gdy przyczyna była zupełnie gdzie indziej.

**Nie wnioskuj z hosta ani z plików stanu** — kontener ma własną przestrzeń
sieciową, więc działający `nslookup` na DSM nie mówi o niej nic. Wejdź do
środka: Container Manager → *Kontener* → `tradaemon-bot-1` → *Terminal* (bez ssh,
bez roota) i wklej to. Obraz to `python:3.12-slim`, więc bez `dig`, `ping`
i `curl` — Python załatwia sprawę:

```bash
python3 - <<'EOF'
import socket, struct, random

def tcp(ip, port=443, t=5):
    s = socket.socket(); s.settimeout(t)
    try: s.connect((ip, port)); return "OK"
    except Exception as e: return "BLAD: %s" % e
    finally: s.close()

def dns(server, name="google.com", t=3):
    p = struct.pack(">HHHHHH", random.randint(0, 65535), 0x0100, 1, 0, 0, 0)
    for part in name.split("."): p += bytes([len(part)]) + part.encode()
    p += b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(t)
    try: s.sendto(p, (server, 53)); s.recvfrom(512); return "OK"
    except Exception as e: return "BLAD: %s" % e
    finally: s.close()

# W pierwszej linii podstaw własny adres: dowolny host odpowiadający na 443.
# Zaszyty adres IP się zestarzeje, a chodzi tylko o test TCP bez udziału DNS-u.
print("1. TCP po samym IP, bez DNS  :", tcp("1.1.1.1"))
print("2. DNS wprost do 1.1.1.1     :", dns("1.1.1.1"))
print("3. DNS wprost do routera     :", dns("192.168.1.1"))
print("4. DNS przez resolwer Dockera:", dns("127.0.0.11"))
EOF
```

| Wynik | Przyczyna |
|---|---|
| 1 pada | kontener nie ma żadnego wyjścia; DNS jest tylko pierwszą ofiarą |
| 1 OK, 2–4 padają | **wychodzące UDP jest blokowane** — patrz niżej, to był nasz przypadek |
| 1–3 OK, pada tylko 4 | wbudowany resolwer Dockera; ogranicz liczbę zapytań po stronie bota |
| wszystko OK | trafiłeś w okno sprawności — powtórz kilka razy pod rząd |

#### Zapora DSM a podsieć kontenerów

Profil zapory kończy się regułą **Deny All**. Jeśli wcześniejsza reguła Allow
przepuszcza `172.17.0.1/255.255.255.0` — czyli **domyślny** mostek Dockera — a Compose
postawił projekt na własnej sieci (`trademon_default` = `172.18.0.0/16`), to ruch
projektu nie pasuje do żadnej reguły Allow i wpada w Deny. Maska `255.255.255.0` jest
przy tym za wąska nawet dla `172.17`, bo Docker rozdaje adresy z całego `/16`.

Efekt jest myląco łagodny: **ginie samo UDP/53, TCP przechodzi**. Bot żyje więc
na trzymanych połączeniach keep-alive i psuje się dopiero, gdy musi rozwiązać
nazwę od nowa — co wygląda jak migotanie łączności, nie jak blokada.

**Lek:** Panel sterowania → Zabezpieczenia → Zapora → edytuj profil, i **ponad**
końcowym Deny dodaj: Ports=All, Protocol=All, Source IP `172.16.0.0`, maska
`255.240.0.0`, Action=Allow. Szeroko z rozmysłem — obejmuje
`172.16.0.0–172.31.255.255`, więc przetrwa odtworzenie projektu, przy którym
Docker bierze kolejną wolną podsieć. Regułę na `172.17` można wtedy usunąć.

## 5. Start kontenerów

**Container Manager GUI — to jest droga, która działa.** Zakładka *Projekt* →
*Utwórz* → wskaż folder z `docker-compose.yml` → build. Przy kolejnych zmianach
kodu: *Projekt* → zaznacz projekt → **Zatrzymaj** → *Akcja* → **Kompiluj** →
*Uruchom*. To odpowiednik `docker compose up -d --build`; samo *Uruchom*
**nie przebudowuje obrazu** i zostawia stary kod, co wygląda jak wdrożenie,
które nic nie zmieniło.

Zatrzymanie nie jest opcjonalne: na działającym projekcie GUI nie daje
przebudować obrazu. Kolejność stop → kompiluj → uruchom jest więc pełną
procedurą, a nie ostrożnościowym dodatkiem.

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

- **Nie** przekierowuj portu 8501 na routerze. Panel nie ma logowania i pozwala
  każdemu, kto go dosięgnie, zmienić konfigurację działającego bota.
- Jeśli zapora DSM jest włączona, rozważ regułę w Panel sterowania →
  Zabezpieczenia → Zapora ograniczającą port 8501 do podsieci LAN.
- Warto ustawić NAS-owi stały adres IP (rezerwacja DHCP na routerze), żeby
  link się nie zmieniał.

## 7. Zasoby: serwis `refresher`

`refresher` trenuje LightGBM raz w tygodniu (`scripts/refresh.py`). Na
słabszym NAS-ie (mało RAM/CPU) może to być zauważalnie wolniejsze niż na
stacji roboczej. Dwie opcje:

- Zostaw jak jest — i tak działa w tle, raz na 7 dni, nie blokuje dashboardu.
- Wyłącz na NAS-ie (`docker compose stop refresher` albo zakomentuj serwis w
  `docker-compose.yml`) i dalej trenuj lokalnie lokalnie, wysyłając potem samo
  `models/` (`tar czf - models | ssh <nas> 'tar xzf - -C /volume1/docker/tradaemon'`).

## 8. Aktualizacja aplikacji później

Bez gita na NAS-ie aktualizacja to wysyłka źródła (SSH, klucz wystarcza) i
przebudowa obrazu (GUI, bo wymaga roota — patrz krok 5). Poniżej cztery kroki,
bo dwa środkowe łatwo wykonać w sposób, który wygląda na udany i nie jest.

**1. Sprawdź, czy nie wyślesz cudzych ustawień.**

```bash
ls config/*.overrides.yaml
```

Ten plik pisze panel — i ten na NAS-ie żyje własnym życiem. Tar go nie kasuje,
ale **nadpisuje**, jeśli masz lokalną kopię, więc ustawienia zapisane z panelu
na NAS-ie cofną się do tego, co akurat leży na stacji roboczej. Raz nas to kosztowało
przywrócenie limitu pozycji, który przed chwilą został z panelu zdjęty. Jeśli
lokalna kopia jest tylko pozostałością po zabawie u siebie — skasuj ją przed
wysyłką.

**2. Wyślij źródło.** Ze stacji roboczej, po `git pull` u siebie:

```bash
COPYFILE_DISABLE=1 tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/tradaemon'
```

**3. Przebuduj obraz.** Container Manager → *Projekt* → `tradaemon` →
**Zatrzymaj** → *Akcja* → **Kompiluj** → *Uruchom*. Zatrzymanie jest wymagane:
na działającym projekcie GUI nie pozwoli przebudować obrazu. Samo *Uruchom* bez
*Kompiluj* podniesie stary obraz i nic się nie zmieni.

**4. Sprawdź, że naprawdę się przebudowało.** `src/` jest wkompilowane w obraz
(`COPY src` + `pip install .`), a nie zamontowane, więc świeże pliki na dysku
NAS-a **nie** znaczą świeżego kodu w kontenerze.

Numer wersji pod tytułem na `http://<nas>:8501` jest pierwszym sprawdzeniem, ale
**dowodzi tylko tego, że świeży jest kontener panelu**. Silnik to osobny
kontener i potrafi przy niedokończonym wdrożeniu chodzić dalej na starym
obrazie — z zewnątrz wygląda to na udaną aktualizację. Silnik pytaj osobno:

```bash
ssh <nas> 'python3 -c "import json;s=json.load(open(\"/volume1/docker/tradaemon/runtime/prog_050/state.json\"));print(s[\"updated_at\"]);print(s.get(\"live_config\",\"BRAK — silnik nadal stary\"))"'
```

Świeży `updated_at` **i** obecny `live_config` (klucz istnieje od 0.1.7) znaczą,
że nowy silnik naprawdę wstał. Świeży `updated_at` bez `live_config` to obraz
sprzed aktualizacji, który wciąż handluje.

`config/`, `data/`, `models/`, `runtime/` są zamontowane z zewnątrz kontenera
(bind mount), więc rebuild obrazu nigdy nie rusza historii. Uwaga na `config/`:
tar **nadpisuje** każdy plik, który ma u siebie, więc bazowe `config/*.yaml`
przyjadą z Maca. Nadpisania z panelu przetrwają tylko wtedy, gdy nie masz ich
lokalnej kopii — dlatego krok 1 każe sprawdzić to przed wysyłką, a nie po.

## 9. Backup

`runtime/` to jedyny katalog z realną, nieodtwarzalną historią (transakcje,
equity). Warto objąć `/volume1/docker/tradaemon` istniejącym mechanizmem
Synology — Hyper Backup albo migawki wolumenu — zamiast liczyć wyłącznie na
to, że dysk NAS-a nigdy nie padnie.
