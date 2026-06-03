"""Post-install health check for a running MediaHub deployment.

``mediahub-setup doctor`` answers "is this box healthy?" without a browser:
it probes the Docker daemon, reports the state of every ``mediahub-*``
container, and shows disk headroom on the install dir and the media library.
It's read-only (no container is started, stopped, or recreated) and returns a
process exit code so a cron/monitoring job can branch on it — the unattended
counterpart to the dashboard's status view, mirroring :mod:`headless`.

Exit codes:
    0  healthy — Docker up and every found container running
    1  unhealthy — Docker up but a container is stopped/restarting, or disk
       is critically low
    2  Docker unavailable (not installed, or the daemon isn't responding)
    3  nothing installed — Docker up but no ``mediahub-*`` containers exist
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import docker_ops, installer, preflight, roles

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_NO_DOCKER = 2
EXIT_NOT_INSTALLED = 3

# Disk headroom (GB) below which we flag the deployment unhealthy — a full
# media disk silently breaks imports and seeding.
_DISK_CRITICAL_GB = 5.0

_ICON = {"ok": "✔", "warn": "⚠", "fail": "✘"}


def _echo(message: str = "") -> None:
    print(message, flush=True)


def _classify_container(state: str) -> str:
    """Map a docker container state to ok/warn/fail."""
    state = (state or "").lower()
    if state == "running":
        return "ok"
    if state in ("restarting", "created", "paused"):
        return "warn"
    return "fail"  # exited, dead, removing, unknown


def diagnose(media_dir: str | Path | None = None, role: str | None = None) -> dict[str, Any]:
    """Build a structured health report (no printing, no side effects).

    Returns a dict with ``status`` (ok/unhealthy/no_docker/not_installed),
    ``containers`` (list of {name, state, status, health}), ``disks`` (list of
    {label, path, usage, health}) and a ``tailscale`` entry for server roles.
    Kept side-effect-free so tests and the CLI can share it.
    """
    report: dict[str, Any] = {
        "status": "ok",
        "docker_available": True,
        "containers": [],
        "disks": [],
        "tailscale": None,
    }

    if not docker_ops.docker_available():
        report["status"] = "no_docker"
        report["docker_available"] = False
        return report

    containers = docker_ops.list_containers()
    if not containers:
        report["status"] = "not_installed"
        return report

    worst = "ok"
    for c in containers:
        health = _classify_container(c.get("state", ""))
        if health == "fail":
            worst = "fail"
        elif health == "warn" and worst != "fail":
            worst = "warn"
        report["containers"].append(
            {
                "name": c.get("name", ""),
                "state": c.get("state", ""),
                "status": c.get("status", ""),
                "ports": c.get("ports", ""),
                "health": health,
            }
        )

    # Disk headroom: install dir (compose + configs) and, if known, the media
    # library. De-dupe by resolved filesystem mount to avoid double reporting.
    disk_targets: list[tuple[str, Path]] = [("install dir", installer.INSTALL_DIR)]
    if media_dir:
        disk_targets.append(("media library", Path(str(media_dir)).expanduser()))

    seen_paths: set[str] = set()
    for label, path in disk_targets:
        if not path.exists():
            continue
        key = str(path.resolve())
        if key in seen_paths:
            continue
        seen_paths.add(key)
        usage = docker_ops.disk_usage(path)
        free = usage.get("free_gb", 0.0)
        health = "fail" if free < _DISK_CRITICAL_GB else "ok"
        if health == "fail":
            worst = "fail"
        report["disks"].append(
            {"label": label, "path": str(path), "usage": usage, "health": health}
        )

    # Tailscale connectivity matters only where UIs bind to the tailnet.
    if role and roles.is_server(roles.normalize(role)):
        ip = preflight.tailscale_ip()
        report["tailscale"] = {"connected": bool(ip), "ip": ip}
        if not ip and worst != "fail":
            worst = "warn"

    report["status"] = {"ok": "ok", "warn": "unhealthy", "fail": "unhealthy"}[worst]
    return report


def run(media_dir: str | Path | None = None, role: str | None = None) -> int:
    """Print a health report and return a process exit code."""
    report = diagnose(media_dir=media_dir, role=role)
    _echo("MediaHub Setup — doctor")

    if report["status"] == "no_docker":
        _echo("  ✘ Docker is not available (not installed, or the daemon isn't responding).")
        _echo("    Start Docker / Docker Desktop and re-run.")
        return EXIT_NO_DOCKER

    if report["status"] == "not_installed":
        _echo("  ⚠ Docker is up, but no mediahub-* containers exist.")
        _echo("    Run `mediahub-setup` (or `install`) to set the stack up.")
        return EXIT_NOT_INSTALLED

    running = sum(1 for c in report["containers"] if c["health"] == "ok")
    total = len(report["containers"])
    _echo(f"  Containers ({running}/{total} running):")
    for c in report["containers"]:
        icon = _ICON.get(c["health"], "?")
        _echo(f"    {icon} {c['name']:<22} {c['status']}")

    if report["disks"]:
        _echo("")
        _echo("  Disk:")
        for d in report["disks"]:
            icon = _ICON.get(d["health"], "?")
            u = d["usage"]
            _echo(
                f"    {icon} {d['label']:<14} {u.get('free_gb', '?')} GB free "
                f"of {u.get('total_gb', '?')} GB ({u.get('percent_used', '?')}% used)"
            )

    ts = report["tailscale"]
    if ts is not None:
        _echo("")
        if ts["connected"]:
            _echo(f"  ✔ Tailscale connected ({ts['ip']})")
        else:
            _echo("  ⚠ Tailscale not connected — tailnet-bound UIs are unreachable remotely.")

    _echo("")
    if report["status"] == "ok":
        _echo("  ✅ Healthy.")
        return EXIT_OK
    _echo("  ✘ Problems found (see ✘/⚠ above).")
    return EXIT_UNHEALTHY
