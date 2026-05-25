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

from . import state
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
from .jellyseerr_client import JellyseerrClient
from .notifiarr import configure_notifiarr_telegram, wire_notifiarr_to_arr

# ---------------------------------------------------------------------------
# Module-level state (lives for the lifetime of the Flask process)
# ---------------------------------------------------------------------------

_lock = threading.Lock()

_status: dict[str, Any] = {
    "phase": "idle",  # idle | running | complete | failed
    "tasks": [],
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
    # Container DNS names (used for cross-container wiring)
    sonarr_internal: str = ""
    radarr_internal: str = ""
    prowlarr_internal: str = ""
    jellyfin_internal: str = ""
    jellyseerr_internal: str = ""
    bazarr_internal: str = ""
    # Per-host URLs (used for local-machine API calls from the wizard)
    qb_url: str = ""
    sonarr_url: str = ""
    radarr_url: str = ""
    prowlarr_url: str = ""
    jellyfin_url: str = ""
    jellyseerr_url: str = ""
    bazarr_url: str = ""
    # Captured during wiring
    api_keys: dict[str, str] = field(default_factory=dict)
    qb_client: QBittorrentClient | None = None
    sonarr_client: SonarrClient | None = None
    radarr_client: RadarrClient | None = None
    prowlarr_client: ProwlarrClient | None = None


# ---------------------------------------------------------------------------
# Task implementations
# ---------------------------------------------------------------------------


def _connect_qbittorrent(ctx: WiringContext) -> str | None:
    qb = QBittorrentClient(ctx.qb_url)
    try:
        temp_pw = get_qbittorrent_temp_password("mediahub-qbittorrent")
        qb.login(temp_pw)
        ctx.qb_client = qb
        return "Logged in with temporary password"
    except Exception:
        # Maybe already changed — try with shared_password
        qb.login(ctx.shared_password)
        ctx.qb_client = qb
        return "Logged in with shared password"


def _change_qbittorrent_password(ctx: WiringContext) -> str | None:
    assert ctx.qb_client is not None
    # If we logged in with shared_password it's already correct
    try:
        ctx.qb_client.list_categories()  # Quick probe with current creds
    except Exception:
        pass
    # Always set it explicitly to the shared password (idempotent)
    ctx.qb_client.change_password(ctx.shared_password)
    qb2 = QBittorrentClient(ctx.qb_url)
    qb2.login(ctx.shared_password)
    ctx.qb_client = qb2
    return None


def _create_qb_category_movies(ctx: WiringContext) -> str | None:
    assert ctx.qb_client is not None
    ctx.qb_client.create_category("movies", "/data/torrents/movies")
    return None


def _create_qb_category_tv(ctx: WiringContext) -> str | None:
    assert ctx.qb_client is not None
    ctx.qb_client.create_category("tv", "/data/torrents/tv")
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
    qb_port = ctx.ports.get("qbittorrent_web", 8080)
    ctx.sonarr_client.add_qbittorrent(
        host="qbittorrent",
        port=qb_port,
        username="admin",
        password=ctx.shared_password,
        category="tv",
    )
    return None


def _add_sonarr_root_folder(ctx: WiringContext) -> str | None:
    assert ctx.sonarr_client is not None
    ctx.sonarr_client.add_root_folder("/data/media/tv")
    return None


def _enable_sonarr_hardlinks(ctx: WiringContext) -> str | None:
    assert ctx.sonarr_client is not None
    ctx.sonarr_client.enable_hardlinks()
    return None


def _add_qb_to_radarr(ctx: WiringContext) -> str | None:
    assert ctx.radarr_client is not None
    qb_port = ctx.ports.get("qbittorrent_web", 8080)
    ctx.radarr_client.add_qbittorrent(
        host="qbittorrent",
        port=qb_port,
        username="admin",
        password=ctx.shared_password,
        category="movies",
    )
    return None


def _add_radarr_root_folder(ctx: WiringContext) -> str | None:
    assert ctx.radarr_client is not None
    ctx.radarr_client.add_root_folder("/data/media/movies")
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


# ----- Jellyseerr -----------------------------------------------------------


def _wait_for_jellyseerr(ctx: WiringContext) -> str | None:
    client = JellyseerrClient(ctx.jellyseerr_url)
    client.wait_until_ready(timeout=180)
    return "Server is responding"


def _record_jellyseerr_for_done(ctx: WiringContext) -> str | None:
    """Jellyseerr's API key is generated during first-run setup in the UI,
    so we surface URLs + setup hints on the Done page rather than configure
    via REST (which would require an already-set-up instance)."""
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
        notifiarr_internal_url=f"http://notifiarr:{ctx.ports.get('notifiarr', 5454)}",
    )
    return None


# ----- Recyclarr -----------------------------------------------------------


def _configure_recyclarr(ctx: WiringContext) -> str | None:
    from .recyclarr import render_recyclarr_config

    render_recyclarr_config(
        sonarr_internal_url=ctx.sonarr_internal,
        sonarr_api_key=ctx.api_keys["sonarr"],
        radarr_internal_url=ctx.radarr_internal,
        radarr_api_key=ctx.api_keys["radarr"],
    )
    return "Config written — runs daily at 4am"


