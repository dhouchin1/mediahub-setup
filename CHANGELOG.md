# Changelog

All notable changes to mediahub-setup will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
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

[Unreleased]: https://github.com/dhouchin/mediahub-setup/compare/HEAD...HEAD
