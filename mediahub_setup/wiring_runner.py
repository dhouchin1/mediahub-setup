"""Orchestrator for the wiring step.

Runs API calls against freshly-started containers to auto-configure the
Sonarr/Radarr/Prowlarr/qBittorrent stack. Designed to be idempotent —
safe to re-run if a previous attempt partially succeeded.

Public interface
----------------
    start_wiring()   — spawn background thread (no-op if already running)
    wiring_status()  — thread-safe snapshot of current progress
"""

from __future__ import annotations

import threading
from typing import Any

from . import state
from .arr_client import (
    ProwlarrClient,
    QBittorrentClient,
    RadarrClient,
    SonarrClient,
    get_qbittorrent_temp_password,
    read_arr_api_key,
)

# ---------------------------------------------------------------------------
# Module-level state (lives for the lifetime of the Flask process)
# ---------------------------------------------------------------------------

_lock = threading.Lock()

_status: dict[str, Any] = {
    "phase": "idle",  # idle | running | complete | failed
    "tasks": [],
}

_thread: threading.Thread | None = None

# Task definitions — order matters; each is run in sequence.
TASK_NAMES = [
    "Connect to qBittorrent",
    "Change qBittorrent password",
    "Create qBittorrent category: movies",
    "Create qBittorrent category: tv",
    "Read Sonarr API key",
    "Read Radarr API key",
    "Read Prowlarr API key",
    "Register Sonarr in Prowlarr",
    "Register Radarr in Prowlarr",
    "Add qBittorrent to Sonarr",
    "Add root folder to Sonarr (/data/media/tv)",
    "Enable hardlinks in Sonarr",
    "Add qBittorrent to Radarr",
    "Add root folder to Radarr (/data/media/movies)",
    "Enable hardlinks in Radarr",
]


def _initial_tasks() -> list[dict]:
    return [{"name": n, "status": "pending", "message": ""} for n in TASK_NAMES]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def wiring_status() -> dict[str, Any]:
    """Return a thread-safe copy of the current wiring status."""
    with _lock:
        return {
            "phase": _status["phase"],
            "tasks": list(_status["tasks"]),
        }


def start_wiring() -> None:
    """Spawn the wiring thread if it is not already running.

    Calling this a second time while the thread is active is a no-op.
    """
    global _thread, _status

    with _lock:
        if _status["phase"] == "running":
            return
        _status = {
            "phase": "running",
            "tasks": _initial_tasks(),
        }

    _thread = threading.Thread(target=_run_wiring, daemon=True)
    _thread.start()


# ---------------------------------------------------------------------------
# Internal runner
# ---------------------------------------------------------------------------


def _task_idx(name: str) -> int:
    for i, n in enumerate(TASK_NAMES):
        if n == name:
            return i
    raise KeyError(f"Unknown task: {name!r}")


def _set_task(name: str, status: str, message: str = "") -> None:
    with _lock:
        idx = _task_idx(name)
        _status["tasks"][idx] = {"name": name, "status": status, "message": message}


def _set_phase(phase: str) -> None:
    with _lock:
        _status["phase"] = phase


