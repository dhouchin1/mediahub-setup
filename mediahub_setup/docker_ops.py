"""Docker introspection + lifecycle operations for the dashboard.

All operations shell out to the `docker` CLI rather than using the Docker
SDK so we don't have to bundle libcurl / dockerpy and the runtime
requirement matches what users already have installed.

These functions are read-mostly; the only mutating helpers are
`restart_container`, `pull_and_recreate`, and `compose_update_all` —
each carefully scoped to operations the user explicitly requested from
the dashboard UI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INSTALL_DIR = Path.home() / "mediahub"

# ---------------------------------------------------------------------------
# Container introspection
# ---------------------------------------------------------------------------


def docker_available() -> bool:
    """Cheap probe — True if `docker` CLI is on PATH AND daemon responds."""
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def list_containers(name_prefix: str = "mediahub-") -> list[dict[str, Any]]:
    """Return basic info for every container whose name starts with *name_prefix*.

    Includes stopped containers (--all). Each dict has: name, image, state,
    status, created.
    """
    try:
        r = subprocess.run(
            [
                "docker",
                "ps",
                "--all",
                "--filter",
                f"name={name_prefix}",
                "--format",
                "{{json .}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.strip().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(
            {
                "name": row.get("Names", ""),
                "image": row.get("Image", ""),
                "state": (row.get("State") or "").lower(),  # "running" / "exited"
                "status": row.get("Status", ""),
                "created": row.get("CreatedAt", ""),
                "ports": row.get("Ports", ""),
            }
        )
    return out


def container_logs(container_name: str, tail: int = 30) -> str:
    """Return the last *tail* lines of the container log."""
    try:
        r = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return f"[error fetching logs: {exc}]"
    return (r.stdout + r.stderr).strip()


def restart_container(container_name: str) -> tuple[bool, str]:
    """Restart a single container. Returns (success, message)."""
    if not container_name.startswith("mediahub-"):
        return False, "Refusing to restart container outside mediahub-* namespace"
    try:
        r = subprocess.run(
            ["docker", "restart", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return False, f"docker restart failed: {exc}"
    if r.returncode != 0:
        return False, r.stderr.strip() or "non-zero exit"
    return True, r.stdout.strip() or "restarted"


# ---------------------------------------------------------------------------
# Live stats (docker stats --no-stream)
# ---------------------------------------------------------------------------


def docker_stats(name_prefix: str = "mediahub-") -> list[dict[str, Any]]:
    """Single-shot snapshot of CPU / mem usage for mediahub-* containers.

    Uses `docker stats --no-stream` so it returns quickly (~1s).
    """
    try:
        r = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.strip().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = row.get("Name", "") or row.get("Names", "")
        if not name.startswith(name_prefix):
            continue
        out.append(
            {
                "name": name,
                "cpu_percent": _parse_percent(row.get("CPUPerc", "0%")),
                "mem_percent": _parse_percent(row.get("MemPerc", "0%")),
                "mem_usage": row.get("MemUsage", ""),
                "net_io": row.get("NetIO", ""),
                "block_io": row.get("BlockIO", ""),
                "pids": row.get("PIDs", ""),
            }
        )
    return out


def _parse_percent(raw: str) -> float:
    try:
        return float(raw.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return 0.0


# ---------------------------------------------------------------------------
# Disk usage
# ---------------------------------------------------------------------------


def disk_usage(path: Path | str) -> dict[str, float]:
    """Return total / used / free GB for the filesystem holding *path*."""
    p = Path(path)
    if not p.exists():
        return {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "percent_used": 0.0}
    usage = shutil.disk_usage(p)
    total = usage.total / 1e9
    free = usage.free / 1e9
    used = (usage.total - usage.free) / 1e9
    pct = (used / total * 100) if total > 0 else 0
    return {
        "total_gb": round(total, 1),
        "used_gb": round(used, 1),
        "free_gb": round(free, 1),
        "percent_used": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# Compose lifecycle: pull + recreate (the "update everything" button)
# ---------------------------------------------------------------------------

_update_lock = threading.Lock()

_update_state: dict[str, Any] = {
    "status": "idle",  # idle | running | ready | error
    "log_lines": deque(maxlen=500),
    "started_at": None,
    "finished_at": None,
    "error": None,
}

_update_thread: threading.Thread | None = None


def update_status() -> dict[str, Any]:
    """Snapshot of the current update-all operation."""
    with _update_lock:
        return {
            "status": _update_state["status"],
            "log_lines": list(_update_state["log_lines"]),
            "started_at": _update_state["started_at"],
            "finished_at": _update_state["finished_at"],
            "error": _update_state["error"],
        }


def _log_update(line: str) -> None:
    _update_state["log_lines"].append(line)


def _run_compose_update(install_dir: Path) -> None:
    """Background thread: docker compose pull then up -d."""
    try:
        for cmd in (
            ["docker", "compose", "pull"],
            ["docker", "compose", "up", "-d"],
        ):
            _log_update(f"$ {' '.join(cmd)}")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(install_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:
                with _update_lock:
                    _update_state["status"] = "error"
                    _update_state["error"] = str(exc)
                    _update_state["finished_at"] = datetime.now(tz=UTC).isoformat()
                _log_update(f"[error] {exc}")
                return
            assert proc.stdout is not None
            for line in proc.stdout:
                _log_update(line.rstrip())
            proc.wait()
            if proc.returncode != 0:
                with _update_lock:
                    _update_state["status"] = "error"
                    _update_state["error"] = f"`{' '.join(cmd)}` exited with code {proc.returncode}"
                    _update_state["finished_at"] = datetime.now(tz=UTC).isoformat()
                _log_update(f"[error] exit code {proc.returncode}")
                return

        with _update_lock:
            _update_state["status"] = "ready"
            _update_state["finished_at"] = datetime.now(tz=UTC).isoformat()
        _log_update("[update] complete.")
    except Exception as exc:  # safety net
        with _update_lock:
            _update_state["status"] = "error"
            _update_state["error"] = str(exc)
            _update_state["finished_at"] = datetime.now(tz=UTC).isoformat()
        _log_update(f"[error] {exc}")


def compose_update_all(install_dir: Path | None = None) -> bool:
    """Idempotent: start the update thread if not already running."""
    global _update_thread
    install_dir = install_dir or INSTALL_DIR
    with _update_lock:
        if _update_state["status"] == "running":
            return False
        _update_state.update(
            {
                "status": "running",
                "log_lines": deque(maxlen=500),
                "started_at": datetime.now(tz=UTC).isoformat(),
                "finished_at": None,
                "error": None,
            }
        )
    _update_thread = threading.Thread(
        target=_run_compose_update,
        args=(install_dir,),
        daemon=True,
    )
    _update_thread.start()
    return True


# ---------------------------------------------------------------------------
# Compose lifecycle: down (teardown)
# ---------------------------------------------------------------------------


def compose_down(
    install_dir: Path | None = None, *, remove_volumes: bool = False
) -> tuple[bool, str]:
    """Run ``docker compose down`` in the install dir. Returns (ok, output).

    Synchronous (teardown is quick, unlike the long pull+recreate update).
    Without *remove_volumes* the named volumes — service configs and the
    qBittorrent/\\*arr databases — are preserved, so ``up`` brings the same
    deployment back. With *remove_volumes* those volumes are deleted too
    (``down --volumes``); the bind-mounted media library is never touched
    either way.
    """
    install_dir = install_dir or INSTALL_DIR
    compose_file = Path(install_dir) / "docker-compose.yml"
    if not compose_file.is_file():
        return False, f"No docker-compose.yml in {install_dir} — nothing to tear down."

    cmd = ["docker", "compose", "down"]
    if remove_volumes:
        cmd.append("--volumes")
    try:
        r = subprocess.run(
            cmd,
            cwd=str(install_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        return False, f"`{' '.join(cmd)}` failed: {exc}"
    output = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return False, output or f"`{' '.join(cmd)}` exited with code {r.returncode}"
    return True, output or "Stack stopped."
