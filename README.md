# mediahub-setup

A friendly web wizard that gets you from "blank Mac" to "working
self-hosted Sonarr + Radarr stack" in about 15 minutes — no config
files to hand-edit, no API keys to copy-paste by hand.

![status: early alpha](https://img.shields.io/badge/status-alpha-orange)
[![CI](https://github.com/dhouchin/mediahub-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/dhouchin/mediahub-setup/actions/workflows/ci.yml)

---

## Install

### One-liner (fastest)

```bash
curl -fsSL https://raw.githubusercontent.com/dhouchin/mediahub-setup/main/scripts/install.sh | bash
```

The script installs `pipx` if you don't have it, then isolates
`mediahub-setup` in its own virtualenv. Nothing touches your system Python.

### pipx (manual)

```bash
brew install pipx && pipx ensurepath
pipx install mediahub-setup
```

### Homebrew tap (coming after first release)

```bash
brew tap dhouchin/mediahub
brew install mediahub-setup
```

---

## Run

```bash
mediahub-setup                 # auto-pick a free port, open browser
mediahub-setup --port 5000     # specific port
mediahub-setup --no-browser    # skip auto-open
```

---

## What it does

Walks you through seven steps:

| Step | What happens |
|------|-------------|
| **Welcome** | Intro + "let's go" |
| **Preflight** | Checks Docker is running, ports are free, disk space OK |
| **Drive picker** | Lists drives, flags NTFS (read-only on macOS), helps you pick or reformat |
| **Settings** | Timezone, custom ports, auto-generated shared password |
| **Install** | Renders `docker-compose.yml`, pulls images, streams `docker compose up -d` live |
| **Wire-up** | Hits Sonarr/Radarr/Prowlarr/qBittorrent APIs to wire them together automatically |
| **Done** | Prints every service URL + credentials — ready to add your first movie |

---

## Requirements

- macOS 13 Ventura or later (Apple Silicon or Intel)
- Python 3.12+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or
  [OrbStack](https://orbstack.dev/) running
- An APFS-formatted external drive (or partition) for media storage
  — NTFS drives are automatically flagged read-only during the drive step

---

## What it doesn't do (yet)

- Linux / Windows support (macOS-first; Linux next)
- Native menu-bar app (planned)
- Resumable installs across reboots
- Indexer pre-population (you still pick which trackers to add in Prowlarr)

---

## Architecture

- **Python 3.12 + Flask + waitress** — runs locally on `127.0.0.1`, single-user,
  no auth required
- **HTMX + Alpine.js + Tailwind via CDN** — no build step, the wheel ships
  templates as package data
- **Generates a standalone `~/mediahub/docker-compose.yml`** — the install
  survives uninstalling this tool
- **TRaSH Guides single-mount** — all containers share `MEDIA_ROOT:/data` so
  Sonarr/Radarr can hardlink instead of copy

---

## Development

```bash
git clone https://github.com/dhouchin/mediahub-setup
cd mediahub-setup
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
mediahub-setup          # starts wizard on a random free port
```

```bash
pytest -v               # all 100+ tests
ruff check .            # lint
ruff format --check .   # format check
```

---

## Publishing a new release

1. Bump `version` in `pyproject.toml`.
2. Commit and tag: `git tag v0.x.y && git push --tags`.
3. Create a GitHub Release from the tag — the
   [publish workflow](.github/workflows/publish.yml) uploads to PyPI
   automatically via OIDC trusted publishing (no API token needed).
4. Update `packaging/homebrew/mediahub-setup.rb` with the new PyPI sdist
   URL + SHA256, then push to the
   [homebrew-mediahub](https://github.com/dhouchin/homebrew-mediahub) tap repo.

---

## License

MIT