def _run_wiring() -> None:
    """Main wiring sequence — runs in the background thread."""
    try:
        settings = state.get("settings", {})
        shared_password = settings.get("shared_password", "")

        qb_port = settings.get("qbittorrent_port", 8080)
        sonarr_port = settings.get("sonarr_port", 8989)
        radarr_port = settings.get("radarr_port", 7878)
        prowlarr_port = settings.get("prowlarr_port", 9696)

        qb_url = f"http://localhost:{qb_port}"
        sonarr_url = f"http://localhost:{sonarr_port}"
        radarr_url = f"http://localhost:{radarr_port}"
        prowlarr_url = f"http://localhost:{prowlarr_port}"

        # Container-network URLs (used for cross-container wiring)
        sonarr_internal = f"http://sonarr:{sonarr_port}"
        radarr_internal = f"http://radarr:{radarr_port}"
        prowlarr_internal = f"http://prowlarr:{prowlarr_port}"

        api_keys: dict[str, str] = {}

        # ----------------------------------------------------------------
        # Step a: qBittorrent
        # ----------------------------------------------------------------
        qb = QBittorrentClient(qb_url)

        _set_task("Connect to qBittorrent", "running")
        try:
            temp_pw = get_qbittorrent_temp_password("mediahub-qbittorrent")
            qb.login(temp_pw)
            _set_task("Connect to qBittorrent", "ok", "Logged in with temporary password")
        except Exception as exc:
            # Maybe already changed — try with shared_password
            try:
                qb.login(shared_password)
                _set_task("Connect to qBittorrent", "ok", "Logged in with shared password")
                temp_pw = shared_password
            except Exception:
                _set_task("Connect to qBittorrent", "failed", str(exc))
                _abort()
                return

        _set_task("Change qBittorrent password", "running")
        try:
            if temp_pw != shared_password:
                qb.change_password(shared_password)
                # Re-login with new password
                qb2 = QBittorrentClient(qb_url)
                qb2.login(shared_password)
                qb = qb2
            _set_task("Change qBittorrent password", "ok")
        except Exception as exc:
            _set_task("Change qBittorrent password", "failed", str(exc))
            _abort()
            return

        _set_task("Create qBittorrent category: movies", "running")
        try:
            qb.create_category("movies", "/data/torrents/movies")
            _set_task("Create qBittorrent category: movies", "ok")
        except Exception as exc:
            _set_task("Create qBittorrent category: movies", "failed", str(exc))
            _abort()
            return

        _set_task("Create qBittorrent category: tv", "running")
        try:
            qb.create_category("tv", "/data/torrents/tv")
            _set_task("Create qBittorrent category: tv", "ok")
        except Exception as exc:
            _set_task("Create qBittorrent category: tv", "failed", str(exc))
            _abort()
            return

        # ----------------------------------------------------------------
        # Step b: Capture API keys from config.xml
        # ----------------------------------------------------------------
        for service, task_name in [
            ("sonarr", "Read Sonarr API key"),
            ("radarr", "Read Radarr API key"),
            ("prowlarr", "Read Prowlarr API key"),
        ]:
            _set_task(task_name, "running")
            try:
                key = read_arr_api_key(f"mediahub-{service}", timeout=60)
                api_keys[service] = key
                _set_task(task_name, "ok", f"Key: {key[:8]}…")
            except Exception as exc:
                _set_task(task_name, "failed", str(exc))
                _abort()
                return

        # ----------------------------------------------------------------
        # Step c: Prowlarr — register Sonarr + Radarr
        # ----------------------------------------------------------------
        prowlarr = ProwlarrClient(prowlarr_url, api_keys["prowlarr"])

        _set_task("Register Sonarr in Prowlarr", "running")
        try:
            prowlarr.add_sonarr(
                sonarr_url=sonarr_internal,
                prowlarr_url=prowlarr_internal,
                sonarr_api_key=api_keys["sonarr"],
            )
            _set_task("Register Sonarr in Prowlarr", "ok")
        except Exception as exc:
            _set_task("Register Sonarr in Prowlarr", "failed", str(exc))
            _abort()
            return

        _set_task("Register Radarr in Prowlarr", "running")
        try:
            prowlarr.add_radarr(
                radarr_url=radarr_internal,
                prowlarr_url=prowlarr_internal,
                radarr_api_key=api_keys["radarr"],
            )
            _set_task("Register Radarr in Prowlarr", "ok")
        except Exception as exc:
            _set_task("Register Radarr in Prowlarr", "failed", str(exc))
            _abort()
            return

        # ----------------------------------------------------------------
        # Step d: Sonarr — download client, root folder, hardlinks
        # ----------------------------------------------------------------
        sonarr = SonarrClient(sonarr_url, api_keys["sonarr"])

        _set_task("Add qBittorrent to Sonarr", "running")
        try:
            sonarr.add_qbittorrent(
                host="qbittorrent",
                port=qb_port,
                username="admin",
                password=shared_password,
                category="tv",
            )
            _set_task("Add qBittorrent to Sonarr", "ok")
        except Exception as exc:
            _set_task("Add qBittorrent to Sonarr", "failed", str(exc))
            _abort()
            return

        _set_task("Add root folder to Sonarr (/data/media/tv)", "running")
        try:
            sonarr.add_root_folder("/data/media/tv")
            _set_task("Add root folder to Sonarr (/data/media/tv)", "ok")
        except Exception as exc:
            _set_task("Add root folder to Sonarr (/data/media/tv)", "failed", str(exc))
            _abort()
            return

        _set_task("Enable hardlinks in Sonarr", "running")
        try:
            sonarr.enable_hardlinks()
            _set_task("Enable hardlinks in Sonarr", "ok")
        except Exception as exc:
            _set_task("Enable hardlinks in Sonarr", "failed", str(exc))
            _abort()
            return

        # ----------------------------------------------------------------
        # Step e: Radarr — download client, root folder, hardlinks
        # ----------------------------------------------------------------
        radarr = RadarrClient(radarr_url, api_keys["radarr"])

        _set_task("Add qBittorrent to Radarr", "running")
        try:
            radarr.add_qbittorrent(
                host="qbittorrent",
                port=qb_port,
                username="admin",
                password=shared_password,
                category="movies",
            )
            _set_task("Add qBittorrent to Radarr", "ok")
        except Exception as exc:
            _set_task("Add qBittorrent to Radarr", "failed", str(exc))
            _abort()
            return

        _set_task("Add root folder to Radarr (/data/media/movies)", "running")
        try:
            radarr.add_root_folder("/data/media/movies")
            _set_task("Add root folder to Radarr (/data/media/movies)", "ok")
        except Exception as exc:
            _set_task("Add root folder to Radarr (/data/media/movies)", "failed", str(exc))
            _abort()
            return

        _set_task("Enable hardlinks in Radarr", "running")
        try:
            radarr.enable_hardlinks()
            _set_task("Enable hardlinks in Radarr", "ok")
        except Exception as exc:
            _set_task("Enable hardlinks in Radarr", "failed", str(exc))
            _abort()
            return

        # ----------------------------------------------------------------
        # All done — persist state
        # ----------------------------------------------------------------
        with _lock:
            _status["phase"] = "complete"
            tasks_snapshot = list(_status["tasks"])

        state.set(
            "wiring",
            {
                "status": "complete",
                "api_keys": {
                    "sonarr": api_keys.get("sonarr", ""),
                    "radarr": api_keys.get("radarr", ""),
                    "prowlarr": api_keys.get("prowlarr", ""),
                },
                "qb_credentials": {"username": "admin", "password": shared_password},
                "tasks": tasks_snapshot,
            },
        )

    except Exception as exc:
        with _lock:
            _status["phase"] = "failed"
            _status["error"] = str(exc)


def _abort() -> None:
    """Mark remaining pending tasks as skipped and set phase to failed."""
    with _lock:
        for task in _status["tasks"]:
            if task["status"] == "pending":
                task["status"] = "skipped"
                task["message"] = "Skipped due to earlier failure"
        _status["phase"] = "failed"
