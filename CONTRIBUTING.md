# Contributing to mediahub-setup

Thanks for your interest in contributing! This is a focused project — pull requests that fix bugs, improve the wizard UX, or add new services to the stack are very welcome.

## Quick start

```bash
git clone https://github.com/dhouchin1/mediahub-setup
cd mediahub-setup
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
mediahub-setup          # runs the wizard on a random free port
```

## Running tests

```bash
pytest -v               # all tests
pytest tests/test_wiring_runner.py -v   # a specific module
ruff check .            # lint
ruff format --check .   # format check
```

Tests run against mocked HTTP clients — no Docker or live services needed. The exception is `tests/test_e2e_contract.py`, which spins up a real Flask app.

## Architecture overview

```
mediahub_setup/
├── routes/            # One Flask Blueprint per wizard step (welcome → done)
├── templates/         # Jinja2 HTML (HTMX + Alpine.js + Tailwind CDN)
├── compose/           # docker-compose.yml.j2 — add new services here
├── services.py        # Declarative catalog every other module reads
├── roles.py           # Deployment roles (all_in_one / seedbox / receiver)
├── platform_detect.py # is_macos()/is_linux() — branch here, not on platform.system()
├── arr_client.py      # REST clients for Sonarr, Radarr, Prowlarr, qBittorrent
├── syncthing_client.py# Syncthing REST client (seedbox ↔ receiver sync)
├── wiring_runner.py   # Idempotent task list — add new service wiring here
├── installer.py       # Renders compose template, runs docker compose up
├── preflight.py       # Docker / port / disk / Tailscale checks
└── drives.py          # Drive enumeration (macOS diskutil + Linux lsblk backends)
```

## Adding a new service

1. Add a `ServiceDef` entry to `services.py` and register it in `OPTIONAL`
   (the settings checkbox, Done card, and dashboard pick it up automatically).
2. Add a `{% if 'x' in enabled_services %}` block to `compose/docker-compose.yml.j2`.
3. If it has a REST API, add a client class (mirror `bazarr_client.py` /
   `syncthing_client.py`).
4. Add wiring tasks to `wiring_runner.py` following the existing pattern.
5. Add tests in `tests/` — mock the HTTP client with `unittest.mock`.

## Conventions to follow

- **Platform branches** go through `platform_detect.is_macos()` / `is_linux()`
  so tests can monkeypatch one place — never call `platform.system()` directly.
- **Role-specific behaviour** goes through `roles.py` helpers
  (`installs_arr`, `is_server`, …). Keep `all_in_one` byte-compatible with the
  pre-role output, and keep the core wiring plan at 15 tasks (gate anything new
  behind a role/service). Tests assert these counts.
- **Never bind to `0.0.0.0` on a seedbox** — published web-UI ports use the
  `lb` (loopback) prefix in the compose template; torrent/sync ports don't.

## Pull request checklist

- [ ] `pytest -v` passes locally
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] New behaviour is covered by at least one test
- [ ] The wizard still runs end-to-end (`mediahub-setup` → step through all 7 steps)

## Reporting bugs

Please open a [GitHub Issue](https://github.com/dhouchin1/mediahub-setup/issues) using the **Bug report** template. Include your macOS version, Docker version, and the full terminal output if the wizard crashes.

## Suggesting features

Open an issue using the **Feature request** template. The most-wanted features are tracked in the [roadmap section of the README](README.md#whats-coming-next).

## Code style

- Python: [`ruff`](https://github.com/astral-sh/ruff) for linting and formatting (configured in `pyproject.toml`)
- HTML/JS: no formatter enforced — match the surrounding style
- Commit messages: imperative mood, short subject line (`Add Jellyfin compose service`, not `Added jellyfin`)

## License

By contributing you agree that your changes will be released under the project's [MIT license](LICENSE).
