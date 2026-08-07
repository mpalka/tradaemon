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
tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'
```

Lista jest jawna z rozmysłem: całe źródło waży ~1 MB, ale `.venv` obok niego
718 MB. Przy `--exclude` łatwo o pomyłkę, przy wyliczeniu — nie.

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

## 4. DNS dla kontenerów (inaczej bot nie dosięgnie giełdy)

Zanim wystartujesz, połóż na NAS-ie plik nakładkowy — Compose scala
`docker-compose.override.yml` z głównym automatycznie, więc repo zostaje czyste:

```bash
ssh <nas> 'cat > /volume1/docker/trademon/docker-compose.override.yml' <<'YAML'
services:
  bot:
    dns: [1.1.1.1, 8.8.8.8]
  dashboard:
    dns: [1.1.1.1, 8.8.8.8]
  portfolio:
    dns: [1.1.1.1, 8.8.8.8]
  refresher:
    dns: [1.1.1.1, 8.8.8.8]
YAML
```

Bez tego bot wstaje, odtwarza księgi i dopiero przy pierwszym pobraniu świec
wywala się na `socket.gaierror: [Errno -3] Temporary failure in name
resolution` (ccxt nie dosięga `api.binance.com`). Mylące jest to, że **build
działa** — `docker build` używa DNS hosta wprost, a `docker compose` tworzy
własną sieć bridge z resolverem `127.0.0.11`, który przekazuje zapytania do
`/etc/resolv.conf` NAS-a. Jeśli stoi tam adres pętli zwrotnej (typowe na DSM,
np. przy pakiecie DNS Server), wewnątrz kontenera wskazuje on na sam kontener.

Zamiast publicznych resolverów możesz wpisać adres swojego routera —
`ssh <nas> 'cat /etc/resolv.conf'` pokaże, czym posługuje się sam NAS.

## 5. Start kontenerów

**SSH (najbardziej przewidywalne):**

```bash
cd /volume1/docker/trademon
sudo docker compose up -d --build
```

W nieinteraktywnym `ssh <nas> '<komenda>'` PATH jest okrojony i `sudo docker`
kończy się `command not found` — użyj wtedy pełnej ścieżki
`/usr/local/bin/docker` albo zaloguj się interaktywnie.

**Container Manager GUI (wygodniejsze na co dzień):** zakładka *Projekt* →
*Utwórz* → wskaż folder z `docker-compose.yml` → build. Pozwala
startować/zatrzymywać/podglądać logi bez SSH przy kolejnych operacjach.

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

Bez gita na NAS-ie aktualizacja to powtórzenie kroku 3 (wysyłka źródła) plus
przebudowa. Z Maca, po `git pull` u siebie:

```bash
tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'
ssh -t <nas> 'cd /volume1/docker/trademon && sudo docker compose up -d --build'
```

`config/`, `data/`, `models/`, `runtime/` są zamontowane z zewnątrz kontenera
(bind mount), więc rebuild obrazu nigdy nie rusza historii. Uwaga: tar
**nadpisuje** bazowe `config/*.yaml` wersją z Maca, ale nie kasuje
`config/*.overrides.yaml` — ustawienia zapisane przez panel na NAS-ie zostają.

## 9. Backup

`runtime/` to jedyny katalog z realną, nieodtwarzalną historią (transakcje,
equity). Warto objąć `/volume1/docker/trademon` istniejącym mechanizmem
Synology — Hyper Backup albo migawki wolumenu — zamiast liczyć wyłącznie na
to, że dysk NAS-a nigdy nie padnie.
