# Deploying to a Synology NAS

*English · [Polski](DEPLOY_SYNOLOGY.pl.md)*

This guide assumes: an x86_64 NAS, the image built directly on the NAS (Container
Manager), and panel access from the local network only — nothing exposed to the internet.

Throughout, `<nas>` is your NAS's hostname or IP and `<user>` is your DSM account.
Substitute your own.

## 1. Prerequisites

- **DSM 7.2+** with the **Container Manager** package (Package Center).
- **SSH enabled**: Control Panel → Terminal & SNMP → Enable SSH service.
- A shared folder for the project, ending up at `/volume1/docker/trademon` — see below.

### Where `/volume1/docker` comes from

Synology layers storage: **drives** → **storage pool** (the RAID) → **volume** (the first
is called `Volume 1` and lives at `/volume1`) → **shared folder** (e.g. `docker`, giving
`/volume1/docker`). The `/volumeX` paths exist on their own, but a directory under them
must correspond to an existing shared folder — otherwise copying bounces off a
permissions error.

**Check whether you already have it.** Installing Container Manager usually creates a
`docker` shared folder by itself. Look in File Station, or over SSH:

```bash
ls -ld /volume1/docker
```

**If it is missing**: Control Panel → Shared Folder → Create:

- name: `docker`
- location: `Volume 1` (or whichever volume has room)
- **do not tick encryption** — an encrypted folder does not mount itself after a NAS
  reboot, so containers with `restart: unless-stopped` would come back to an empty
  directory and the books would start from zero;
- recycle bin and snapshots as you like; they make no difference here.

The `trademon` subdirectory creates itself on the first copy (step 2) — you do not need
to click it into existence.

### Beyond that, you create no directories by hand

`docker` is the only folder you click in DSM. The rest appears on its own:

| Directory | Where it comes from |
|---|---|
| `trademon/` | the `mkdir -p` in step 2's command |
| `config/`, `src/`, `scripts/` | the source upload in step 3 |
| `data/`, `models/`, `runtime/` | the copy in step 2 — and failing that, the code creates them at startup ([config.py](../src/trademon/config.py)) |
| `runtime/<book-name>/` | `RuntimeStore` on its first write ([engine/state.py](../src/trademon/engine/state.py)) |

**This is exactly why the order matters.** Start the containers before copying the data
and the directories will appear — but **empty**, and the books will start counting from
zero, losing the continuity of your history. Step 2 (copying) first, step 5 (starting)
after.

You do not need to worry about permissions: the containers run as root (the `Dockerfile`
sets no `USER`), so they can write regardless of which DSM user the files arrived as.

**How much space to set aside.** The project's own data is around 40 MB today (`data/`
33 MB, `models/` 6 MB, `runtime/` 1 MB) and grows slowly. The Docker image is what eats
space: python plus pandas/numpy/pyarrow/duckdb/lightgbm/scikit-learn/streamlit is roughly
1.5–2 GB, plus the build cache. **Budget ~5 GB free** on the volume, with room for
further rebuilds. Check in Storage Manager → Volume.

## 2. Migrating existing history to the NAS

**Do this before you start anything on the NAS.** `runtime/<book>/state.json`,
`trades.jsonl` and `equity.jsonl` are the entire history of the bot's operation — book
state, the trade journal, the equity curve. With those files missing, `RuntimeStore`
starts a book from zero, so if you want to continue rather than begin again, you have to
copy them.

