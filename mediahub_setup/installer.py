"""Install orchestration for the MediaHub wizard.

All install state is module-level (single-process, single-user tool).
A threading.Lock guards the background install thread so reloading the
page never spawns a second `docker compose up -d`.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import services

# ---------------------------------------------------------------------------
# Module-level install state
# ---------------------------------------------------------------------------

_lock = threading.Lock()


def _initial_services_state() -> dict[str, str]:
    return {k: "pending" for k in services.core_keys()}


_install_state: dict[str, Any] = {
    "status": "idle",  # idle | running | ready | error
    "log_lines": deque(maxlen=500),
    "services": _initial_services_state(),
    "started_at": None,
    "finished_at": None,
    "error": None,
    "compose_path": None,
    "env_path": None,
}

_install_thread: threading.Thread | None = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

INSTALL_DIR = Path.home() / "mediahub"
_COMPOSE_TEMPLATE = "docker-compose.yml.j2"
_TEMPLATES_DIR = Path(__file__).parent / "compose"


# ---------------------------------------------------------------------------
# File preparation
# ---------------------------------------------------------------------------


def prepare_install_dir() -> Path:
    """Create ~/mediahub/ if it does not exist; return the path."""
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    return INSTALL_DIR


def prepare_media_layout(drive_mount: str) -> None:
    """Create the expected folder tree under the media drive."""
    base = Path(drive_mount)
    for sub in (
        "torrents/movies",
        "torrents/tv",
        "media/movies",
        "media/tv",
    ):
        (base / sub).mkdir(parents=True, exist_ok=True)


def render_compose(install_dir: Path, settings: dict) -> Path:
    """Render docker-compose.yml.j2 into install_dir/docker-compose.yml.

    ``settings`` must have keys: tz, puid, pgid, ports (dict). Optional:
    ``enabled_services`` (list of service keys beyond the core stack).
    Returns the path to the written file.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
    )
    template = env.get_template(_COMPOSE_TEMPLATE)
    enabled = settings.get("enabled_services", [])
    rendered = template.render(
        tz=settings["tz"],
        puid=settings["puid"],
        pgid=settings["pgid"],
        ports=settings["ports"],
        enabled_services=enabled,
    )
    out = install_dir / "docker-compose.yml"
    install_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    return out


def render_env(install_dir: Path, drive: dict, settings: dict) -> Path:
    """Write ~/mediahub/.env consumed by docker compose.

    ``drive`` must have key: mount_path (str path to the media drive).
    ``settings`` must have keys: puid, pgid, tz.
    Returns the path to the written file.
    """
    lines = [
        f"PUID={settings['puid']}",
        f"PGID={settings['pgid']}",
        f"TZ={settings['tz']}",
        f"MEDIA_ROOT={drive['mount_path']}",
    ]
    out = install_dir / ".env"
    install_dir.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out


# ---------------------------------------------------------------------------
# Background install thread
# ---------------------------------------------------------------------------


def _log(line: str) -> None:
    _install_state["log_lines"].append(line)


def _poll_service(name: str, url: str, timeout_secs: int = 300) -> None:
    """Poll ``url`` until any HTTP response arrives or timeout."""
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        try:
            requests.get(url, timeout=3)
            with _lock:
                _install_state["services"][name] = "ready"
            _log(f"[health] {name} is ready at {url}")
            return
        except Exception:
            with _lock:
                _install_state["services"][name] = "starting"
            time.sleep(2)
    with _lock:
        _install_state["services"][name] = "timeout"
    _log(f"[health] {name} timed out waiting for {url}")


def _run_install(install_dir: Path, settings: dict) -> None:
    """Background thread: docker compose up -d then poll each service."""
    _log("[install] Starting docker compose up -d …")

    try:
        proc = subprocess.Popen(
            ["docker", "compose", "up", "-d"],
            cwd=str(install_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _log(line.rstrip())
        proc.wait()

        if proc.returncode != 0:
            with _lock:
                _install_state["status"] = "error"
                _install_state["error"] = f"docker compose up -d exited with code {proc.returncode}"
                _install_state["finished_at"] = datetime.now(tz=UTC).isoformat()
            _log(f"[install] ERROR: exit code {proc.returncode}")
            return
    except Exception as exc:
        with _lock:
            _install_state["status"] = "error"
            _install_state["error"] = str(exc)
            _install_state["finished_at"] = datetime.now(tz=UTC).isoformat()
        _log(f"[install] EXCEPTION: {exc}")
        return

    _log("[install] docker compose up -d finished — polling service health …")

    ports = settings.get("ports", {})
    enabled = settings.get("enabled_services", [])
    all_to_poll = services.core_keys() + [k for k in enabled if k != "recyclarr"]

    service_urls: dict[str, str] = {}
    for key in all_to_poll:
        svc = services.ALL.get(key)
        if not svc:
            continue
        port_key = svc.get("port_key") or ""
        if not port_key:
            continue
        port = ports.get(port_key, svc.get("default_port", 0))
        if not port:
            continue
        service_urls[key] = f"http://localhost:{port}"

    # Ensure each polled service has a state slot
    with _lock:
        for key in service_urls:
            _install_state["services"].setdefault(key, "pending")

    poll_threads = []
    for svc, url in service_urls.items():
        t = threading.Thread(target=_poll_service, args=(svc, url), daemon=True)
        t.start()
        poll_threads.append(t)

    for t in poll_threads:
        t.join()

    with _lock:
        _install_state["status"] = "ready"
        _install_state["finished_at"] = datetime.now(tz=UTC).isoformat()
    _log("[install] All services polled — install complete.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_install(install_dir: Path, drive: dict, settings: dict) -> bool:
    """Idempotent: spawns the background thread only if not already running.

    Returns True if a new install was started, False if one was already running.
    """
    global _install_thread

    with _lock:
        if _install_state["status"] in ("running",):
            return False
        # Reset transient state for a fresh run (allows retry after error)
        enabled = settings.get("enabled_services", [])
        all_services = services.core_keys() + [k for k in enabled if k != "recyclarr"]
        _install_state.update(
            {
                "status": "running",
                "log_lines": deque(maxlen=500),
                "services": {k: "pending" for k in all_services},
                "started_at": datetime.now(tz=UTC).isoformat(),
                "finished_at": None,
                "error": None,
                "compose_path": str(install_dir / "docker-compose.yml"),
                "env_path": str(install_dir / ".env"),
            }
        )

    _install_thread = threading.Thread(
        target=_run_install,
        args=(install_dir, settings),
        daemon=True,
    )
    _install_thread.start()
    return True


def install_status() -> dict:
    """Return a snapshot of the current install state for the status endpoint."""
    with _lock:
        log = list(_install_state["log_lines"])
        services = dict(_install_state["services"])
        status = _install_state["status"]
        started_at = _install_state["started_at"]
        finished_at = _install_state["finished_at"]
        error = _install_state["error"]
        compose_path = _install_state["compose_path"]
        env_path = _install_state["env_path"]

    # Compute overall progress %
    svc_states = list(services.values())
    total = len(svc_states)
    ready_count = svc_states.count("ready")
    timeout_count = svc_states.count("timeout")
    done_count = ready_count + timeout_count

    if status == "idle":
        progress = 0
    elif status == "running":
        # 50% for compose up, 50% for health checks
        progress = 50 + int((done_count / total) * 50) if total else 50
    elif status in ("ready", "error"):
        progress = 100
    else:
        progress = 0

    return {
        "status": status,
        "log_lines": log[-30:],  # last 30 for the partial
        "services": services,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
        "progress": progress,
        "compose_path": compose_path,
        "env_path": env_path,
    }
