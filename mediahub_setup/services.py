"""Declarative catalog of every service the wizard can install.

The compose template, settings form, wiring runner, dashboard, and done
page all read from this catalog so that adding a new service only
requires editing one place plus the compose template block.
"""

from __future__ import annotations

from typing import TypedDict


class ServiceDef(TypedDict, total=False):
    name: str  # human label, e.g. "Sonarr"
    role: str  # one-liner, e.g. "TV series manager"
    image: str  # full docker image with tag
    container_name: str  # docker container_name (and DNS hostname inside the network)
    port_key: str  # key into the ports dict (e.g. "sonarr"). qbittorrent uses two.
    default_port: int  # external port
    internal_port: int  # port inside the container (usually same as default_port)
    color: str  # tailwind color name for UI badges
    url_path: str  # URL path appended to host (e.g. "/web/" for Jellyfin)
    auth: str  # "shared_password" | "first_run_setup" | "api_key_only" | "none"
    core: bool  # True = always installed
    depends_on: list[str]  # other service keys this depends on for wiring


# ---------------------------------------------------------------------------
# Core services — always installed
# ---------------------------------------------------------------------------

PROWLARR: ServiceDef = {
    "name": "Prowlarr",
    "role": "Indexer manager",
    "image": "lscr.io/linuxserver/prowlarr:latest",
    "container_name": "mediahub-prowlarr",
    "port_key": "prowlarr",
    "default_port": 9696,
    "internal_port": 9696,
    "color": "violet",
    "url_path": "/",
    "auth": "shared_password",
    "core": True,
    "depends_on": [],
}

SONARR: ServiceDef = {
    "name": "Sonarr",
    "role": "TV series manager",
    "image": "lscr.io/linuxserver/sonarr:latest",
    "container_name": "mediahub-sonarr",
    "port_key": "sonarr",
    "default_port": 8989,
    "internal_port": 8989,
    "color": "blue",
    "url_path": "/",
    "auth": "shared_password",
    "core": True,
    "depends_on": ["prowlarr"],
}

RADARR: ServiceDef = {
    "name": "Radarr",
    "role": "Movie manager",
    "image": "lscr.io/linuxserver/radarr:latest",
    "container_name": "mediahub-radarr",
    "port_key": "radarr",
    "default_port": 7878,
    "internal_port": 7878,
    "color": "amber",
    "url_path": "/",
    "auth": "shared_password",
    "core": True,
    "depends_on": ["prowlarr"],
}

QBITTORRENT: ServiceDef = {
    "name": "qBittorrent",
    "role": "Download client",
    "image": "lscr.io/linuxserver/qbittorrent:latest",
    "container_name": "mediahub-qbittorrent",
    "port_key": "qbittorrent_web",
    "default_port": 8090,
    "internal_port": 8090,
    "color": "cyan",
    "url_path": "/",
    "auth": "shared_password",
    "core": True,
    "depends_on": [],
}


# ---------------------------------------------------------------------------
# Optional services
# ---------------------------------------------------------------------------

JELLYFIN: ServiceDef = {
    "name": "Jellyfin",
    "role": "Media server (play your library)",
    "image": "lscr.io/linuxserver/jellyfin:latest",
    "container_name": "mediahub-jellyfin",
    "port_key": "jellyfin",
    "default_port": 8096,
    "internal_port": 8096,
    "color": "purple",
    "url_path": "/web/",
    "auth": "first_run_setup",
    "core": False,
    "depends_on": [],
}

OVERSEERR: ServiceDef = {
    "name": "Overseerr",
    "role": "Request UI for movies & TV",
    "image": "sctx/overseerr:latest",
    "container_name": "mediahub-overseerr",
    "port_key": "overseerr",
    "default_port": 5055,
    "internal_port": 5055,
    "color": "orange",
    "url_path": "/",
    "auth": "first_run_setup",
    "core": False,
    "depends_on": ["sonarr", "radarr"],
}

# Kept for users who specifically want the Jellyfin-flavoured fork.
# Same API as Overseerr (Jellyseerr is a fork of Overseerr).
JELLYSEERR: ServiceDef = {
    "name": "Jellyseerr",
    "role": "Request UI for movies & TV (Jellyfin fork)",
    "image": "fallenbagel/jellyseerr:latest",
    "container_name": "mediahub-jellyseerr",
    "port_key": "jellyseerr",
    "default_port": 5056,
    "internal_port": 5055,
    "color": "indigo",
    "url_path": "/",
    "auth": "first_run_setup",
    "core": False,
    "depends_on": ["jellyfin", "sonarr", "radarr"],
}

WEB: ServiceDef = {
    "name": "MediaHub Web",
    "role": "Custom Next.js dashboard with status, request, and library views",
    "image": "ghcr.io/dhouchin1/mediahub-web:latest",
    "container_name": "mediahub-web",
    "port_key": "web",
    "default_port": 3000,
    "internal_port": 3000,
    "color": "teal",
    "url_path": "/",
    "auth": "none",
    "core": False,
    "depends_on": ["sonarr", "radarr"],
}

BAZARR: ServiceDef = {
    "name": "Bazarr",
    "role": "Subtitle downloader",
    "image": "lscr.io/linuxserver/bazarr:latest",
    "container_name": "mediahub-bazarr",
    "port_key": "bazarr",
    "default_port": 6767,
    "internal_port": 6767,
    "color": "rose",
    "url_path": "/",
    "auth": "first_run_setup",
    "core": False,
    "depends_on": ["sonarr", "radarr"],
}

