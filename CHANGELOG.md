# Changelog

All notable changes to mediahub-setup will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added — unattended ops (`install --dry-run`, `doctor`, `down`)

- **`mediahub-setup down`** — stops the stack (`docker compose down`) from the
  CLI. The bind-mounted media library is never touched; named volumes (service
  configs + the \*arr/qBittorrent databases) are **preserved** by default so a
  later `mediahub-setup` brings the same deployment back. `--volumes` wipes them
  for a clean slate, gated behind a confirmation prompt (`--yes` to skip).

- **`mediahub-setup install --dry-run`** — validates the config and runs
  preflight, resolves the data directory and builds the `settings` contract,
  then prints the resolved plan (services + published ports, and the exact
  wiring tasks that would run) and stops **before** rendering compose, starting
  containers, or wiring. Returns the same per-phase exit codes on failure, so
  it doubles as a cloud-init pre-check: catch a bad `seedbox.yml` before
  committing a fresh VPS to `docker compose up`.
- **`mediahub-setup doctor`** — read-only post-install health check for a
  running deployment. Probes the Docker daemon, reports every `mediahub-*`
  container's state, and shows disk headroom on the install dir (and `--data-dir`
  if given). For server roles, `--role seedbox` adds a Tailscale connectivity
  check. Exit codes (0 healthy / 1 unhealthy / 2 no-Docker / 3 not-installed)
  make it dependable in a cron or monitoring job on a headless seedbox.

### Added — fully-automated (headless) install

- **`mediahub-setup install` subcommand** — a non-interactive, config-driven
  install for unattended bring-up (cloud-init / a fresh VPS). Runs the same
  pipeline as the web wizard (preflight → drive → settings → `docker compose up
  -d` → wiring) from a YAML/JSON config plus flags, streams progress, and
  returns a distinct exit code per phase. Bare `mediahub-setup` still launches
  the wizard; `mediahub-setup serve` is the explicit alias.
- **`settings_builder.py`** — builds the exact wizard `settings` contract from a
  plain config mapping (no Flask form), reused by the headless path. A
  key-parity test guards against drift from the `/settings` route.
- **`headless.py`** — the orchestrator; on success prints the service URLs and
  the seedbox's own Syncthing device ID (reachable over Tailscale on a seedbox).
- **`scripts/install.sh` now supports Linux** (apt/dnf/yum/pacman with a
  pip-user fallback, plus an opt-in `MEDIAHUB_INSTALL_DOCKER=1` Docker Engine
  bootstrap) and **passes extra args through to `mediahub-setup`**, enabling a
  true one-liner: `curl … | bash -s -- install --role seedbox --config seedbox.yml --yes`.
- **`examples/seedbox.yml` + `examples/receiver.yml`** — documented config
  templates; `docs/REMOTE-SEEDBOX.md` now leads with the automated path.

### Added — remote seedbox topology

- **Deployment roles** (`mediahub-setup --role=all-in-one|seedbox|receiver`, also
  a picker on the Welcome screen). `all_in_one` is the default and unchanged.
  `seedbox` runs the acquisition stack on a remote Linux VPS; `receiver` runs
  only Syncthing on a home machine to hold the synced library. New
  `mediahub_setup/roles.py` keeps the logic in one place.
- **Linux support.** `drives.py` gains an `lsblk`/`/proc/mounts` backend behind
  a `platform_detect` dispatch (macOS keeps `diskutil`); preflight skips the
  macOS `/Volumes` file-sharing probe and adapts Docker detection; the drive
  step has a manual-path entry for headless servers. `mediahub-setup` now runs
  on Ubuntu/Debian, and CI runs the suite on macOS **and** Linux.
- **Syncthing** as an optional service — replicates only the organised
  `Media/` library (never `Torrents/`). The wizard auto-configures the folder
  **Send-Only** on a seedbox and **Receive-Only with forced Staggered
  versioning** on a receiver, and surfaces each node's device ID for pairing on
  the Done page. New `syncthing_client.py` drives the Syncthing REST API.
- **Gluetun VPN toggle** — optionally routes qBittorrent through a WireGuard/
  OpenVPN tunnel (`network_mode: service:gluetun`) with port-forwarding for
  seeding. VPN secrets are written to `.env`, never the compose file. Caddy and
  the *arr download-client wiring follow qBittorrent to the gluetun netns.
- **Tailscale-first hardening** — on a seedbox every published web UI binds to
  `127.0.0.1` (reached over Tailscale or an SSH tunnel), Caddy local mode is
  pre-checked, and a preflight check nudges installing/connecting Tailscale.
- **Seedbox retention** — qBittorrent ratio/seed-time share limits with a
  remove-and-delete action so a small VPS disk auto-prunes; the hardlinked
  `Media/` library (and the synced home copy) is unaffected.
- **`docs/REMOTE-SEEDBOX.md`** — end-to-end VPS + Mac walkthrough, including the
  deletion-propagation safety rule (receiver versioning is non-negotiable).

### Added — sync with media-hub canonical stack

- **Overseerr** as a first-class optional service (`sctx/overseerr:latest`,
  port 5055). The wizard now defaults to Overseerr instead of Jellyseerr;
  Jellyseerr remains available for users who prefer the Jellyfin-flavoured
  fork (it now defaults to port 5056 to avoid the Overseerr conflict).
- **MediaHub Web UI** as an optional service — the custom Next.js dashboard
  from the [media-hub repo](https://github.com/dhouchin1/media-hub) that
  surfaces library status, downloads, and request shortcuts. Ships as
  `ghcr.io/dhouchin1/mediahub-web:latest`. The installer also supports
  pointing `web_build_context` at a local checkout for development.
- **Caddy `local` mode** — per-port site blocks guarded by an IP allowlist
  (loopback + RFC1918 + `100.64.0.0/10` for Tailscale). This is now the
  default when Caddy is enabled. Existing `public` (path-routed + auto-HTTPS)
  mode is still available behind a mode picker on the Settings step.
- **Unified `RequestAppClient`** in `overseerr_client.py` — Overseerr and
  Jellyseerr share a REST API, so the wiring step uses one client for both.
  The old `JellyseerrClient` import alias is preserved for back-compat.

### Changed

- **qBittorrent default port: 8080 → 8090** (8080 collides with too many
  other local dev servers). Existing installs keep whatever port they wrote
  to the rendered `docker-compose.yml`; only the wizard's *default* changed.
- **Jellyfin media mount is now read-only** (`${MEDIA_ROOT}/media:/data/media:ro`)
  — Jellyfin doesn't need to write to the library and read-only blocks
  accidents.
- **`.env` writer** now emits `SONARR_API_KEY`, `RADARR_API_KEY`,
  `PROWLARR_API_KEY`, `BAZARR_API_KEY`, `QBITTORRENT_USERNAME`, and
  `QBITTORRENT_PASSWORD` so the custom web service can authenticate to the
  arr stack. Values are backfilled by the wiring step.
- **Compose template** drops per-service host port bindings when Caddy is
  enabled in `local` mode — Caddy alone publishes the host ports, keeping
  the IP allowlist effective.

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
