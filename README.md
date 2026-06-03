# mediahub-setup

> **From blank Mac to fully wired self-hosted media server in ~15 minutes — no config files to hand-edit, no API keys to copy-paste.**

A 7-step web wizard that installs and auto-wires a self-hosted media stack using Docker, following the [TRaSH Guides](https://trash-guides.info/) single-mount convention for hardlinks. The core 4-service stack is always installed; optional add-ons (Jellyfin, **Overseerr**, Jellyseerr, Bazarr, **MediaHub Web UI**, Notifiarr+Telegram, Recyclarr, Caddy, Flaresolverr, **Syncthing**, **Gluetun VPN**) are togglable from the Settings step. It also runs on **Linux** and supports a [remote-seedbox topology](docs/REMOTE-SEEDBOX.md) — downloads on a VPS, library synced home.

![status: alpha](https://img.shields.io/badge/status-alpha-orange)
[![CI](https://github.com/dhouchin1/mediahub-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/dhouchin1/mediahub-setup/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

<!-- TODO: Add demo GIF here once recorded -->
<!-- ![MediaHub Setup demo](docs/demo.gif) -->

---

## Quickstart

Same tool on every machine — pick a role with `--role` (or on the Welcome screen).
*First time? [Install it](#install) first.*

### All-in-one (one machine)

```bash
mediahub-setup          # opens the wizard in your browser → click through the 7 steps
```

### Remote seedbox → home (two machines)

Downloads run on a cheap Linux VPS; only the **organized library** syncs home to a Mac.
Full walkthrough with troubleshooting: **[docs/REMOTE-SEEDBOX.md](docs/REMOTE-SEEDBOX.md)**.

**1 · On the VPS** *(after installing Docker + Tailscale):*

```bash
mediahub-setup --role=seedbox --no-browser     # binds localhost; prints a URL + port
# reach the wizard from your laptop over an SSH tunnel (use the port it printed):
ssh -L 7842:127.0.0.1:7842 you@your-vps        # then open http://localhost:7842
```

Step through **Install → Wire-up**, then **copy the VPS's Syncthing device ID** from the Done page.

**2 · On your Mac:**

```bash
mediahub-setup --role=receiver                 # auto-opens your browser
```

In **Settings**, paste the **VPS device ID** and keep the same Folder ID. It installs Syncthing **Receive-Only with versioning forced on**, then shows *this* Mac's device ID.

**3 · Pair them** — add each machine's device ID on the other and accept the shared `mediahub-media` folder. The `Media/` library now syncs down automatically; point Jellyfin/Plex at it.

> ⚠️ On the Mac, never switch the folder to *Send & Receive* or disable versioning. Syncthing's "Receive-Only" does **not** stop deletions from propagating — versioning is what keeps a VPS-side cleanup from wiping your library.

---

## What you get

### Core stack (always installed)

| Service | Port | What it does |
|---------|------|--------------|
| [Sonarr](https://sonarr.tv/) | 8989 | TV series manager — finds, downloads, and organises episodes |
| [Radarr](https://radarr.video/) | 7878 | Movie manager — same idea, but for films |
| [Prowlarr](https://github.com/Prowlarr/Prowlarr) | 9696 | Indexer hub — one place to manage all your trackers; Sonarr + Radarr query it automatically |
| [qBittorrent](https://www.qbittorrent.org/) | 8090 | Torrent client — downloads to `/data/Torrents`, Sonarr/Radarr hardlink into `/data/Media` |

All four services share a **single `/data` mount** on your external drive so hardlinks work, saving you a full second copy of every file.

### Optional add-ons (toggle in Settings)

| Service | Port | What it does |
|---------|------|--------------|
| [Jellyfin](https://jellyfin.org/) | 8096 | Free media server — actually *play* your library on TVs, phones, browsers |
| [Overseerr](https://overseerr.dev/) | 5055 | **Request UI** for non-technical household members; auto-wires to Sonarr/Radarr |
| [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) | 5056 | Jellyfin-flavoured fork of Overseerr — pick this instead if you prefer the Jellyfin-tight integration |
| [Bazarr](https://www.bazarr.media/) | 6767 | Subtitle downloader — wires to Sonarr + Radarr automatically |
| **MediaHub Web UI** | 3000 | Custom Next.js dashboard with library, downloads, and requests at a glance (image: `ghcr.io/dhouchin1/mediahub-web:latest`) |
| [Notifiarr](https://notifiarr.com/) + Telegram | 5454 | Webhook router with a **Telegram bot** to tell you when downloads finish |
| [Recyclarr](https://recyclarr.dev/) | — | Auto-syncs TRaSH Guides quality profiles into Sonarr/Radarr nightly |
| [Caddy](https://caddyserver.com/) | (varies) | Reverse proxy with two modes: **local** (per-port + IP allowlist, default) or **public** (single hostname + auto-HTTPS) |
| [Flaresolverr](https://github.com/FlareSolverr/FlareSolverr) | 8191 | Cloudflare bypass for protected indexers |
| [Syncthing](https://syncthing.net/) | 8384 | Replicate the organised library between a remote seedbox and home — see [Deployment modes](#deployment-modes) |
| [Gluetun](https://github.com/qdm12/gluetun) | — | Route qBittorrent through a VPN (WireGuard/OpenVPN) with port-forwarding for seeding |

Selecting Jellyseerr automatically enables Jellyfin. Overseerr and Jellyseerr share a port range and are mutually exclusive — pick one.

#### Caddy modes

When Caddy is enabled you choose a mode in Settings:

- **Local** *(default)* — Caddy publishes each service on its own port and rejects requests outside the loopback + RFC1918 + `100.64.0.0/10` (Tailscale) ranges. Best for LAN / Tailnet use. No TLS.
- **Public** — Caddy routes everything under a single hostname (e.g. `mediahub.example.com/sonarr/`) and automatically obtains a Let's Encrypt cert on first request. Best when you want one external URL with HTTPS. Requires ports 80/443 reachable from the internet.

---

## Deployment modes

The wizard supports three topologies, chosen on the Welcome screen or with
`mediahub-setup --role=<mode>`:

| Mode | What it does |
|------|--------------|
| **All-in-one** *(default)* | Download, organise and play everything on one machine — the classic setup. Nothing changes from previous versions. |
| **Remote seedbox** | Run the acquisition stack (qBittorrent + *arr) on a cheap **Linux VPS**, route torrents through an optional VPN, and Syncthing the organised library home. Web UIs bind to loopback / Tailscale, never the public IP. |
| **Home receiver** | Run on your Mac to receive the synced library (Syncthing **Receive-Only with versioning forced on**) and play it locally. No *arr stack. |

The seedbox + receiver pair is the "run downloads on a VPS, keep the files at
home" setup. **Full walkthrough: [docs/REMOTE-SEEDBOX.md](docs/REMOTE-SEEDBOX.md)** —
including the one Syncthing safety rule you must not break.

---

## Install

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/dhouchin1/mediahub-setup/main/scripts/install.sh | bash
```

Installs `pipx` if you don't have it, then isolates `mediahub-setup` in its own venv — nothing touches your system Python.

### pipx (manual)

```bash
brew install pipx && pipx ensurepath
pipx install mediahub-setup
```

### Homebrew tap

```bash
brew tap dhouchin1/mediahub
brew install mediahub-setup
```

### macOS menu-bar app

Download `MediaHub Setup.dmg` from the [latest GitHub Release](https://github.com/dhouchin1/mediahub-setup/releases), open it, and drag to Applications. The wizard lives in your menu bar — no Terminal needed.

---

## Run

```bash
mediahub-setup                 # auto-pick a free port, open browser
mediahub-setup --port 5000     # specific port
mediahub-setup --no-browser    # skip auto-open
```

Or install the menu-bar variant:

```bash
pipx install 'mediahub-setup[menubar]'
mediahub-setup-menubar
```

---

## Operating a deployment (CLI)

Beyond the wizard, a few non-interactive subcommands cover unattended bring-up
and day-2 ops — handy on a headless seedbox where there's no browser:

```bash
# Validate a config and preview the plan WITHOUT touching Docker (cloud-init pre-check)
mediahub-setup install --role seedbox --config seedbox.yml --dry-run

# Bring the stack up unattended from that config
mediahub-setup install --role seedbox --config seedbox.yml --yes

# Health-check a running deployment (read-only); exits non-zero if anything is wrong
mediahub-setup doctor                       # container states + disk headroom
mediahub-setup doctor --role seedbox        # + Tailscale connectivity check
mediahub-setup doctor --data-dir /mnt/media # also check the media drive's free space

# Stop the stack (media library untouched; configs/databases preserved)
mediahub-setup down
mediahub-setup down --volumes               # also wipe configs + databases (prompts first)
```

`doctor` exit codes — `0` healthy, `1` unhealthy (a container is down or disk is
critically low), `2` Docker unavailable, `3` nothing installed — make it
dependable in a cron or monitoring job.

---

## How it works

The wizard walks you through seven steps:

| Step | What happens |
|------|-------------|
| **1 · Welcome** | Intro screen |
| **2 · Preflight** | Verifies Docker is running, required ports are free, disk space is sufficient |
| **3 · Drive picker** | Lists mounted drives, flags NTFS (read-only on macOS), lets you pick your media drive |
| **4 · Settings** | Timezone, PUID/PGID, custom ports per service, auto-generated shared password |
| **5 · Install** | Renders `docker-compose.yml`, creates folder tree, pulls images, streams `docker compose up -d` live |
| **6 · Wire-up** | Hits every service's REST API to connect them: sets qBittorrent password + categories, registers Prowlarr in Sonarr/Radarr, adds download clients and root folders |
| **7 · Done** | Prints every service URL + credentials — ready to add your first movie |

After the wizard, your stack runs independently via Docker — you can manage it with `docker compose` directly. The wizard is only needed once (or to repair a broken wiring).

---

## Requirements

- **macOS 13 Ventura or later** (Apple Silicon or Intel), **or Linux** (Ubuntu/Debian — for the remote-seedbox VPS)
- Python 3.12+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) / [OrbStack](https://orbstack.dev/) on macOS, or [Docker Engine](https://docs.docker.com/engine/install/) on Linux
- A data drive or writable folder for media storage (APFS on macOS; any writable mount/folder on Linux — the drive step has a manual-path option for headless servers)

NTFS drives are automatically detected and flagged as unsafe for hardlinks during the drive step (on macOS, where NTFS is read-only).

---

## Post-install dashboard

After the wizard finishes, visit `/dashboard` in the same browser tab for:

- Live per-container CPU + RAM gauges (polled every 3s via Docker stats API)
- One-click restart for any individual service
- Disk-usage bar for your media drive
- "Update all" button that runs `docker compose pull && docker compose up -d` with streaming logs

## Resume / repair mode

If you close the wizard halfway or a wiring task fails, visit `/repair` — it inspects the current state (saved settings, rendered compose, running containers, completed wiring tasks) and walks you straight to the right next step. Failed wiring tasks can be retried without re-running the whole pipeline.

## What's coming next

- [x] **Linux support** (Ubuntu/Debian) — done; powers the remote-seedbox role
- [x] **Remote seedbox + Syncthing** — run downloads on a VPS, sync the library home
- [ ] **Backup/restore wizard** — tarball `~/mediahub/config/` and restore on a new machine
- [ ] **Windows/WSL2 support**
- [ ] **xterm.js terminal widget** for the install log stream
- [ ] **Plex** as an alternative to Jellyfin
- [ ] **Notifiarr → Discord / ntfy / Slack** routing in addition to Telegram

---

## Architecture

- **Python 3.12 + Flask + waitress** — runs on `127.0.0.1` only, single-user, no auth required
- **HTMX + Alpine.js + Tailwind via CDN** — no build step; templates ship as package data
- **Jinja2-rendered `~/mediahub/docker-compose.yml`** — the install survives uninstalling this wizard
- **TRaSH Guides single-mount** — all containers share `MEDIA_ROOT:/data`, enabling hardlinks

---

## Development

```bash
git clone https://github.com/dhouchin1/mediahub-setup
cd mediahub-setup
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
mediahub-setup          # starts wizard on a random free port
```

```bash
pytest -v               # 100+ tests
ruff check .            # lint
ruff format --check .   # format check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for pull request guidelines and development tips.

---

## Publishing a release

1. Bump `version` in `pyproject.toml`.
2. Commit and tag: `git tag v0.x.y && git push --tags`.
3. Create a GitHub Release from the tag — the [publish workflow](.github/workflows/publish.yml) uploads to PyPI automatically via OIDC trusted publishing (no API token needed).
4. Update `packaging/homebrew/mediahub-setup.rb` with the new PyPI sdist URL + SHA256, then push to the [homebrew-mediahub](https://github.com/dhouchin1/homebrew-mediahub) tap repo.

---

## License

MIT
