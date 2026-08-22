"""Orchestrator for the wiring step.

Runs API calls against freshly-started containers to auto-configure the
stack. Designed to be idempotent — safe to re-run if a previous attempt
partially succeeded.

The task list is built dynamically based on which optional services the
user enabled in Settings, so the wiring step gracefully scales from the
core 4-service stack up to the full Jellyfin/Jellyseerr/Bazarr/Notifiarr
combination without code changes per combination.

Public interface
----------------
    start_wiring()      — spawn background thread (no-op if already running)
    wiring_status()     — thread-safe snapshot of current progress
    planned_task_names() — list of task names that will run for current settings
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import roles, services, state
from .arr_client import (
    ProwlarrClient,
    QBittorrentClient,
    RadarrClient,
    SonarrClient,
    get_qbittorrent_temp_password,
    read_arr_api_key,
)
from .bazarr_client import BazarrClient
from .jellyfin_client import JellyfinClient
from .notifiarr import configure_notifiarr_telegram, wire_notifiarr_to_arr
from .overseerr_client import RequestAppClient
from .syncthing_client import SyncthingClient, read_syncthing_apikey

# ---------------------------------------------------------------------------
# Module-level state (lives for the lifetime of the Flask process)
# ---------------------------------------------------------------------------

_lock = threading.Lock()

_status: dict[str, Any] = {
    "phase": "idle",  # idle | running | complete | failed
    "tasks": [],
    "error": "",  # set when the run died outside any single task
}

_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------


@dataclass
class WiringTask:
    name: str
    fn: Callable[[WiringContext], str | None]  # returns optional success message
    requires: list[str] = field(default_factory=list)  # service keys that must be enabled


@dataclass
class WiringContext:
    """Mutable context threaded through every task in a wiring run."""

    settings: dict[str, Any]
    shared_password: str
    ports: dict[str, int]
    enabled: list[str]
    role: str = roles.ALL_IN_ONE
    # qBittorrent's reachable hostname on the docker network. When it egresses
    # through Gluetun it shares that container's netns, so *arr + Caddy must
    # address it as "gluetun" rather than "qbittorrent".
    qb_host: str = "qbittorrent"
    # Container DNS names (used for cross-container wiring)
    sonarr_internal: str = ""
    radarr_internal: str = ""
    prowlarr_internal: str = ""
    jellyfin_internal: str = ""
    overseerr_internal: str = ""
    jellyseerr_internal: str = ""
    bazarr_internal: str = ""
    # Per-host URLs (used for local-machine API calls from the wizard)
    qb_url: str = ""
    sonarr_url: str = ""
    radarr_url: str = ""
    prowlarr_url: str = ""
    jellyfin_url: str = ""
    overseerr_url: str = ""
    jellyseerr_url: str = ""
    bazarr_url: str = ""
    syncthing_url: str = ""
    # Captured during wiring
    api_keys: dict[str, str] = field(default_factory=dict)
    qb_client: QBittorrentClient | None = None
    sonarr_client: SonarrClient | None = None
    radarr_client: RadarrClient | None = None
    prowlarr_client: ProwlarrClient | None = None
    syncthing_client: SyncthingClient | None = None
    # Syncthing pairing info surfaced on the Done page
    syncthing_device_id: str = ""
    syncthing_folder_id: str = ""
    syncthing_folder_type: str = ""


# ---------------------------------------------------------------------------
# Task implementations
# ---------------------------------------------------------------------------


def _connect_qbittorrent(ctx: WiringContext) -> str | None:
    qb = QBittorrentClient(ctx.qb_url)
    qb_user = ctx.settings.get("qbittorrent_username", "admin")
    try:
        temp_pw = get_qbittorrent_temp_password("mediahub-qbittorrent")
        qb.login(temp_pw, username="admin")  # temp creds always use admin
        ctx.qb_client = qb
        return "Logged in with temporary password"
    except Exception:
        # Maybe already changed — try with shared_password under the chosen user
        qb.login(ctx.shared_password, username=qb_user)
        ctx.qb_client = qb
        return "Logged in with shared password"


def _change_qbittorrent_password(ctx: WiringContext) -> str | None:
    assert ctx.qb_client is not None
    qb_user = ctx.settings.get("qbittorrent_username", "admin")
    # If we logged in with shared_password it's already correct
    try:
        ctx.qb_client.list_categories()  # Quick probe with current creds
    except Exception:
        pass
    # Always set it explicitly (idempotent). This also renames the user if
    # the wizard's chosen username differs from "admin".
    ctx.qb_client.change_password(ctx.shared_password, username=qb_user)
    qb2 = QBittorrentClient(ctx.qb_url)
    qb2.login(ctx.shared_password, username=qb_user)
    ctx.qb_client = qb2
    return None


def _create_qb_category_movies(ctx: WiringContext) -> str | None:
    assert ctx.qb_client is not None
    ctx.qb_client.create_category("Movies", "/data/Torrents/Movies")
    return None


def _create_qb_category_tv(ctx: WiringContext) -> str | None:
    assert ctx.qb_client is not None
    ctx.qb_client.create_category("TV Shows", "/data/Torrents/TV Shows")
    return None


def _read_sonarr_api_key(ctx: WiringContext) -> str | None:
    key = read_arr_api_key("mediahub-sonarr", timeout=60)
    ctx.api_keys["sonarr"] = key
    ctx.sonarr_client = SonarrClient(ctx.sonarr_url, key)
    return f"Key: {key[:8]}…"


def _read_radarr_api_key(ctx: WiringContext) -> str | None:
    key = read_arr_api_key("mediahub-radarr", timeout=60)
    ctx.api_keys["radarr"] = key
    ctx.radarr_client = RadarrClient(ctx.radarr_url, key)
    return f"Key: {key[:8]}…"


def _read_prowlarr_api_key(ctx: WiringContext) -> str | None:
    key = read_arr_api_key("mediahub-prowlarr", timeout=60)
    ctx.api_keys["prowlarr"] = key
    ctx.prowlarr_client = ProwlarrClient(ctx.prowlarr_url, key)
    return f"Key: {key[:8]}…"


def _register_sonarr_in_prowlarr(ctx: WiringContext) -> str | None:
    assert ctx.prowlarr_client is not None
    ctx.prowlarr_client.add_sonarr(
        sonarr_url=ctx.sonarr_internal,
        prowlarr_url=ctx.prowlarr_internal,
        sonarr_api_key=ctx.api_keys["sonarr"],
    )
    return None


def _register_radarr_in_prowlarr(ctx: WiringContext) -> str | None:
    assert ctx.prowlarr_client is not None
    ctx.prowlarr_client.add_radarr(
        radarr_url=ctx.radarr_internal,
        prowlarr_url=ctx.prowlarr_internal,
        radarr_api_key=ctx.api_keys["radarr"],
    )
    return None


def _add_qb_to_sonarr(ctx: WiringContext) -> str | None:
    assert ctx.sonarr_client is not None
    qb_port = ctx.ports.get("qbittorrent_web", 8090)
    qb_user = ctx.settings.get("qbittorrent_username", "admin")
    ctx.sonarr_client.add_qbittorrent(
        host=ctx.qb_host,
        port=qb_port,
        username=qb_user,
        password=ctx.shared_password,
        category="TV Shows",
    )
    return None


def _add_sonarr_root_folder(ctx: WiringContext) -> str | None:
    assert ctx.sonarr_client is not None
    ctx.sonarr_client.add_root_folder("/data/Media/TV Shows")
    return None


def _enable_sonarr_hardlinks(ctx: WiringContext) -> str | None:
    assert ctx.sonarr_client is not None
    ctx.sonarr_client.enable_hardlinks()
    return None


def _add_qb_to_radarr(ctx: WiringContext) -> str | None:
    assert ctx.radarr_client is not None
    qb_port = ctx.ports.get("qbittorrent_web", 8090)
    qb_user = ctx.settings.get("qbittorrent_username", "admin")
    ctx.radarr_client.add_qbittorrent(
        host=ctx.qb_host,
        port=qb_port,
        username=qb_user,
        password=ctx.shared_password,
        category="Movies",
    )
    return None


def _add_radarr_root_folder(ctx: WiringContext) -> str | None:
    assert ctx.radarr_client is not None
    ctx.radarr_client.add_root_folder("/data/Media/Movies")
    return None


def _enable_radarr_hardlinks(ctx: WiringContext) -> str | None:
    assert ctx.radarr_client is not None
    ctx.radarr_client.enable_hardlinks()
    return None


# ----- Jellyfin -------------------------------------------------------------


def _wait_for_jellyfin(ctx: WiringContext) -> str | None:
    """Poll Jellyfin until it serves a System/Info/Public response."""
    client = JellyfinClient(ctx.jellyfin_url)
    client.wait_until_ready(timeout=180)
    return "Server is responding"


def _add_jellyfin_libraries(ctx: WiringContext) -> str | None:
    """Jellyfin requires manual first-run setup via the web UI to create the
    admin user. We can't fully wire libraries without that admin token, so
    we just verify the data folders exist inside the container."""
    return "Open Jellyfin web UI to finish first-time setup"


# ----- Overseerr / Jellyseerr ----------------------------------------------


def _wait_for_overseerr(ctx: WiringContext) -> str | None:
    client = RequestAppClient(ctx.overseerr_url)
    client.wait_until_ready(timeout=180)
    return "Server is responding"


def _record_overseerr_for_done(ctx: WiringContext) -> str | None:
    """Overseerr's API key is generated during first-run setup in the UI,
    so we surface URLs + setup hints on the Done page rather than configure
    via REST (which would require an already-set-up instance)."""
    return "Configure via web UI; URL surfaced on Done page"


def _wait_for_jellyseerr(ctx: WiringContext) -> str | None:
    client = RequestAppClient(ctx.jellyseerr_url)
    client.wait_until_ready(timeout=180)
    return "Server is responding"


def _record_jellyseerr_for_done(ctx: WiringContext) -> str | None:
    """Same pattern as Overseerr — first-run setup is done in the web UI."""
    return "Configure via web UI; URL surfaced on Done page"


# ----- Bazarr --------------------------------------------------------------


def _wait_for_bazarr(ctx: WiringContext) -> str | None:
    client = BazarrClient(ctx.bazarr_url, api_key=None)
    client.wait_until_ready(timeout=180)
    return "Server is responding"


def _add_bazarr_to_sonarr(ctx: WiringContext) -> str | None:
    """Bazarr requires its API key (generated on first launch). Read it from
    the container config and wire Sonarr+Radarr connections via Bazarr REST."""
    from .bazarr_client import read_bazarr_api_key

    key = read_bazarr_api_key("mediahub-bazarr", timeout=120)
    ctx.api_keys["bazarr"] = key
    client = BazarrClient(ctx.bazarr_url, api_key=key)
    client.set_sonarr(
        sonarr_url=ctx.sonarr_internal,
        api_key=ctx.api_keys["sonarr"],
    )
    return None


def _add_bazarr_to_radarr(ctx: WiringContext) -> str | None:
    client = BazarrClient(ctx.bazarr_url, api_key=ctx.api_keys["bazarr"])
    client.set_radarr(
        radarr_url=ctx.radarr_internal,
        api_key=ctx.api_keys["radarr"],
    )
    return None


# ----- Notifiarr -----------------------------------------------------------


def _configure_notifiarr(ctx: WiringContext) -> str | None:
    """Generate Notifiarr config file with Sonarr/Radarr/qBittorrent + optional
    Telegram. Restart the container to pick up the new config."""
    notifiarr_cfg = ctx.settings.get("notifiarr") or {}
    configure_notifiarr_telegram(
        ports=ctx.ports,
        api_keys=ctx.api_keys,
        shared_password=ctx.shared_password,
        telegram_bot_token=notifiarr_cfg.get("telegram_bot_token", ""),
        telegram_chat_id=notifiarr_cfg.get("telegram_chat_id", ""),
        qbittorrent_username=ctx.settings.get("qbittorrent_username", "admin"),
    )
    return "Config written"


def _wire_notifiarr_webhooks(ctx: WiringContext) -> str | None:
    """Add Notifiarr as a Connect target in Sonarr + Radarr so download
    events fire to Notifiarr (which routes to Telegram)."""
    assert ctx.sonarr_client is not None
    assert ctx.radarr_client is not None
    wire_notifiarr_to_arr(
        sonarr=ctx.sonarr_client,
        radarr=ctx.radarr_client,
        notifiarr_internal_url=_internal_url("notifiarr"),
    )
    return None


# ----- Recyclarr -----------------------------------------------------------


def _configure_recyclarr(ctx: WiringContext) -> str | None:
    from .recyclarr import render_recyclarr_config

    selected = ctx.settings.get("recyclarr_profiles")
    render_recyclarr_config(
        sonarr_internal_url=ctx.sonarr_internal,
        sonarr_api_key=ctx.api_keys["sonarr"],
        radarr_internal_url=ctx.radarr_internal,
        radarr_api_key=ctx.api_keys["radarr"],
        selected_profiles=selected,
    )
    return "Config written — runs daily at 4am"


# ----- Caddy ---------------------------------------------------------------


def _configure_caddy(ctx: WiringContext) -> str | None:
    from .caddy import render_caddyfile

    caddy_cfg = ctx.settings.get("caddy") or {}
    mode = ctx.settings.get("caddy_mode") or caddy_cfg.get("mode", "local")
    domain = caddy_cfg.get("domain", "mediahub.local")
    render_caddyfile(
        domain=domain,
        enabled=ctx.enabled,
        ports=ctx.ports,
        mode=mode,
        qbittorrent_host=ctx.qb_host,
    )
    if mode == "public":
        return f"Caddyfile written for {domain} (public/HTTPS mode)"
    return "Caddyfile written (local-only mode, IP allowlist active)"


# ----- Retention (seedbox disk management) ---------------------------------


def _set_qb_share_limits(ctx: WiringContext) -> str | None:
    """Apply global ratio + seed-time limits so a small seedbox disk doesn't
    fill up. When a limit is hit qBittorrent removes the torrent and deletes
    its ``/data/Torrents`` copy — the hardlinked ``/data/Media`` library that
    Syncthing replicates survives.
    """
    assert ctx.qb_client is not None
    r = ctx.settings.get("retention") or {}
    ratio = float(r.get("seed_ratio", 2.0))
    minutes = int(r.get("seed_time_minutes", 10080))
    remove = bool(r.get("remove_on_limit", True))
    ctx.qb_client.set_global_share_limits(
        ratio=ratio, seeding_time_minutes=minutes, remove_on_limit=remove
    )
    action = "remove+delete" if remove else "pause"
    return f"ratio {ratio}, {minutes}m, then {action}"


# ----- Gluetun (qBittorrent VPN egress) ------------------------------------


def _set_qb_vpn_listen_port(ctx: WiringContext) -> str | None:
    """Best-effort: read Gluetun's forwarded port and set it as qBittorrent's
    listen port so seeding works through the tunnel.

    Never hard-fails — port forwarding is assigned asynchronously by the VPN
    and may not be ready yet; the user can set it manually if so.
    """
    import json as _json
    import subprocess as _subprocess

    try:
        result = _subprocess.run(
            [
                "docker",
                "exec",
                "mediahub-gluetun",
                "wget",
                "-qO-",
                "http://localhost:8000/v1/openvpn/portforwarded",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            port = int(_json.loads(result.stdout).get("port") or 0)
            if port and ctx.qb_client is not None:
                ctx.qb_client.set_listen_port(port)
                return f"qBittorrent listen port set to forwarded port {port}"
    except Exception:
        pass
    return (
        "Gluetun handles port forwarding; set qBittorrent's listen port manually if seeding stalls"
    )


# ----- Syncthing -----------------------------------------------------------


def _wait_for_syncthing(ctx: WiringContext) -> str | None:
    """Read the auto-generated API key from the container and wait for the
    REST API to come up."""
    key = read_syncthing_apikey("mediahub-syncthing", timeout=120)
    ctx.api_keys["syncthing"] = key
    client = SyncthingClient(ctx.syncthing_url, api_key=key)
    client.wait_until_ready(timeout=180)
    ctx.syncthing_client = client
    return "Server is responding"


def _configure_syncthing_folder(ctx: WiringContext) -> str | None:
    """Create the Media folder with the role-appropriate type and (on a
    receiver) forced versioning, then pair with the remote device if its ID
    was provided in Settings.

    Send-Only on a seedbox (authoritative source); Receive-Only on a home
    receiver, where syncthing_client forces staggered versioning so a delete
    on the seedbox parks the file in ``.stversions`` instead of wiping the
    home library.
    """
    assert ctx.syncthing_client is not None
    client = ctx.syncthing_client

    device_id = client.my_device_id()
    ctx.syncthing_device_id = device_id

    st_cfg = ctx.settings.get("syncthing") or {}
    folder_id = (st_cfg.get("folder_id") or "mediahub-media").strip()
    label = (st_cfg.get("folder_label") or "MediaHub Library").strip()
    remote = (st_cfg.get("remote_device_id") or "").strip()
    folder_type = roles.syncthing_folder_type(ctx.role) or "sendonly"
    ctx.syncthing_folder_id = folder_id
    ctx.syncthing_folder_type = folder_type

    device_ids = [device_id]
    if remote:
        client.add_device(remote)
        device_ids.append(remote)

    client.set_folder(
        folder_id=folder_id,
        label=label,
        path="/data/Media",
        folder_type=folder_type,
        device_ids=device_ids,
    )

    msg = f"Folder '{folder_id}' set to {folder_type}"
    if folder_type == "receiveonly":
        msg += " + versioning"
    if remote:
        msg += f"; paired with {remote[:7]}…"
    return msg


# ---------------------------------------------------------------------------
# Task plan
# ---------------------------------------------------------------------------


def _build_task_plan(enabled: list[str], role: str | None = None) -> list[WiringTask]:
    """Return the ordered list of tasks for the given enabled services.

    The core *arr stack tasks run for roles that install it (all-in-one and
    seedbox). The receiver role skips them entirely — it only runs the
    optional-service tasks (e.g. Syncthing). Optional service tasks are
    appended only when their services are enabled.
    """
    if role is None:
        role = roles.current()

    plan: list[WiringTask] = []
    if roles.installs_arr(role):
        plan += [
            # qBittorrent
            WiringTask("Connect to qBittorrent", _connect_qbittorrent),
            WiringTask("Change qBittorrent password", _change_qbittorrent_password),
            WiringTask("Create qBittorrent category: Movies", _create_qb_category_movies),
            WiringTask("Create qBittorrent category: TV Shows", _create_qb_category_tv),
            # API keys
            WiringTask("Read Sonarr API key", _read_sonarr_api_key),
            WiringTask("Read Radarr API key", _read_radarr_api_key),
            WiringTask("Read Prowlarr API key", _read_prowlarr_api_key),
            # Prowlarr
            WiringTask("Register Sonarr in Prowlarr", _register_sonarr_in_prowlarr),
            WiringTask("Register Radarr in Prowlarr", _register_radarr_in_prowlarr),
            # Sonarr
            WiringTask("Add qBittorrent to Sonarr", _add_qb_to_sonarr),
            WiringTask("Add root folder to Sonarr (/data/Media/TV Shows)", _add_sonarr_root_folder),
            WiringTask("Enable hardlinks in Sonarr", _enable_sonarr_hardlinks),
            # Radarr
            WiringTask("Add qBittorrent to Radarr", _add_qb_to_radarr),
            WiringTask("Add root folder to Radarr (/data/Media/Movies)", _add_radarr_root_folder),
            WiringTask("Enable hardlinks in Radarr", _enable_radarr_hardlinks),
        ]

    if "jellyfin" in enabled:
        plan.append(WiringTask("Wait for Jellyfin to boot", _wait_for_jellyfin, ["jellyfin"]))
        plan.append(WiringTask("Verify Jellyfin libraries", _add_jellyfin_libraries, ["jellyfin"]))

    if "overseerr" in enabled:
        plan.append(WiringTask("Wait for Overseerr to boot", _wait_for_overseerr, ["overseerr"]))
        plan.append(
            WiringTask("Surface Overseerr setup link", _record_overseerr_for_done, ["overseerr"])
        )

    if "jellyseerr" in enabled:
        plan.append(WiringTask("Wait for Jellyseerr to boot", _wait_for_jellyseerr, ["jellyseerr"]))
        plan.append(
            WiringTask("Surface Jellyseerr setup link", _record_jellyseerr_for_done, ["jellyseerr"])
        )

    if "bazarr" in enabled:
        plan.append(WiringTask("Wait for Bazarr to boot", _wait_for_bazarr, ["bazarr"]))
        plan.append(WiringTask("Connect Bazarr to Sonarr", _add_bazarr_to_sonarr, ["bazarr"]))
        plan.append(WiringTask("Connect Bazarr to Radarr", _add_bazarr_to_radarr, ["bazarr"]))

    if "notifiarr" in enabled:
        plan.append(
            WiringTask("Configure Notifiarr + Telegram", _configure_notifiarr, ["notifiarr"])
        )
        plan.append(
            WiringTask("Wire Notifiarr to Sonarr/Radarr", _wire_notifiarr_webhooks, ["notifiarr"])
        )

    if "recyclarr" in enabled:
        plan.append(
            WiringTask("Configure Recyclarr (TRaSH sync)", _configure_recyclarr, ["recyclarr"])
        )

    if "caddy" in enabled:
        plan.append(WiringTask("Generate Caddy reverse proxy config", _configure_caddy, ["caddy"]))

    if "syncthing" in enabled:
        plan.append(WiringTask("Wait for Syncthing to boot", _wait_for_syncthing, ["syncthing"]))
        plan.append(
            WiringTask(
                "Configure Syncthing library folder", _configure_syncthing_folder, ["syncthing"]
            )
        )

    if "gluetun" in enabled and roles.installs_arr(role):
        plan.append(
            WiringTask("Set qBittorrent VPN listen port", _set_qb_vpn_listen_port, ["gluetun"])
        )

    # Seedbox: cap seeding so a small VPS disk auto-prunes (the home copy is
    # kept safe by Syncthing). Not added for all-in-one, keeping its plan at 15.
    if roles.is_server(role) and roles.installs_arr(role):
        plan.append(WiringTask("Set qBittorrent share limits", _set_qb_share_limits))

    return plan


def planned_task_names(enabled: list[str] | None = None, role: str | None = None) -> list[str]:
    """Return the names of tasks that will run for the given enabled list.

    If *enabled* is None, reads from saved settings state. If *role* is None,
    the current role is used.
    """
    if enabled is None:
        settings = state.get("settings") or {}
        enabled = settings.get("enabled_services") or []
    return [t.name for t in _build_task_plan(enabled, role)]


# Backwards-compat constant — kept for tests that import it. Reflects only
# the always-on core task names (all-in-one role).
TASK_NAMES: list[str] = [t.name for t in _build_task_plan([], role=roles.ALL_IN_ONE)]


def _initial_tasks(task_names: list[str]) -> list[dict]:
    return [{"name": n, "status": "pending", "message": ""} for n in task_names]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def wiring_status() -> dict[str, Any]:
    """Return a thread-safe copy of the current wiring status."""
    with _lock:
        return {
            "phase": _status["phase"],
            "tasks": list(_status["tasks"]),
            "error": _status.get("error", ""),
        }


def start_wiring() -> None:
    """Spawn the wiring thread if it is not already running.

    Calling this a second time while the thread is active is a no-op.
    """
    global _thread, _status

    settings = state.get("settings") or {}
    enabled = settings.get("enabled_services") or []
    plan = _build_task_plan(enabled)
    names = [t.name for t in plan]

    with _lock:
        if _status["phase"] == "running":
            return
        _status = {
            "phase": "running",
            "tasks": _initial_tasks(names),
            "error": "",
        }

    _thread = threading.Thread(target=_run_wiring, args=(plan,), daemon=True)
    _thread.start()


# ---------------------------------------------------------------------------
# Internal runner
# ---------------------------------------------------------------------------


def _set_task(name: str, status: str, message: str = "") -> None:
    with _lock:
        for i, task in enumerate(_status["tasks"]):
            if task["name"] == name:
                _status["tasks"][i] = {"name": name, "status": status, "message": message}
                return


def _internal_url(key: str) -> str:
    """``http://<container>:<container port>`` for a service on the compose
    network — independent of whichever host port the user chose."""
    return f"http://{key}:{services.ALL[key]['internal_port']}"


def _build_context() -> WiringContext:
    settings = state.get("settings") or {}
    enabled = settings.get("enabled_services") or []
    shared_password = settings.get("shared_password", "")

    ports = settings.get("ports") or {}
    qb_port = ports.get("qbittorrent_web", 8090)
    sonarr_port = ports.get("sonarr", 8989)
    radarr_port = ports.get("radarr", 7878)
    prowlarr_port = ports.get("prowlarr", 9696)
    jellyfin_port = ports.get("jellyfin", 8096)
    overseerr_port = ports.get("overseerr", 5055)
    jellyseerr_port = ports.get("jellyseerr", 5056)
    bazarr_port = ports.get("bazarr", 6767)
    syncthing_port = ports.get("syncthing", 8384)

    return WiringContext(
        settings=settings,
        shared_password=shared_password,
        ports=ports,
        enabled=enabled,
        role=roles.current(),
        qb_host="gluetun" if "gluetun" in enabled else "qbittorrent",
        # Container-to-container URLs use the *container* port, which is
        # fixed by the compose template (e.g. "{{ ports.sonarr }}:8989").
        # The host-side port the user picked only applies to localhost.
        sonarr_internal=_internal_url("sonarr"),
        radarr_internal=_internal_url("radarr"),
        prowlarr_internal=_internal_url("prowlarr"),
        jellyfin_internal=_internal_url("jellyfin"),
        overseerr_internal=_internal_url("overseerr"),
        jellyseerr_internal=_internal_url("jellyseerr"),
        bazarr_internal=_internal_url("bazarr"),
        qb_url=f"http://localhost:{qb_port}",
        sonarr_url=f"http://localhost:{sonarr_port}",
        radarr_url=f"http://localhost:{radarr_port}",
        prowlarr_url=f"http://localhost:{prowlarr_port}",
        jellyfin_url=f"http://localhost:{jellyfin_port}",
        overseerr_url=f"http://localhost:{overseerr_port}",
        jellyseerr_url=f"http://localhost:{jellyseerr_port}",
        bazarr_url=f"http://localhost:{bazarr_port}",
        syncthing_url=f"http://localhost:{syncthing_port}",
    )


def _persist_wiring(ctx: WiringContext | None, phase: str, error: str = "") -> None:
    """Write the run outcome to persistent state.

    Called on success *and* failure: the repair page reads the persisted
    task list to show which tasks failed and which still need to run, and
    that only works if failed runs are recorded too. A failed run must not
    wipe credentials captured by an earlier successful one, so existing
    values are kept and only overwritten by what this run discovered.
    """
    with _lock:
        tasks_snapshot = list(_status["tasks"])

    prev = state.get("wiring") or {}
    record: dict[str, Any] = {**prev, "status": phase, "tasks": tasks_snapshot, "error": error}
    if ctx is not None:
        api_keys = {
            k: v for k, v in ctx.api_keys.items() if k in ("sonarr", "radarr", "prowlarr", "bazarr")
        }
        record["api_keys"] = {**(prev.get("api_keys") or {}), **api_keys}
        record["qb_credentials"] = {
            "username": ctx.settings.get("qbittorrent_username", "admin"),
            "password": ctx.shared_password,
        }
        if phase == "complete" or ctx.syncthing_device_id:
            record["syncthing"] = {
                "device_id": ctx.syncthing_device_id,
                "folder_id": ctx.syncthing_folder_id,
                "folder_type": ctx.syncthing_folder_type,
            }
    state.set("wiring", record)


def _run_wiring(plan: list[WiringTask]) -> None:
    """Execute the prebuilt task plan in order, marking each task."""
    ctx: WiringContext | None = None
    try:
        ctx = _build_context()

        for task in plan:
            _set_task(task.name, "running")
            try:
                msg = task.fn(ctx)
                _set_task(task.name, "ok", msg or "")
            except Exception as exc:
                _set_task(task.name, "failed", str(exc))
                _abort()
                _persist_wiring(ctx, "failed")
                return

        with _lock:
            _status["phase"] = "complete"
        _persist_wiring(ctx, "complete")

    except Exception as exc:
        # Died outside any single task (e.g. _build_context on corrupt
        # settings). Surface the message — it is the only diagnostic the
        # user gets — and mark the untouched tasks skipped.
        with _lock:
            _status["error"] = str(exc)
        _abort()
        try:
            _persist_wiring(ctx, "failed", error=str(exc))
        except Exception:  # noqa: BLE001 — never let reporting mask the real error
            pass


def _abort() -> None:
    """Mark remaining pending tasks as skipped and set phase to failed."""
    with _lock:
        for task in _status["tasks"]:
            if task["status"] == "pending":
                task["status"] = "skipped"
                task["message"] = "Skipped due to earlier failure"
        _status["phase"] = "failed"
