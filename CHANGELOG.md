# Changelog

All notable changes to mediahub-setup will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added — Phase 1 + 2 expansion (optional services framework)

- **`mediahub_setup/services.py`** — declarative catalog of every service the wizard
  can install (core + optional). Drives the compose template, settings form, wiring
  runner, dashboard, and Done page from a single source of truth.
- **Optional services** togglable from Settings:
  - **Jellyfin** — media server so you can actually play your library
  - **Jellyseerr** — request UI for non-technical users (designed to be embedded
    in external dashboards / family-hub apps via its REST API)
  - **Bazarr** — automatic subtitle downloads (auto-wired to Sonarr + Radarr)
  - **Notifiarr** — notification router with **Telegram bot** integration; settings
    accept bot token + chat ID and the wiring step adds Notifiarr as a Connect
    target in both Sonarr and Radarr so download events fire to Telegram
  - **Recyclarr** — auto-applies TRaSH Guides quality profiles on a daily cron
  - **Caddy** — reverse proxy with auto-HTTPS for public domains, plain HTTP for
    `.local` (writes `~/mediahub/config/caddy/Caddyfile`)
  - **Flaresolverr** — Cloudflare bypass proxy for indexers
- **Post-install Dashboard** (`/dashboard`) — live container health grid, per-service
  CPU/RAM gauges, restart buttons, disk-usage bar, all polling every 3s via HTMX.
- **Update-all-containers tab** — `docker compose pull && up -d` with streaming logs.
- **Repair / Resume mode** (`/repair`) — detects partial installs (state file,
  rendered compose, running containers, completed wiring tasks), highlights what's
  missing or failed, and offers a one-click resume.
- **Welcome page banner** — when partial state is detected, surface a "Resume /
  repair" call-to-action instead of forcing a fresh restart.
- **Dependency resolution** — selecting Jellyseerr in Settings auto-enables Jellyfin
  (and Sonarr/Radarr, which are core anyway).
- **`mediahub_setup/docker_ops.py`** — wrapper around `docker ps`, `docker stats`,
  `docker logs`, `docker restart` for the dashboard.
- New client modules: `jellyfin_client.py`, `jellyseerr_client.py`,
  `bazarr_client.py`. Each polls the new service's health endpoint after install.
- New config generators: `notifiarr.py` (TOML + webhook wiring), `recyclarr.py`
  (YAML), `caddy.py` (Caddyfile with conditional service blocks).

### Fixed
- Two stale GitHub URLs in templates (`base.html`, `done.html`) now point to
  `dhouchin1/mediahub-setup` instead of broken paths.
- Port validation now accepts privileged ports (1-1023) so Caddy can bind 80/443.

### Added — Original v0.1.0 work
- Full 7-step web wizard: welcome → preflight → drive picker → settings →
  install → auto-wiring → done
- Live log streaming on the install screen via HTMX polling
- Auto-wiring: qBittorrent password, Prowlarr application registration,
  Sonarr/Radarr download client + root folder + hardlinks flag
- Drive picker with NTFS detection (flags as read-only, recommends reformatting)
- System-defaults detection (timezone, PUID/PGID, free ports)
- Auto-generated shared password (16 chars, no ambiguous characters)
- `docker-compose.yml` template using TRaSH Guides single-mount convention
- `scripts/install.sh` one-liner curl installer
- `mediahub_setup/menubar.py`: native macOS menu-bar wrapper (`rumps`) with
  health-polling timer, browser-open action, and graceful Quit
- `mediahub-setup-menubar` CLI entry point (`pip install 'mediahub-setup[menubar]'`)
- `packaging/py2app/`: build script + bootstrap for standalone `.app` bundle
- `.github/workflows/build-app.yml`: builds and uploads DMG on each release
- GitHub Actions CI (Python 3.12 + 3.13, macOS runner) and PyPI publish
  workflow (OIDC trusted publishing)
- Homebrew formula template in `packaging/homebrew/`
- 100+ unit + integration tests, including an end-to-end wizard smoke test
  that validates cross-step state contracts

---

[Unreleased]: https://github.com/dhouchin1/mediahub-setup/compare/HEAD...HEAD
