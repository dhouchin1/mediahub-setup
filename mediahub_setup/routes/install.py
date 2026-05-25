"""Install wizard step — writes files and runs docker compose up -d."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for

from .. import installer, services, state

bp = Blueprint("install", __name__, url_prefix="/install")

# Core services always shown in the summary / status UI
CORE_SERVICES = [
    {"key": "sonarr", "label": "Sonarr", "port_key": "sonarr"},
    {"key": "radarr", "label": "Radarr", "port_key": "radarr"},
    {"key": "prowlarr", "label": "Prowlarr", "port_key": "prowlarr"},
    {"key": "qbittorrent", "label": "qBittorrent", "port_key": "qbittorrent_web"},
]


def _services_for_settings(settings: dict | None) -> list[dict]:
    """Build the SERVICES list shown in the install UI, adding optional ones
    based on the current settings.enabled_services."""
    out = list(CORE_SERVICES)
    enabled = (settings or {}).get("enabled_services") or []
    for key in enabled:
        if key == "recyclarr":
            continue  # CLI tool, no port to poll
        svc = services.ALL.get(key)
        if not svc:
            continue
        out.append(
            {"key": key, "label": svc.get("name", key), "port_key": svc.get("port_key") or key}
        )
    return out


def _guard() -> tuple | None:
    """Return a redirect response if required upstream state is missing."""
    drive = state.get("drive")
    if not drive:
        flash("Please select a drive first.", "warn")
        return redirect(url_for("drive.index"))
    settings = state.get("settings")
    if not settings:
        flash("Please configure settings first.", "warn")
        return redirect(url_for("settings.index"))
    return None


@bp.get("/")
def index():
    guard = _guard()
    if guard:
        return guard

    drive = state.get("drive")
    settings = state.get("settings")
    status = installer.install_status()
    install_dir = installer.INSTALL_DIR
    svc_list = _services_for_settings(settings)

    return render_template(
        "install.html",
        step="install",
        drive=drive,
        settings=settings,
        install_dir=install_dir,
        services=svc_list,
        status=status,
    )


@bp.post("/start")
def start():
    guard = _guard()
    if guard:
        return guard

    drive = state.get("drive")
    settings = state.get("settings")

    current = installer.install_status()
    if current["status"] == "running":
        # Already in progress — just return to index to watch
        return redirect(url_for("install.index"))

    # Prepare filesystem
    install_dir = installer.prepare_install_dir()
    installer.prepare_media_layout(drive["mount_path"])
    installer.render_compose(install_dir, settings)
    installer.render_env(install_dir, drive, settings)

    # Kick off the background thread
    installer.start_install(install_dir, drive, settings)

    return redirect(url_for("install.index"))


@bp.post("/retry")
def retry():
    """Reset error state and allow a fresh start attempt."""
    guard = _guard()
    if guard:
        return guard

    drive = state.get("drive")
    settings = state.get("settings")

    install_dir = installer.prepare_install_dir()
    installer.prepare_media_layout(drive["mount_path"])
    installer.render_compose(install_dir, settings)
    installer.render_env(install_dir, drive, settings)
    installer.start_install(install_dir, drive, settings)

    return redirect(url_for("install.index"))


@bp.get("/status")
def status():
    """HTMX polling endpoint — returns the status partial."""
    settings = state.get("settings")
    data = installer.install_status()

    # When all services are ready, persist to state for downstream steps
    if data["status"] == "ready":
        state.set(
            "install",
            {
                "compose_path": data["compose_path"],
                "env_path": data["env_path"],
                "status": "ready",
                "services": data["services"],
            },
        )

    ports = settings["ports"] if settings else {}
    svc_list = _services_for_settings(settings)

    return render_template(
        "_partials/install_status.html",
        data=data,
        services=svc_list,
        ports=ports,
    )
