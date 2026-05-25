# mediahub-setup

> **From blank Mac to fully wired self-hosted media server in ~15 minutes — no config files to hand-edit, no API keys to copy-paste.**

A 7-step web wizard that installs and auto-wires a self-hosted media stack using Docker, following the [TRaSH Guides](https://trash-guides.info/) single-mount convention for hardlinks. The core 4-service stack is always installed; optional add-ons (Jellyfin, Jellyseerr, Bazarr, Notifiarr+Telegram, Recyclarr, Caddy, Flaresolverr) are togglable from the Settings step.

![status: alpha](https://img.shields.io/badge/status-alpha-orange)
[![CI](https://github.com/dhouchin1/mediahub-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/dhouchin1/mediahub-setup/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

<!-- TODO: Add demo GIF here once recorded -->
<!-- ![MediaHub Setup demo](docs/demo.gif) -->

---

## What you get

### Core stack (always installed)

| Service | Port | What it does |
|---------|------|--------------|
| [Sonarr](https://sonarr.tv/) | 8989 | TV series manager — finds, downloads, and organises episodes |
| [Radarr](https://radarr.video/) | 7878 | Movie manager — same idea, but for films |
| [Prowlarr](https://github.com/Prowlarr/Prowlarr) | 9696 | Indexer hub — one place to manage all your trackers; Sonarr + Radarr query it automatically |
| [qBittorrent](https://www.qbittorrent.org/) | 8080 | Torrent client — downloads to `/data/torrents`, Sonarr/Radarr hardlink into `/data/media` |

All four services share a **single `/data` mount** on your external drive so hardlinks work, saving you a full second copy of every file.

### Optional add-ons (toggle in Settings)

| Service | Port | What it does |
|---------|------|--------------|
| [Jellyfin](https://jellyfin.org/) | 8096 | Free media server — actually *play* your library on TVs, phones, browsers |
| [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) | 5055 | Request UI for non-technical household members; auto-wires to Sonarr/Radarr |
| [Bazarr](https://www.bazarr.media/) | 6767 | Subtitle downloader — wires to Sonarr + Radarr automatically |
| [Notifiarr](https://notifiarr.com/) + Telegram | 5454 | Webhook router with a **Telegram bot** to tell you when downloads finish |
| [Recyclarr](https://recyclarr.dev/) | — | Auto-syncs TRaSH Guides quality profiles into Sonarr/Radarr nightly |
| [Caddy](https://caddyserver.com/) | 80 / 443 | Reverse proxy with auto-HTTPS; expose everything under one hostname |
| [Flaresolverr](https://github.com/FlareSolverr/FlareSolverr) | 8191 | Cloudflare bypass for protected indexers |

Selecting Jellyseerr automatically enables Jellyfin (dependency resolution is handled for you).

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

- macOS 13 Ventura or later (Apple Silicon or Intel)
- Python 3.12+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or [OrbStack](https://orbstack.dev/) running
- An APFS-formatted external drive (or partition) for media storage

NTFS drives are automatically detected and flagged as unsafe for hardlinks during the drive step.

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

- [ ] **Linux support** (Ubuntu/Debian) — only `drives.py` is macOS-specific right now
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
