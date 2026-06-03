"""Non-interactive (headless) install path.

Drives the exact same backend the web wizard uses — preflight, drive
resolution, settings, compose/.env render, ``docker compose up -d`` and the
wiring runner — but from a config file + CLI flags instead of a browser.

Designed for unattended VPS bring-up (e.g. cloud-init or a one-line
``curl … | bash -s -- install --role seedbox --config seedbox.yml``): it
streams progress to stdout, never blocks on input, and returns a process exit
code so a provisioning script can branch on success/failure.

The wizard and this module share one settings contract via
:mod:`mediahub_setup.settings_builder`, so a headless seedbox is configured
identically to one walked through the browser.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import drives, installer, preflight, roles, state, wiring_runner
from .settings_builder import SettingsError, build_settings

# Process exit codes (0 == success). Distinct codes let a provisioning script
# tell *which* phase failed.
EXIT_OK = 0
EXIT_PREFLIGHT = 2
EXIT_CONFIG = 3
EXIT_DRIVE = 4
EXIT_INSTALL = 5
EXIT_WIRING = 6

_STATUS_ICON = {"pass": "✔", "warn": "⚠", "fail": "✘"}


def _echo(message: str = "") -> None:
    print(message, flush=True)


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML or JSON config file into a plain dict.

    YAML is parsed for ``.yml``/``.yaml`` (and as the default), JSON for
    ``.json``. Raises ``FileNotFoundError`` / ``ValueError`` on a missing file
    or a non-mapping root.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Config file not found: {p}")
    text = p.read_text()
    if p.suffix.lower() == ".json":
        import json

        data = json.loads(text or "{}")
    else:
        import yaml

        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping, got {type(data).__name__}")
    return data


def _drive_state(info: drives.DriveInfo) -> dict[str, Any]:
    """Convert a DriveInfo into the dict shape the wizard stores under 'drive'."""
    return {
        "name": info.name,
        "mount_path": info.mount_path,
        "filesystem": info.filesystem,
        "total_bytes": info.total_bytes,
        "free_bytes": info.free_bytes,
        "total_gb": info.total_gb,
        "free_gb": info.free_gb,
        "writable": info.writable,
    }


def _resolve_drive(data_dir: str | None, cfg: dict[str, Any]) -> drives.DriveInfo | None:
    """Resolve and prepare the media data directory (creating it if needed)."""
    path = data_dir or cfg.get("data_dir") or (cfg.get("drive") or {}).get("data_dir")
    if not path:
        return None
    target = Path(str(path)).expanduser()
    target.mkdir(parents=True, exist_ok=True)  # unattended: create it if absent
    return drives.drive_from_path(str(target))


def _run_preflight(role: str, *, skip: bool, force: bool) -> bool:
    if skip:
        _echo("• Preflight: skipped (--skip-preflight)")
        return True
    _echo("• Preflight checks…")
    results = preflight.run_all(role)
    for r in results:
        icon = _STATUS_ICON.get(r.status, "?")
        _echo(f"    {icon} {r.name}: {r.message}")
        if r.status == "fail" and r.fix:
            _echo(f"        fix: {r.fix}")
    overall = preflight.overall_status(results)
    state.set("preflight", {"overall": overall})
    if overall == "fail" and not force:
        _echo("  Preflight FAILED — fix the issues above, or pass --force / --skip-preflight.")
        return False
    if overall == "fail":
        _echo("  Preflight failed but --force given; continuing.")
    return True


def _run_install(
    drive: dict[str, Any], settings: dict[str, Any], *, timeout: float, poll: float
) -> bool:
    """Render compose/.env, start docker compose, and poll until ready."""
    role = settings["role"]
    install_dir = installer.prepare_install_dir()
    installer.prepare_media_layout(drive["mount_path"], include_torrents=roles.installs_arr(role))
    compose_path = installer.render_compose(install_dir, settings)
    installer.render_env(install_dir, drive, settings)
    _echo(f"• Wrote {compose_path}")
    _echo("• docker compose up -d …")

    installer.start_install(install_dir, drive, settings)

    deadline = time.monotonic() + timeout
    seen: dict[str, str] = {}
    while time.monotonic() < deadline:
        status = installer.install_status()
        for name, svc_state in status["services"].items():
            if seen.get(name) != svc_state:
                seen[name] = svc_state
                _echo(f"    {name}: {svc_state}")
        if status["status"] == "ready":
            state.set(
                "install",
                {
                    "compose_path": status["compose_path"],
                    "env_path": status["env_path"],
                    "status": "ready",
                    "services": status["services"],
                },
            )
            timed_out = [n for n, s in status["services"].items() if s == "timeout"]
            if timed_out:
                _echo(f"  ⚠ services slow to respond: {', '.join(timed_out)} (continuing)")
            return True
        if status["status"] == "error":
            _echo(f"  Install error: {status.get('error')}")
            for line in status.get("log_lines", [])[-15:]:
                _echo(f"    | {line}")
            return False
        time.sleep(poll)

    _echo(f"  Install timed out after {timeout:.0f}s.")
    return False


def _run_wiring(role: str, settings: dict[str, Any], *, timeout: float, poll: float) -> bool:
    enabled = settings.get("enabled_services") or []
    planned = wiring_runner.planned_task_names(enabled, role)
    if not planned:
        _echo("• Wiring: nothing to wire for this role.")
        return True

    _echo(f"• Wiring {len(planned)} tasks…")
    wiring_runner.start_wiring()

    deadline = time.monotonic() + timeout
    reported: set[str] = set()
    while time.monotonic() < deadline:
        snap = wiring_runner.wiring_status()
        for task in snap["tasks"]:
            if task["status"] in ("ok", "failed", "skipped") and task["name"] not in reported:
                reported.add(task["name"])
                icon = {"ok": "✔", "failed": "✘", "skipped": "–"}.get(task["status"], "?")
                detail = f" — {task['message']}" if task.get("message") else ""
                _echo(f"    {icon} {task['name']}{detail}")
        if snap["phase"] == "complete":
            return True
        if snap["phase"] == "failed":
            _echo("  Wiring failed (see the ✘ task above).")
            return False
        time.sleep(poll)

    _echo(f"  Wiring timed out after {timeout:.0f}s.")
    return False


def _print_plan(role: str, drive: dict[str, Any], settings: dict[str, Any]) -> None:
    """Print the resolved install plan for ``--dry-run`` (nothing is started)."""
    from . import services as _services

    ports = settings.get("ports") or {}
    enabled = settings.get("enabled_services") or []

    _echo("")
    _echo("─" * 60)
    _echo(f"DRY RUN — plan for a '{role}' install (nothing was started):")
    _echo("")
    free_gb = drive.get("free_gb")
    free_str = f"{free_gb:.1f} GB" if isinstance(free_gb, (int, float)) else "?"
    _echo(f"  Data directory : {drive['mount_path']} ({drive.get('filesystem', '?')})")
    _echo(f"  Free space     : {free_str}")
    _echo("")

    core = ["sonarr", "radarr", "prowlarr", "qbittorrent"] if roles.installs_arr(role) else []
    optional = [k for k in enabled if k not in {"recyclarr", "gluetun"}]
    _echo("  Services (with published ports):")
    for key in dict.fromkeys(core + optional):  # de-dupe, keep order
        svc = _services.ALL.get(key)
        if not svc:
            continue
        port = ports.get(svc.get("port_key") or "")
        port_str = f":{port}" if port else " (no published port)"
        _echo(f"    • {svc.get('name', key):<14}{port_str}")
    # Infra-only toggles that have no web UI of their own.
    for key in ("recyclarr", "gluetun"):
        if key in enabled:
            _echo(f"    • {key:<14} (background)")

    planned = wiring_runner.planned_task_names(enabled, role)
    _echo("")
    if planned:
        _echo(f"  Wiring tasks that would run ({len(planned)}):")
        for name in planned:
            _echo(f"    – {name}")
    else:
        _echo("  Wiring tasks that would run: none for this role.")
    _echo("")
    _echo("  Config and preflight are valid. Re-run without --dry-run to install.")
    _echo("─" * 60)


def _print_summary(role: str, settings: dict[str, Any]) -> None:
    wiring = state.get("wiring") or {}
    ports = settings.get("ports") or {}
    tnet_ip = preflight.tailscale_ip() if roles.is_server(role) else None
    host = tnet_ip or "localhost"

    _echo("")
    _echo("─" * 60)
    _echo(f"✅ MediaHub '{role}' install complete.")
    _echo("")

    if roles.is_server(role):
        where = f"the tailnet ({host})" if tnet_ip else "an SSH tunnel (UIs bind to loopback)"
        _echo(f"  Web UIs are reachable over {where}:")

    core_shown = ["sonarr", "radarr", "prowlarr", "qbittorrent"] if roles.installs_arr(role) else []
    optional_shown = [
        k for k in (settings.get("enabled_services") or []) if k not in {"recyclarr", "gluetun"}
    ]
    shown = core_shown + optional_shown
    from . import services as _services

    for key in dict.fromkeys(shown):  # de-dupe, keep order
        svc = _services.ALL.get(key)
        if not svc:
            continue
        port_key = svc.get("port_key") or ""
        port = ports.get(port_key)
        if port:
            _echo(f"    • {svc.get('name', key):<14} http://{host}:{port}")

    creds = wiring.get("qb_credentials") or {}
    if creds:
        user = creds.get("username", "admin")
        pw = creds.get("password", "")
        _echo("")
        _echo(f"  qBittorrent / *arr login:  {user} / {pw}")

    st = wiring.get("syncthing") or {}
    if st.get("device_id"):
        _echo("")
        _echo("  Syncthing:")
        _echo(f"    folder    : {st.get('folder_id')} ({st.get('folder_type')})")
        _echo(f"    THIS node : {st['device_id']}")
        remote = (settings.get("syncthing") or {}).get("remote_device_id")
        if remote:
            _echo(f"    paired to : {remote}")
        else:
            _echo("    Paste THIS device ID into the peer (the Mac receiver) to finish pairing.")
    _echo("─" * 60)


def run(
    *,
    role: str,
    config_path: str | None = None,
    data_dir: str | None = None,
    skip_preflight: bool = False,
    force: bool = False,
    assume_yes: bool = False,  # reserved: headless never prompts, kept for CLI symmetry
    dry_run: bool = False,
    install_timeout: float = 900.0,
    wiring_timeout: float = 1200.0,
    poll_interval: float = 2.0,
) -> int:
    """Run the full unattended install pipeline. Returns a process exit code.

    With ``dry_run=True`` the pipeline stops after validating the config,
    running preflight, resolving the data directory and building settings: it
    prints the resolved plan and returns ``EXIT_OK`` without rendering compose,
    starting containers or wiring. Useful as a cloud-init sanity check.
    """
    role = roles.normalize(role)
    mode = "dry run" if dry_run else "install"
    _echo(f"MediaHub Setup — headless {mode} (role: {role})")

    try:
        cfg = load_config(config_path) if config_path else {}
    except (FileNotFoundError, ValueError) as exc:
        _echo(f"✘ Config error: {exc}")
        return EXIT_CONFIG

    state.set("role", role)

    # --- drive -------------------------------------------------------------
    drive_info = _resolve_drive(data_dir, cfg)
    if drive_info is None:
        _echo("✘ No data directory. Pass --data-dir or set 'data_dir' in the config.")
        return EXIT_DRIVE
    if not drive_info.writable:
        _echo(f"✘ Data directory is not writable: {drive_info.mount_path}")
        return EXIT_DRIVE
    drive = _drive_state(drive_info)
    state.set("drive", drive)
    _echo(f"• Data directory: {drive['mount_path']} ({drive_info.filesystem})")

    # --- preflight ---------------------------------------------------------
    if not _run_preflight(role, skip=skip_preflight, force=force):
        return EXIT_PREFLIGHT

    # --- settings ----------------------------------------------------------
    try:
        settings = build_settings(role, cfg)
    except SettingsError as exc:
        _echo("✘ Invalid settings:")
        for field, message in exc.errors.items():
            _echo(f"    - {field}: {message}")
        return EXIT_CONFIG
    state.set("settings", settings)
    summary_services = (["(core *arr)"] if roles.installs_arr(role) else []) + list(
        settings["enabled_services"]
    )
    _echo(f"• Services: {', '.join(summary_services)}")

    # --- dry run: stop here with the validated plan ------------------------
    if dry_run:
        _print_plan(role, drive, settings)
        return EXIT_OK

    # --- install -----------------------------------------------------------
    if not _run_install(drive, settings, timeout=install_timeout, poll=poll_interval):
        return EXIT_INSTALL

    # --- wiring ------------------------------------------------------------
    if not _run_wiring(role, settings, timeout=wiring_timeout, poll=poll_interval):
        return EXIT_WIRING

    _print_summary(role, settings)
    return EXIT_OK
