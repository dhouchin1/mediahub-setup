"""System preflight checks.

Each check returns a CheckResult describing pass/warn/fail status,
a human-readable message, and (when applicable) a remediation hint
the UI can show the user.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["pass", "warn", "fail"]

# Ports the *arr stack needs locally.
REQUIRED_PORTS: tuple[tuple[int, str], ...] = (
    (7878, "Radarr"),
    (8989, "Sonarr"),
    (9696, "Prowlarr"),
    (8080, "qBittorrent Web UI"),
    (6881, "qBittorrent (BitTorrent)"),
)


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    fix: str | None = None
    details: list[str] = field(default_factory=list)


def _run(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def check_docker_installed() -> CheckResult:
    if shutil.which("docker") is None:
        return CheckResult(
            name="Docker installed",
            status="fail",
            message="`docker` not found in PATH",
            fix=(
                "Install OrbStack (recommended, free for personal use) "
                "from https://orbstack.dev/, or Docker Desktop from "
                "https://www.docker.com/products/docker-desktop/"
            ),
        )
    result = _run(["docker", "--version"])
    version = result.stdout.strip() if result and result.returncode == 0 else "unknown"
    return CheckResult(
        name="Docker installed",
        status="pass",
        message=version,
    )


def check_docker_daemon() -> CheckResult:
    result = _run(["docker", "ps"])
    if result is None:
        return CheckResult(
            name="Docker daemon running",
            status="fail",
            message="Couldn't run `docker ps`",
            fix="Make sure Docker / OrbStack is installed before running this.",
        )
    if result.returncode != 0:
        return CheckResult(
            name="Docker daemon running",
            status="fail",
            message="Daemon not reachable",
            fix=(
                "Open OrbStack (or Docker Desktop). Wait for it to finish "
                "starting, then re-run preflight."
            ),
            details=[line for line in result.stderr.splitlines() if line.strip()],
        )
    return CheckResult(
        name="Docker daemon running",
        status="pass",
        message="`docker ps` succeeded",
    )


def check_docker_compose() -> CheckResult:
    result = _run(["docker", "compose", "version"])
    if result is None or result.returncode != 0:
        return CheckResult(
            name="Compose plugin",
            status="fail",
            message="`docker compose` not available",
            fix=(
                "Modern Docker (and OrbStack) ship Compose v2 as a plugin. "
                "If you have an old standalone `docker-compose`, upgrade Docker."
            ),
        )
    return CheckResult(
        name="Compose plugin",
        status="pass",
        message=result.stdout.strip(),
    )


def _port_free(port: int) -> bool:
    """True if a process can bind 0.0.0.0:port right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def check_ports() -> CheckResult:
    busy = [(p, name) for p, name in REQUIRED_PORTS if not _port_free(p)]
    if not busy:
        return CheckResult(
            name="Required ports",
            status="pass",
            message="All five ports are free",
        )
    return CheckResult(
        name="Required ports",
        status="warn",
        message=f"{len(busy)} port(s) in use",
        fix=(
            "Stop whatever is using these ports, or override them in the "
            "Settings step (next screen)."
        ),
        details=[f"Port {p} ({name}) is in use" for p, name in busy],
    )


def check_disk_space(min_gb: int = 5) -> CheckResult:
    """Sanity-check the home dir has room for state + config dirs.
    The real media drive is checked separately in the Drive step."""
    free_bytes = shutil.disk_usage(str(_resolve_home())).free
    free_gb = free_bytes / 1_000_000_000
    if free_gb < min_gb:
        return CheckResult(
            name="Home directory space",
            status="warn",
            message=f"{free_gb:.1f} GB free (< {min_gb} GB)",
            fix="Free up some space on the boot drive before installing.",
        )
    return CheckResult(
        name="Home directory space",
        status="pass",
        message=f"{free_gb:.1f} GB free",
    )


def _resolve_home() -> str:
    from pathlib import Path

    return str(Path.home())


def run_all() -> list[CheckResult]:
    """Run every preflight check, in order."""
    return [
        check_docker_installed(),
        check_docker_daemon(),
        check_docker_compose(),
        check_ports(),
        check_disk_space(),
    ]


def overall_status(results: list[CheckResult]) -> Status:
    if any(r.status == "fail" for r in results):
        return "fail"
    if any(r.status == "warn" for r in results):
        return "warn"
    return "pass"
