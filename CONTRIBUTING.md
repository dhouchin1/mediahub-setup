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
├── routes/          # One Flask Blueprint per wizard step (welcome → done)
├── templates/       # Jinja2 HTML (HTMX + Alpine.js + Tailwind CDN)
├── compose/         # docker-compose.yml.j2 — add new services here
├── arr_client.py    # REST clients for Sonarr, Radarr, Prowlarr, qBittorrent
├── wiring_runner.py # Idempotent task list — add new service wiring here
├── installer.py     # Renders compose template, runs docker compose up
├── preflight.py     # Docker / port / disk checks
└── drives.py        # Drive enumeration (macOS diskutil-based)
```

## Adding a new service

1. Add the service to `compose/docker-compose.yml.j2`.
2. If it has a REST API, add a client class to `arr_client.py`.
3. Add wiring tasks to `wiring_runner.py` following the existing pattern.
4. Add tests in `tests/` — mock the HTTP client with `responses` or `unittest.mock`.

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