**Upload an SSH key first** — without one every subsequent command asks for a password,
and some tools (see below) will not log in at all:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/nas-key -N "" -C "workstation -> nas"
ssh-copy-id -i ~/.ssh/nas-key.pub <user>@<nas>
ssh <user>@<nas> 'chmod 755 ~ && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys'
```

That last line matters: DSM leaves the home directory group-writable, and sshd then
**silently ignores the key** and falls back to asking for a password. It is also worth
adding an entry to `~/.ssh/config` (`Host`, `User`, `IdentityFile`).

The transfer itself — from your machine, in the project directory:

```bash
tar czf - data models runtime config | ssh <nas> 'mkdir -p /volume1/docker/trademon && tar xzf - -C /volume1/docker/trademon'
```

> **Do not count on rsync.** On some DSM setups `rsync -avz … <nas>:/volume1/…` ends in
> `Permission denied, please try again` along with `io_read_nonblocking` / `io_read_buf`
> errors. It looks like a login refusal, but `ssh -v` shows otherwise:
> `Authenticated … using "publickey"`, the session comes up, the `rsync --server …`
> command reaches the NAS, and **the remote side is what refuses**. So the block is on
> the DSM side, not in authentication. The likely fix (untested here): Control Panel →
> File Services → rsync → enable the service. `tar` and `scp` work without it, so they
> are the simpler route.
>
> On macOS there is a second trap: `/usr/bin/rsync` is openrsync, which fails outright on
> a password prompt even when plain `ssh` works. An SSH key plus `chmod 755 ~` on the DSM
> side is the fix.

What is worth copying:

- `runtime/` — trade and equity history, separately for each book.
- `data/` — the OHLCV cache (Parquet); saves re-downloading from Binance/Yahoo.
- `models/` — trained models plus the reports in `models/reports/`.
- `config/*.overrides.yaml` — settings saved from the panel (e.g. a pinned A/B variant).
- `.env` (if you use `ALERT_WEBHOOK_URL`) — copy it over SFTP/SSH, **never through git**;
  it is a secret.

## 3. Getting the code onto the NAS

**DSM has no git** (`git: command not found`). You could install the Git Server package
and clone, but for a single deployment it is simpler to send the source down the same
channel as the data.

From your machine, in the project directory:

```bash
COPYFILE_DISABLE=1 tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'
```

The list is explicit on purpose: the whole source is ~1 MB, but the `.venv` next to it is
several hundred. With `--exclude` it is easy to make a mistake; with an enumeration it is
not.

`COPYFILE_DISABLE=1` stops macOS `tar` from adding `._name` files — copies of extended
attributes. They do not break the build (Python will not import them), but they clutter
the image and make a source comparison between NAS and workstation fail to come out
clean, which costs time during diagnosis. On Linux the variable is simply ignored.

The build needs what the `Dockerfile` copies (`pyproject.toml`, `src`, `config`,
`scripts`) plus `docker-compose.yml`. `README.md` and `docs` come along for convenience.

Finally create `.env` — it must exist, even empty:

```bash
ssh <nas> 'cd /volume1/docker/trademon && cp -n .env.example .env'
```

Why it is required: Container Manager ships an older Compose that does not understand the
extended `env_file` syntax (`- path: .env` + `required: false`) and fails with
`services.bot.env_file.0 must be a string`. So `docker-compose.yml` uses the plain
`- .env` form, and that form cannot be optional. Empty values are fine — exchange keys
are only needed in live mode.

## 4. DNS for containers — measure first, configure second

**`docker-compose.yml` deliberately does not set `dns:`.** It used to, and that was a
mistake worth writing down, because it cost an evening.

The theory sounded reasonable: Compose creates a bridge network with a resolver at
`127.0.0.11` that forwards queries to the NAS's `/etc/resolv.conf`, and if a loopback
address sat there (which happens on DSM with the DNS Server package), inside a container
it would point at the container itself. Hence the idea of pinning explicit public
resolvers.

Measured on a live NAS, that turned out to be false. `/etc/resolv.conf` held
`nameserver 192.168.1.1` — the router, not a loopback — and answered **20/20 queries in
5 ms**, faster than any public resolver. Pinning `1.1.1.1` therefore pushed every lookup
out through NAT, adding unreliability where there had been none, and name resolution
started failing intermittently.

**The rule:** the default behaviour (embedded resolver → the host's resolver) is both the
shortest and the fastest path. Add `dns:` **only** after confirming the host's resolver
is genuinely broken:

```bash
ssh <nas> 'cat /etc/resolv.conf; python3 -c "import socket;print(socket.gethostbyname(\"api.binance.com\"))"'
```

A loopback address in `resolv.conf`, or an exception from `gethostbyname`, means the
theory holds and you should set `dns:`. Anything else means look elsewhere.

**An important caveat:** you get the same message (`Temporary failure in name
resolution`) when the cause has nothing to do with DNS at all — see "DNS, or no way out?"
below. That is precisely the trap that leads to swapping resolvers when the problem is a
layer down.

**Checking after startup — no root needed, just SSH with a key.** Do not go into the
container (that needs `sudo`, see step 5); look at the files the engine writes to the
NAS's disk:

```bash
ssh <nas> 'python3 -c "import json;s=json.load(open(\"/volume1/docker/trademon/runtime/prog_050/state.json\"));print(s[\"updated_at\"], len(s[\"last_close\"]), \"pairs\")"'
```

It should show a fresh timestamp and **18 pairs** (that is what `exchange.symbols` counts
since 0.1.11; it was 10 before). Zero pairs means the engine never reached the exchange
and fell over before its first candle fetch — so DNS still is not working and there is no
point looking for the cause in the bot's code. A second signal: `ls -l` on
`runtime/prog_050/equity.jsonl` — if `state.json` is seconds old while `equity.jsonl` is
hours old, a restart loop is in progress.

Container logs are in Container Manager → *Container* → `trademon-bot-1` → *Log*.

### When the bot cannot reach the exchange — measure from inside the container

`Temporary failure in name resolution` (`EAI_AGAIN`) means only that **the resolver did
not answer**. It does not mean DNS is at fault: a query with no way out produces an
identical message. That once cost half a night of changing resolvers when the cause was
somewhere else entirely.

**Do not infer from the host or from state files** — the container has its own network
namespace, so a working `nslookup` on DSM says nothing about it. Go inside: Container
Manager → *Container* → `trademon-bot-1` → *Terminal* (no ssh, no root) and paste this.
The image is `python:3.12-slim`, so there is no `dig`, `ping` or `curl` — Python does the
job:

```bash
python3 - <<'EOF'
import socket, struct, random

def tcp(ip, port=443, t=5):
    s = socket.socket(); s.settimeout(t)
    try: s.connect((ip, port)); return "OK"
    except Exception as e: return "FAILED: %s" % e
    finally: s.close()

def dns(server, name="google.com", t=3):
    p = struct.pack(">HHHHHH", random.randint(0, 65535), 0x0100, 1, 0, 0, 0)
    for part in name.split("."): p += bytes([len(part)]) + part.encode()
    p += b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(t)
    try: s.sendto(p, (server, 53)); s.recvfrom(512); return "OK"
    except Exception as e: return "FAILED: %s" % e
    finally: s.close()

# Substitute an address of your own for the first line: any host that answers on 443.
# A hardcoded IP goes stale, and the point is only to test TCP without involving DNS.
print("1. TCP by raw IP, no DNS       :", tcp("1.1.1.1"))
print("2. DNS straight to 1.1.1.1     :", dns("1.1.1.1"))
print("3. DNS straight to your router :", dns("192.168.1.1"))
print("4. DNS via Docker's resolver   :", dns("127.0.0.11"))
EOF
```

| Result | Cause |
|---|---|
| 1 fails | the container has no way out at all; DNS is merely the first casualty |
| 1 OK, 2–4 fail | **outbound UDP is blocked** — see below; this was the case here |
| 1–3 OK, only 4 fails | Docker's embedded resolver; reduce the query rate on the bot's side |
| everything OK | you hit a working window — repeat it several times in a row |

#### The DSM firewall versus the container subnet

A firewall profile ends in a **Deny All** rule. If the Allow rule above it covers
`172.17.0.1/255.255.255.0` — the **default** Docker bridge — but Compose put the project
on its own network (`trademon_default` = `172.18.0.0/16`), the project's traffic matches
no Allow rule and falls into Deny. That netmask is too narrow even for `172.17`, because
Docker hands out addresses from the whole `/16`.

The effect is misleadingly mild: **UDP/53 alone is dropped while TCP passes**. The bot
then lives on held-open keep-alive connections and only breaks when it has to resolve a
name afresh — which looks like flickering connectivity rather than a block.

**The fix:** Control Panel → Security → Firewall → edit the profile, and **above** the
final Deny add: Ports=All, Protocol=All, Source IP `172.16.0.0`, netmask `255.240.0.0`,
Action=Allow. Deliberately broad — it covers `172.16.0.0–172.31.255.255`, so it survives
recreating the project, when Docker takes the next free subnet. The `172.17` rule can
then be removed.

## 5. Starting the containers

**The Container Manager GUI is the route that works.** *Project* tab → *Create* → point
at the folder with `docker-compose.yml` → build. For later code changes: *Project* →
select the project → **Stop** → *Action* → **Build** → *Run*. That is the equivalent of
`docker compose up -d --build`; *Run* on its own **does not rebuild the image** and
leaves the old code in place, which looks like a deployment that changed nothing.

Stopping is not optional: the GUI will not rebuild the image of a running project. So
stop → build → run is the whole procedure, not a cautious extra.

**Why not over SSH.** `ssh <nas> 'sudo docker compose up -d --build'` is tempting, but it
fails twice, differently each time:

1. In a non-interactive `ssh <nas> '<command>'` the PATH is trimmed and `docker` ends in
   `command not found` — the binary is at `/usr/local/bin/docker`.
2. Even with the full path, `sudo` on DSM **demands a password** (`sudo -n` returns "a
   password is required"), and the `/var/run/docker.sock` socket is `root:root` with
   `srw-rw----`, so there is no access without root. Being in the `administrators` group
   does not change that — there is no `docker` group here.

That leaves `ssh -t <nas>` and typing the password by hand, but if you are sitting at the
keyboard anyway, the GUI is faster and less error-prone. For **reading**, SSH is
excellent and a key is enough — see the verification below.

`docker-compose.yml` already has `restart: unless-stopped` on every service, so the
containers come back on their own after a NAS reboot — just verify in Container Manager
that the project has "run on startup" enabled.

## 6. LAN access

The panel: `http://<nas-ip>:8501`, on your home network.

- **Do not** forward port 8501 on your router. The panel has no authentication and lets
  anyone who reaches it change the running configuration.
- If the DSM firewall is on, consider a rule under Control Panel → Security → Firewall
  restricting port 8501 to the LAN subnet.
- Give the NAS a fixed IP (a DHCP reservation on the router) so the link stops changing.

## 7. Resources: the `refresher` service

`refresher` trains LightGBM once a week (`scripts/refresh.py`). On a weaker NAS (little
RAM or CPU) that can be noticeably slower than on a workstation. Two options:

- Leave it — it runs in the background once every 7 days and does not block the dashboard.
- Disable it on the NAS (`docker compose stop refresher`, or comment the service out of
  `docker-compose.yml`) and keep training locally, then send just `models/` across
  (`tar czf - models | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'`).

## 8. Updating the application later

With no git on the NAS, an update means sending the source (SSH; a key is enough) and
rebuilding the image (the GUI, because that needs root — see step 5). Four steps below,
because the middle two are easy to perform in a way that looks successful and is not.

**1. Check you are not about to send someone else's settings.**

```bash
ls config/*.overrides.yaml
```

The panel writes that file, and the one on the NAS lives its own life. Tar does not
delete it, but it **overwrites** it if you have a local copy, so settings saved from the
panel on the NAS revert to whatever happens to be on your machine. That once cost a
restored position cap that had just been lifted from the panel. If your local copy is
only a leftover from experimenting at home, delete it before sending.

**2. Send the source.** From your machine, after a `git pull`:

```bash
COPYFILE_DISABLE=1 tar czf - src scripts config Dockerfile docker-compose.yml pyproject.toml .env.example README.md docs | ssh <nas> 'tar xzf - -C /volume1/docker/trademon'
```

**3. Rebuild the image.** Container Manager → *Project* → `trademon` → **Stop** →
*Action* → **Build** → *Run*. Stopping is required: the GUI will not rebuild a running
project's image. *Run* without *Build* brings the old image back up and nothing changes.

**4. Verify it really rebuilt.** `src/` is compiled into the image (`COPY src` +
`pip install .`) rather than mounted, so fresh files on the NAS's disk do **not** mean
fresh code in the container.

The version number under the title at `http://<nas>:8501` is the first check, but it
**only proves the dashboard container is fresh**. The engine is a separate container and
can, after an unfinished deployment, keep running on the old image — which from outside
looks like a successful update. Ask the engine separately:

```bash
ssh <nas> 'python3 -c "import json;s=json.load(open(\"/volume1/docker/trademon/runtime/prog_050/state.json\"));print(s[\"updated_at\"]);print(s.get(\"live_config\",\"MISSING — the engine is still the old one\"))"'
```

A fresh `updated_at` **and** a present `live_config` (the key exists since 0.1.7) mean the
new engine really came up. A fresh `updated_at` without `live_config` is a
pre-update image that is still trading.

`config/`, `data/`, `models/` and `runtime/` are bind-mounted from outside the container,
so rebuilding the image never touches history. Watch out for `config/`: tar
**overwrites** every file it carries, so the baseline `config/*.yaml` arrive from your
machine. Panel overrides survive only if you have no local copy of them — which is why
step 1 tells you to check before sending, not after.

## 9. Backup

`runtime/` is the only directory holding real, unreproducible history (trades, equity).
It is worth bringing `/volume1/docker/trademon` into an existing Synology mechanism —
Hyper Backup, or volume snapshots — rather than relying solely on the NAS's disk never
failing.
