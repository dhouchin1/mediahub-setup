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

from . import platform_detect, roles

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
        if platform_detect.is_macos():
            fix = (
                "Install OrbStack (recommended, free for personal use) "
                "from https://orbstack.dev/, or Docker Desktop from "
                "https://www.docker.com/products/docker-desktop/"
            )
        else:
            fix = (
                "Install Docker Engine — https://docs.docker.com/engine/install/ "
                "— then add your user to the `docker` group "
                "(`sudo usermod -aG docker $USER` and re-login) so this wizard "
                "can talk to the daemon."
            )
        return CheckResult(
            name="Docker installed",
            status="fail",
            message="`docker` not found in PATH",
            fix=fix,
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
    """True if a process can bind 0.0.0.0:port right now.

    Deliberately NO SO_REUSEADDR: on macOS/BSD it lets the wildcard bind
    succeed even while another process holds 127.0.0.1:<port> (e.g. a native
    Sonarr or Homebrew qBittorrent bound to loopback), which reported the
    port as free and let docker compose fail later with address-in-use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
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


def check_file_sharing() -> CheckResult:
    """Verify Docker/OrbStack passes ``/Volumes`` through to containers.

    The TRaSH single-mount convention requires that the container can see
    the host's external drive at the same path the host sees it. Both
    OrbStack and Docker Desktop share ``/Volumes/*`` by default on macOS,
    but a user who explicitly removed it from the shared list (or who is
    running a custom Docker config) needs to fix that before install.

    Strategy: mount ``/Volumes`` into a tiny ``alpine`` container and list
    it. If a host-visible ``/Volumes/*`` entry appears inside the
    container, the share is working. We use ``alpine`` because it's tiny
    (~3 MB), commonly cached on developer machines, and harmless to pull
    if missing.

    Returns ``pass`` (working), ``warn`` (not working — surfaces fix), or
    ``warn`` (couldn't verify — e.g. docker hasn't booted yet).

    On Linux there is no ``/Volumes`` indirection — Docker bind-mounts host
    paths natively — so this check is a no-op ``pass`` there.
    """
    import os
    from pathlib import Path

    if not platform_detect.is_macos():
        return CheckResult(
            name="Container file sharing",
            status="pass",
            message="Bind mounts are native on this platform",
        )

    # What does the host see at /Volumes? Filter out hidden dotfiles.
    try:
        host_entries = sorted(
            e for e in os.listdir("/Volumes") if not e.startswith(".") and e != "Macintosh HD"
        )
    except OSError:
        return CheckResult(
            name="Container file sharing",
            status="warn",
            message="/Volumes not readable from this account",
            fix="This is unusual on macOS — check Finder can see /Volumes.",
        )

    if not host_entries:
        # Nothing to verify against — just confirm /Volumes itself is mountable
        host_entries_for_check: list[str] = []
    else:
        host_entries_for_check = host_entries

    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "missing",
            "-v",
            "/Volumes:/check:ro",
            "alpine:latest",
            "ls",
            "/check",
        ],
        timeout=20.0,
    )
    if result is None or result.returncode != 0:
        # Couldn't even run the probe — surface a warn so the user knows
        # we didn't verify, with a hint at the most common cause.
        return CheckResult(
            name="Container file sharing",
            status="warn",
            message="Couldn't verify /Volumes sharing",
            fix=(
                "If your stack later complains about missing /data, open "
                "OrbStack → Settings → File Sharing (or Docker Desktop → "
                "Settings → Resources → File Sharing) and confirm /Volumes "
                "is in the shared list."
            ),
            details=[
                (result.stderr.strip()[:200] if result and result.stderr else "no docker output")
            ],
        )

    container_entries = {ln.strip() for ln in result.stdout.splitlines() if ln.strip()}

    missing = [e for e in host_entries_for_check if e not in container_entries]
    if missing:
        # Container can mount /Volumes but the user's drives aren't visible.
        # Almost always: the share is restricted to a subset of paths.
        return CheckResult(
            name="Container file sharing",
            status="warn",
            message=f"{len(missing)} drive(s) not visible to containers",
            fix=(
                "Open OrbStack → Settings → File Sharing (or Docker Desktop → "
                "Settings → Resources → File Sharing) and confirm /Volumes "
                "(or the parent of your media drive) is in the shared list."
            ),
            details=[f"/Volumes/{name}" for name in missing[:5]],
        )

    # Determine engine name for the success message
    engine = "Docker"
    if Path("/Applications/OrbStack.app").exists() or shutil.which("orb"):
        engine = "OrbStack"
    elif Path("/Applications/Docker.app").exists():
        engine = "Docker Desktop"

    visible = len(host_entries) if host_entries else 0
    if visible:
        msg = f"{engine} sees {visible} drive(s) under /Volumes"
    else:
        msg = f"{engine} can mount /Volumes (no external drives attached)"
    return CheckResult(
        name="Container file sharing",
        status="pass",
        message=msg,
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


def tailscale_ip() -> str | None:
    """Best-effort: this machine's Tailscale IPv4 address, or None."""
    if shutil.which("tailscale") is None:
        return None
    result = _run(["tailscale", "ip", "-4"])
    if result and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()[0].strip() or None
    return None


def check_tailscale() -> CheckResult:
    """Advise (never fail) on Tailscale for private remote access.

    On a public VPS the service web UIs must not be exposed unauthenticated.
    The recommended path is Tailscale: bind the UIs privately and reach them
    over the tailnet. We only detect and advise — never run ``tailscale up``.
    """
    name = "Tailscale (private access)"
    if shutil.which("tailscale") is None:
        return CheckResult(
            name=name,
            status="warn",
            message="Tailscale not installed",
            fix=(
                "Install Tailscale (https://tailscale.com/download) and run "
                "`tailscale up`, then reach your services over the tailnet "
                "instead of exposing them on the public internet."
            ),
        )
    result = _run(["tailscale", "status"])
    out = (result.stdout if result else "") or ""
    if result is None or result.returncode != 0 or "Logged out" in out or "stopped" in out:
        return CheckResult(
            name=name,
            status="warn",
            message="Tailscale installed but not connected",
            fix="Run `tailscale up` to join your tailnet, then access services privately.",
        )
    ip = tailscale_ip()
    return CheckResult(
        name=name,
        status="pass",
        message=f"Connected — tailnet IP {ip}" if ip else "Connected",
    )


def run_all(role: str | None = None) -> list[CheckResult]:
    """Run every preflight check, in order.

    On a seedbox (public VPS) an informational Tailscale check is appended so
    the user is nudged toward private access before exposing anything.
    """
    if role is None:
        role = roles.current()
    checks = [
        check_docker_installed(),
        check_docker_daemon(),
        check_docker_compose(),
        check_ports(),
        check_file_sharing(),
        check_disk_space(),
    ]
    if roles.is_server(role):
        checks.append(check_tailscale())
    return checks


def overall_status(results: list[CheckResult]) -> Status:
    if any(r.status == "fail" for r in results):
        return "fail"
    if any(r.status == "warn" for r in results):
        return "warn"
    return "pass"
