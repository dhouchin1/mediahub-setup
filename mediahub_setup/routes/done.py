from flask import Blueprint, redirect, render_template, url_for

from mediahub_setup import state

bp = Blueprint("done", __name__, url_prefix="/done")


@bp.get("/")
def index():
    settings = state.get("settings") or {}
    drive = state.get("drive") or {}
    install = state.get("install") or {}
    wiring = state.get("wiring") or {}

    ports = settings.get("ports") or {}
    shared_password = settings.get("shared_password", "")

    api_keys = wiring.get("api_keys") or {}
    qb_creds = wiring.get("qb_credentials") or {}

    def url(service: str) -> str:
        port_map = {
            "sonarr": ports.get("sonarr", 8989),
            "radarr": ports.get("radarr", 7878),
            "prowlarr": ports.get("prowlarr", 9696),
            "qbittorrent": ports.get("qbittorrent_web", 8080),
        }
        return f"http://localhost:{port_map[service]}"

    services = [
        {
            "name": "Sonarr",
            "role": "TV series manager",
            "url": url("sonarr"),
            "username": None,
            "password": shared_password,
            "api_key": api_keys.get("sonarr", ""),
            "color": "blue",
        },
        {
            "name": "Radarr",
            "role": "Movie manager",
            "url": url("radarr"),
            "username": None,
            "password": shared_password,
            "api_key": api_keys.get("radarr", ""),
            "color": "amber",
        },
        {
            "name": "Prowlarr",
            "role": "Indexer manager",
            "url": url("prowlarr"),
            "username": None,
            "password": shared_password,
            "api_key": api_keys.get("prowlarr", ""),
            "color": "violet",
        },
        {
            "name": "qBittorrent",
            "role": "Download client",
            "url": url("qbittorrent"),
            "username": qb_creds.get("username", "admin"),
            "password": qb_creds.get("password", shared_password),
            "api_key": None,
            "color": "cyan",
        },
    ]

    ctx = {
        "step": "done",
        "services": services,
        "radarr_url": url("radarr"),
        "sonarr_url": url("sonarr"),
        "mount_path": drive.get("mount_path", ""),
        "compose_path": install.get("compose_path", ""),
    }
    return render_template("done.html", **ctx)


@bp.post("/reset")
def reset():
    state.clear()
    return redirect(url_for("welcome.index"), 303)