FLARESOLVERR: ServiceDef = {
    "name": "Flaresolverr",
    "role": "Cloudflare bypass proxy for indexers",
    "image": "ghcr.io/flaresolverr/flaresolverr:latest",
    "container_name": "mediahub-flaresolverr",
    "port_key": "flaresolverr",
    "default_port": 8191,
    "internal_port": 8191,
    "color": "orange",
    "url_path": "/",
    "auth": "none",
    "core": False,
    "depends_on": ["prowlarr"],
}

NOTIFIARR: ServiceDef = {
    "name": "Notifiarr",
    "role": "Notification router",
    "image": "golift/notifiarr:latest",
    "container_name": "mediahub-notifiarr",
    "port_key": "notifiarr",
    "default_port": 5454,
    "internal_port": 5454,
    "color": "emerald",
    "url_path": "/",
    "auth": "api_key_only",
    "core": False,
    "depends_on": ["sonarr", "radarr", "qbittorrent"],
}

RECYCLARR: ServiceDef = {
    "name": "Recyclarr",
    "role": "TRaSH Guides auto-sync (CLI)",
    "image": "ghcr.io/recyclarr/recyclarr:latest",
    "container_name": "mediahub-recyclarr",
    "port_key": "",  # no port — CLI tool
    "default_port": 0,
    "internal_port": 0,
    "color": "lime",
    "url_path": "",
    "auth": "none",
    "core": False,
    "depends_on": ["sonarr", "radarr"],
}

CADDY: ServiceDef = {
    "name": "Caddy",
    "role": "Reverse proxy with auto-HTTPS",
    "image": "caddy:2-alpine",
    "container_name": "mediahub-caddy",
    "port_key": "caddy",
    "default_port": 80,
    "internal_port": 80,
    "color": "sky",
    "url_path": "/",
    "auth": "none",
    "core": False,
    "depends_on": [],
}

SYNCTHING: ServiceDef = {
    "name": "Syncthing",
    "role": "Library sync between a seedbox and home",
    "image": "syncthing/syncthing:latest",
    "container_name": "mediahub-syncthing",
    "port_key": "syncthing",
    "default_port": 8384,
    "internal_port": 8384,
    "color": "teal",
    "url_path": "/",
    "auth": "first_run_setup",
    "core": False,
    "depends_on": [],
}

GLUETUN: ServiceDef = {
    "name": "Gluetun VPN",
    "role": "Routes qBittorrent traffic through a VPN",
    "image": "qmcgaw/gluetun:latest",
    "container_name": "mediahub-gluetun",
    "port_key": "",  # no UI of its own — it fronts qBittorrent's ports
    "default_port": 0,
    "internal_port": 0,
    "color": "rose",
    "url_path": "",
    "auth": "none",
    "core": False,
    "depends_on": [],
}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

# Ordered for stable display
CORE: dict[str, ServiceDef] = {
    "prowlarr": PROWLARR,
    "sonarr": SONARR,
    "radarr": RADARR,
    "qbittorrent": QBITTORRENT,
}

OPTIONAL: dict[str, ServiceDef] = {
    "jellyfin": JELLYFIN,
    "overseerr": OVERSEERR,
    "jellyseerr": JELLYSEERR,
    "bazarr": BAZARR,
    "web": WEB,
    "flaresolverr": FLARESOLVERR,
    "notifiarr": NOTIFIARR,
    "recyclarr": RECYCLARR,
    "caddy": CADDY,
    "syncthing": SYNCTHING,
    "gluetun": GLUETUN,
}

ALL: dict[str, ServiceDef] = {**CORE, **OPTIONAL}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def core_keys() -> list[str]:
    """Service keys that are always installed."""
    return list(CORE.keys())


def has_port(key: str) -> bool:
    """True if ``key`` is a known service with a web port to poll/proxy.

    False for unknown keys and for services with an empty ``port_key``
    (recyclarr is a CLI tool, gluetun is a network sidecar).
    """
    return bool(ALL.get(key, {}).get("port_key"))


def optional_keys() -> list[str]:
    """Service keys that the user toggles on/off."""
    return list(OPTIONAL.keys())


def enabled_keys(enabled_optional: list[str]) -> list[str]:
    """Full ordered list of services that will be installed.

    Filters *enabled_optional* to only known optional services and
    appends them after the core stack in catalog order.
    """
    return core_keys() + [k for k in optional_keys() if k in enabled_optional]


def resolve_dependencies(enabled_optional: list[str]) -> list[str]:
    """Return *enabled_optional* with missing prerequisites auto-added.

    For example, enabling 'jellyseerr' implicitly enables 'jellyfin'.
    """
    resolved = set(enabled_optional)
    changed = True
    while changed:
        changed = False
        for key in list(resolved):
            for dep in OPTIONAL.get(key, {}).get("depends_on", []):
                if dep in OPTIONAL and dep not in resolved:
                    resolved.add(dep)
                    changed = True
    # Preserve catalog order
    return [k for k in optional_keys() if k in resolved]


def default_ports_for(keys: list[str]) -> dict[str, int]:
    """Build a {port_key: default_port} dict for the given service keys.

    qBittorrent's BT port is added if qbittorrent itself is in *keys*.
    """
    ports: dict[str, int] = {}
    for k in keys:
        svc = ALL.get(k)
        if not svc:
            continue
        port_key = svc.get("port_key") or ""
        port = svc.get("default_port", 0)
        if port_key and port:
            ports[port_key] = port
    if "qbittorrent" in keys:
        ports["qbittorrent_bt"] = 6881
    return ports
