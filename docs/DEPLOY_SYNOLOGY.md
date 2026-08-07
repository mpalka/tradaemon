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
istniejący folder współdzielony — inaczej `git clone` i rsync odbiją się o brak
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

Podkatalog `trademon` utworzy się sam przy `git clone` — nie musisz go klikać.

### Poza tym nie zakładasz żadnych katalogów ręcznie

`docker` to jedyny folder, który klikasz w DSM. Reszta powstaje sama:

| Katalog | Skąd się bierze |
|---|---|
| `trademon/` | `git clone` (albo rsync z kroku 2) |
| `config/`, `src/`, `scripts/` | z gita |
| `data/`, `models/`, `runtime/` | rsync z kroku 2; a gdyby ich nie było, tworzy je sam kod ([config.py](../src/trademon/config.py)) przy starcie |
| `runtime/<nazwa-księgi>/` | `RuntimeStore` przy pierwszym zapisie ([engine/state.py](../src/trademon/engine/state.py)) |

**Właśnie dlatego kolejność ma znaczenie.** Jeśli odpalisz kontenery przed
skopiowaniem danych, katalogi powstaną — ale **puste**, a księgi zaczną liczyć
od zera i stracisz ciągłość historii. Najpierw krok 2 (rsync), dopiero potem
krok 4 (start).

O uprawnienia nie musisz się martwić: kontenery działają jako root (`Dockerfile`
nie ustawia `USER`), więc zapiszą się do plików niezależnie od tego, na jakiego
użytkownika DSM przyjechały przez rsync.

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

Z Maca, z katalogu projektu:

```bash
rsync -avz --progress ./data ./models ./runtime ./config <user>@<nas-ip>:/volume1/docker/trademon/
```

(Alternatywa bez rsync: scp lub File Station.)

**Na macOS wgraj najpierw klucz SSH — inaczej rsync się nie zaloguje.** macOS
podstawia jako `/usr/bin/rsync` **openrsync** (reimplementacja Apple'a), która
nie radzi sobie z interaktywnym promptem na hasło: prompt się pokazuje, ale
logowanie kończy się `Permission denied, please try again` i serią błędów
`io_read_nonblocking` / `io_read_buf`. Zwykłe `ssh` z tym samym hasłem działa
wtedy bez zarzutu, więc łatwo szukać przyczyny nie tam, gdzie trzeba.

Klucz omija prompt i rozwiązuje to na stałe:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/synology2 -N "" -C "mac -> synology2"
ssh-copy-id -i ~/.ssh/synology2.pub <user>@<nas>
ssh <user>@<nas> 'chmod 755 ~ && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys'
```

Ostatnia linia jest istotna: DSM zostawia katalog domowy zapisywalny dla grupy,
a sshd wtedy **po cichu ignoruje klucz** i wraca do pytania o hasło. Warto też
dodać wpis w `~/.ssh/config` (`Host`, `User`, `IdentityFile`), żeby rsync sam
sięgał po właściwy klucz.

Co dokładnie warto skopiować:

- `runtime/` — historia transakcji i equity, dla każdej księgi osobno.
- `data/` — cache OHLCV (parquet), oszczędza ponowne pobieranie z Binance/Yahoo.
- `models/` — wytrenowane modele + raporty z `models/reports/`.
- `config/*.overrides.yaml` — ustawienia zapisane przez panel (np. przypięty
  wariant A/B). Bazowe `config/*.yaml` i tak przyjadą z gita.
- `.env` (jeśli używasz `ALERT_WEBHOOK_URL`) — kopiuj ręcznie przez SFTP/SSH,
  **nigdy przez git**, to sekret.

## 3. Pobranie kodu na NAS

```bash
ssh <user>@<nas-ip>
git clone <repo-url> /volume1/docker/trademon
```

Jeśli krok 2 (rsync) już utworzył `/volume1/docker/trademon/data` itp. przed
`git clone` — sklonuj do pustego katalogu i dopiero potem dograj `data/`,
`models/`, `runtime/`, `config/*.overrides.yaml` do środka, żeby ścieżki
względne z `docker-compose.yml` się zgadzały.

## 4. Start kontenerów

**SSH (najbardziej przewidywalne):**

```bash
cd /volume1/docker/trademon
sudo docker compose up -d --build
```

**Container Manager GUI (wygodniejsze na co dzień):** zakładka *Projekt* →
*Utwórz* → wskaż folder z `docker-compose.yml` → build. Pozwala
startować/zatrzymywać/podglądać logi bez SSH przy kolejnych operacjach.

`docker-compose.yml` ma już `restart: unless-stopped` na każdym serwisie, więc
po restarcie NAS-a kontenery wracają same — warto tylko zweryfikować w
Container Manager, że projekt ma włączone "Uruchom przy starcie".

## 5. Dostęp z LAN

Panel: `http://<adres-ip-nas>:8501`, w sieci domowej.

- **Nie** przekierowuj portu 8501 na routerze.
- Jeśli zapora DSM jest włączona, rozważ regułę w Panel sterowania →
  Zabezpieczenia → Zapora ograniczającą port 8501 do podsieci LAN.
- Warto ustawić NAS-owi stały adres IP (rezerwacja DHCP na routerze), żeby
  link się nie zmieniał.

## 6. Zasoby: serwis `refresher`

`refresher` trenuje LightGBM raz w tygodniu (`scripts/refresh.py`). Na
słabszym NAS-ie (mało RAM/CPU) może to być zauważalnie wolniejsze niż na
Macu. Dwie opcje:

- Zostaw jak jest — i tak działa w tle, raz na 7 dni, nie blokuje dashboardu.
- Wyłącz na NAS-ie (`docker compose stop refresher` albo zakomentuj serwis w
  `docker-compose.yml`) i dalej trenuj lokalnie na Macu, synchronizując tylko
  `models/` przez `rsync` po każdym `scripts/refresh.py`.

## 7. Aktualizacja aplikacji później

```bash
ssh <user>@<nas-ip>
cd /volume1/docker/trademon
git pull
docker compose up -d --build
```

`config/`, `data/`, `models/`, `runtime/` są zamontowane z zewnątrz kontenera
(bind mount), więc rebuild obrazu nigdy nie rusza historii.

## 8. Backup

`runtime/` to jedyny katalog z realną, nieodtwarzalną historią (transakcje,
equity). Warto objąć `/volume1/docker/trademon` istniejącym mechanizmem
Synology — Hyper Backup albo migawki wolumenu — zamiast liczyć wyłącznie na
to, że dysk NAS-a nigdy nie padnie.
