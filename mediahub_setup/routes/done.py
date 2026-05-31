from flask import Blueprint, redirect, render_template, url_for

from mediahub_setup import preflight, roles, services, state

bp = Blueprint("done", __name__, url_prefix="/done")


def _service_card(
    key: str,
    ports: dict,
    api_keys: dict,
    qb_creds: dict,
    shared_password: str,
) -> dict | None:
    """Build the dict consumed by done.html for one service."""
    svc = services.ALL.get(key)
    if not svc:
        return None

    port_key = svc.get("port_key") or ""
    if not port_key:
        return None  # CLI tools (Recyclarr) have no port

    port = ports.get(port_key, svc.get("default_port", 0))
    if not port:
        return None
    url_path = svc.get("url_path", "/")
    url = f"http://localhost:{port}{url_path}"

    auth = svc.get("auth", "shared_password")
    username: str | None = None
    password: str | None = None
    api_key: str | None = api_keys.get(key)

    if auth == "shared_password":
        password = shared_password
        if key == "qbittorrent":
            username = qb_creds.get("username", "admin")
            password = qb_creds.get("password", shared_password)
    elif auth == "first_run_setup":
        password = None  # user sets it in the web UI
    elif auth == "api_key_only":
        password = None

    return {
        "key": key,
        "name": svc.get("name", key),
        "role": svc.get("role", ""),
        "url": url,
        "username": username,
        "password": password,
        "api_key": api_key,
        "color": svc.get("color", "violet"),
        "auth": auth,
    }


@bp.get("/")
def index():
    settings = state.get("settings") or {}
    drive = state.get("drive") or {}
    install = state.get("install") or {}
    wiring = state.get("wiring") or {}

    ports = settings.get("ports") or {}
    shared_password = settings.get("shared_password", "")
    enabled = settings.get("enabled_services") or []

    api_keys = wiring.get("api_keys") or {}
    qb_creds = wiring.get("qb_credentials") or {}
    syncthing_info = wiring.get("syncthing") or {}

    role = roles.current()
    install_arr = roles.installs_arr(role)

    # Core *arr services first (only for roles that install them), then any
    # optional ones in catalog order.
    core = services.core_keys() if install_arr else []
    keys_in_order = core + [k for k in services.optional_keys() if k in enabled]

    svc_cards: list[dict] = []
    for key in keys_in_order:
        card = _service_card(key, ports, api_keys, qb_creds, shared_password)
        if card:
            svc_cards.append(card)

    def url(service: str) -> str:
        port_map = {
            "sonarr": ports.get("sonarr", 8989),
            "radarr": ports.get("radarr", 7878),
            "prowlarr": ports.get("prowlarr", 9696),
            "qbittorrent": ports.get("qbittorrent_web", 8090),
        }
        return f"http://localhost:{port_map[service]}"

    ctx = {
        "step": "done",
        "role": role,
        "install_arr": install_arr,
        "services": svc_cards,
        "radarr_url": url("radarr"),
        "sonarr_url": url("sonarr"),
        "overseerr_enabled": "overseerr" in enabled,
        "overseerr_url": f"http://localhost:{ports.get('overseerr', 5055)}/",
        "jellyseerr_enabled": "jellyseerr" in enabled,
        "jellyseerr_url": f"http://localhost:{ports.get('jellyseerr', 5056)}/",
        "jellyfin_enabled": "jellyfin" in enabled,
        "jellyfin_url": f"http://localhost:{ports.get('jellyfin', 8096)}/web/",
        "web_enabled": "web" in enabled,
        "web_url": f"http://localhost:{ports.get('web', 3000)}/",
        "notifiarr_enabled": "notifiarr" in enabled,
        "notifiarr_url": f"http://localhost:{ports.get('notifiarr', 5454)}/",
        "syncthing_enabled": "syncthing" in enabled,
        "syncthing_url": f"http://localhost:{ports.get('syncthing', 8384)}/",
        "syncthing": syncthing_info,
        "tailnet_ip": preflight.tailscale_ip() if role == roles.SEEDBOX else None,
        "mount_path": drive.get("mount_path", ""),
        "compose_path": install.get("compose_path", ""),
    }
    return render_template("done.html", **ctx)


@bp.post("/reset")
def reset():
    state.clear()
    return redirect(url_for("welcome.index"), 303)
