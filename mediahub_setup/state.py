"""Shared wizard state.

The wizard is single-user and single-process by design (local install
tool), so we use a module-level dict guarded by a lock. Persisted to
~/.mediahub-setup-state.json on every write so re-running the CLI
resumes where you left off.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_STATE_PATH = Path.home() / ".mediahub-setup-state.json"
_lock = threading.Lock()
_state: dict[str, Any] = {}


def _load() -> None:
    global _state
    if _STATE_PATH.exists():
        try:
            data = json.loads(_STATE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        # Valid JSON that isn't an object (null, [], a truncated-then-edited
        # file) would otherwise make every state.get() raise on the first
        # request, with no in-app way to recover.
        _state = data if isinstance(data, dict) else {}


def _save() -> None:
    # The file holds plaintext secrets (shared/qBittorrent password, VPN
    # credentials via the persisted settings dict), so it must be owner-only
    # from the moment it exists. Write to a sibling temp file and rename so
    # a crash or kill mid-write can't leave a truncated file that _load()
    # silently discards — which would forget the whole install, passwords
    # included.
    tmp = _STATE_PATH.with_name(_STATE_PATH.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(_state, indent=2))
        os.replace(tmp, _STATE_PATH)
        os.chmod(_STATE_PATH, 0o600)  # tighten a file left by an older version
    except OSError:
        # non-fatal — state will just not persist across runs
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


_load()


def get(key: str, default: Any = None) -> Any:
    with _lock:
        return _state.get(key, default)


def set(key: str, value: Any) -> None:  # noqa: A001 — shadowing builtin OK in this module
    with _lock:
        _state[key] = value
        _save()


def update(**kwargs: Any) -> None:
    with _lock:
        _state.update(kwargs)
        _save()


def clear() -> None:
    with _lock:
        _state.clear()
        _save()


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_state)
