"""Shared wizard state.

The wizard is single-user and single-process by design (local install
tool), so we use a module-level dict guarded by a lock. Persisted to
~/.mediahub-setup-state.json on every write so re-running the CLI
resumes where you left off.
"""

from __future__ import annotations

import json
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
        _STATE_PATH.write_text(json.dumps(_state, indent=2))
        # Wizard state carries the shared password and *arr API keys; this file
        # lives in the user's home and is never mounted, so restrict it to the
        # owner rather than the world-readable default.
        _STATE_PATH.chmod(0o600)
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
