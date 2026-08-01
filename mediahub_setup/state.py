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
            _state = json.loads(_STATE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            _state = {}


def _save() -> None:
    try:
        # This file holds plaintext secrets (the shared/qBittorrent password
        # and VPN credentials via the persisted `settings` dict), so it must
        # be owner-only — matching the 0600 host-secret files written
        # elsewhere. Create it 0600 from the start (no world-readable window)
        # and tighten any pre-existing file left over from an older version.
        fd = os.open(_STATE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(_state, indent=2))
        os.chmod(_STATE_PATH, 0o600)
    except OSError:
        pass  # non-fatal — state will just not persist across runs


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