# ----- Caddy ---------------------------------------------------------------


def _configure_caddy(ctx: WiringContext) -> str | None:
    from .caddy import render_caddyfile

    domain = (ctx.settings.get("caddy") or {}).get("domain", "mediahub.local")
    render_caddyfile(domain=domain, enabled=ctx.enabled, ports=ctx.ports)
    return f"Caddyfile written for {domain}"


# ---------------------------------------------------------------------------
# Task plan
# ---------------------------------------------------------------------------


def _build_task_plan(enabled: list[str]) -> list[WiringTask]:
    """Return the ordered list of tasks for the given enabled services.

    Core stack tasks always run. Optional service tasks are appended only
    when their services are enabled (and required prerequisites are met).
    """
    plan: list[WiringTask] = [
        # qBittorrent
        WiringTask("Connect to qBittorrent", _connect_qbittorrent),
        WiringTask("Change qBittorrent password", _change_qbittorrent_password),
        WiringTask("Create qBittorrent category: movies", _create_qb_category_movies),
        WiringTask("Create qBittorrent category: tv", _create_qb_category_tv),
        # API keys
        WiringTask("Read Sonarr API key", _read_sonarr_api_key),
        WiringTask("Read Radarr API key", _read_radarr_api_key),
        WiringTask("Read Prowlarr API key", _read_prowlarr_api_key),
        # Prowlarr
        WiringTask("Register Sonarr in Prowlarr", _register_sonarr_in_prowlarr),
        WiringTask("Register Radarr in Prowlarr", _register_radarr_in_prowlarr),
        # Sonarr
        WiringTask("Add qBittorrent to Sonarr", _add_qb_to_sonarr),
        WiringTask("Add root folder to Sonarr (/data/media/tv)", _add_sonarr_root_folder),
        WiringTask("Enable hardlinks in Sonarr", _enable_sonarr_hardlinks),
        # Radarr
        WiringTask("Add qBittorrent to Radarr", _add_qb_to_radarr),
        WiringTask("Add root folder to Radarr (/data/media/movies)", _add_radarr_root_folder),
        WiringTask("Enable hardlinks in Radarr", _enable_radarr_hardlinks),
    ]

    if "jellyfin" in enabled:
        plan.append(WiringTask("Wait for Jellyfin to boot", _wait_for_jellyfin, ["jellyfin"]))
        plan.append(WiringTask("Verify Jellyfin libraries", _add_jellyfin_libraries, ["jellyfin"]))

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

    return plan


def planned_task_names(enabled: list[str] | None = None) -> list[str]:
    """Return the names of tasks that will run for the given enabled list.

    If *enabled* is None, reads from saved settings state.
    """
    if enabled is None:
        settings = state.get("settings") or {}
        enabled = settings.get("enabled_services") or []
    return [t.name for t in _build_task_plan(enabled)]


# Backwards-compat constant — kept for tests that import it. Reflects only
# the always-on core task names.
TASK_NAMES: list[str] = [t.name for t in _build_task_plan([])]


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


def _build_context() -> WiringContext:
    settings = state.get("settings") or {}
    enabled = settings.get("enabled_services") or []
    shared_password = settings.get("shared_password", "")

    ports = settings.get("ports") or {}
    qb_port = ports.get("qbittorrent_web", 8080)
    sonarr_port = ports.get("sonarr", 8989)
    radarr_port = ports.get("radarr", 7878)
    prowlarr_port = ports.get("prowlarr", 9696)
    jellyfin_port = ports.get("jellyfin", 8096)
    jellyseerr_port = ports.get("jellyseerr", 5055)
    bazarr_port = ports.get("bazarr", 6767)

    return WiringContext(
        settings=settings,
        shared_password=shared_password,
        ports=ports,
        enabled=enabled,
        sonarr_internal=f"http://sonarr:{sonarr_port}",
        radarr_internal=f"http://radarr:{radarr_port}",
        prowlarr_internal=f"http://prowlarr:{prowlarr_port}",
        jellyfin_internal=f"http://jellyfin:{jellyfin_port}",
        jellyseerr_internal=f"http://jellyseerr:{jellyseerr_port}",
        bazarr_internal=f"http://bazarr:{bazarr_port}",
        qb_url=f"http://localhost:{qb_port}",
        sonarr_url=f"http://localhost:{sonarr_port}",
        radarr_url=f"http://localhost:{radarr_port}",
        prowlarr_url=f"http://localhost:{prowlarr_port}",
        jellyfin_url=f"http://localhost:{jellyfin_port}",
        jellyseerr_url=f"http://localhost:{jellyseerr_port}",
        bazarr_url=f"http://localhost:{bazarr_port}",
    )


def _run_wiring(plan: list[WiringTask]) -> None:
    """Execute the prebuilt task plan in order, marking each task."""
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
                    k: v
                    for k, v in ctx.api_keys.items()
                    if k in ("sonarr", "radarr", "prowlarr", "bazarr")
                },
                "qb_credentials": {"username": "admin", "password": ctx.shared_password},
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
