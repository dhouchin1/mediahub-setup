from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from .. import roles, services, state
from ..recyclarr import (
    RADARR_PROFILES,
    SONARR_PROFILES,
    default_recyclarr_profiles,
)
from ..system_settings import (
    DEFAULT_PORTS,
    detect_gid,
    detect_tz,
    detect_uid,
    generate_password,
)

bp = Blueprint("settings", __name__, url_prefix="/settings")

# A receiver has no *arr stack, so only services that work against the synced
# library (or are infrastructure) are offered there.
_RECEIVER_SAFE_OPTIONAL = {"jellyfin", "syncthing", "caddy"}


def _optional_services_for(role: str) -> dict:
    """Optional services offered for *role* (the receiver hides *arr-dependent ones)."""
    if role == roles.RECEIVER:
        return {k: v for k, v in services.OPTIONAL.items() if k in _RECEIVER_SAFE_OPTIONAL}
    return services.OPTIONAL


def _default_form() -> dict:
    """Return form defaults, preferring previously-saved state."""
    saved = state.get("settings") or {}
    ports = saved.get("ports", DEFAULT_PORTS)
    enabled = saved.get("enabled_services")
    if not enabled:
        # Pre-check Caddy on a fresh seedbox so its IP allowlist (Tailnet +
        # RFC1918) fronts the stack by default — never raw on the public IP.
        enabled = ["caddy"] if roles.current() == roles.SEEDBOX else []
    notifiarr_cfg = saved.get("notifiarr") or {}
    caddy_cfg = saved.get("caddy") or {}
    syncthing_cfg = saved.get("syncthing") or {}
    gluetun_cfg = saved.get("gluetun") or {}
    retention_cfg = saved.get("retention") or {}
    recyclarr_profiles = saved.get("recyclarr_profiles") or default_recyclarr_profiles()
    return {
        "role": roles.current(),
        "tz": saved.get("tz") or detect_tz(),
        "puid": saved.get("puid", detect_uid()),
        "pgid": saved.get("pgid", detect_gid()),
        "ports": {k: ports.get(k, DEFAULT_PORTS[k]) for k in DEFAULT_PORTS},
        "auto_passwords": saved.get("auto_passwords", True),
        "shared_password": saved.get("shared_password") or generate_password(),
        "qbittorrent_username": saved.get("qbittorrent_username", "admin"),
        "enabled_services": enabled,
        "optional_services": _optional_services_for(roles.current()),
        "notifiarr": {
            "telegram_bot_token": notifiarr_cfg.get("telegram_bot_token", ""),
            "telegram_chat_id": notifiarr_cfg.get("telegram_chat_id", ""),
        },
        "caddy": {
            "domain": caddy_cfg.get("domain", "mediahub.local"),
            "mode": caddy_cfg.get("mode", "local"),
        },
        "syncthing": {
            "folder_label": syncthing_cfg.get("folder_label", "MediaHub Library"),
            "folder_id": syncthing_cfg.get("folder_id", "mediahub-media"),
            "remote_device_id": syncthing_cfg.get("remote_device_id", ""),
        },
        "gluetun": {
            "provider": gluetun_cfg.get("provider", "mullvad"),
            "vpn_type": gluetun_cfg.get("vpn_type", "wireguard"),
            "wireguard_private_key": gluetun_cfg.get("wireguard_private_key", ""),
            "wireguard_addresses": gluetun_cfg.get("wireguard_addresses", ""),
            "openvpn_user": gluetun_cfg.get("openvpn_user", ""),
            "openvpn_password": gluetun_cfg.get("openvpn_password", ""),
            "server_countries": gluetun_cfg.get("server_countries", ""),
            "port_forwarding": gluetun_cfg.get("port_forwarding", True),
        },
        "retention": {
            "seed_ratio": retention_cfg.get("seed_ratio", 2.0),
            "seed_time_minutes": retention_cfg.get("seed_time_minutes", 10080),
            "remove_on_limit": retention_cfg.get("remove_on_limit", True),
        },
        "recyclarr_profiles": recyclarr_profiles,
        "sonarr_recyclarr_profiles": SONARR_PROFILES,
        "radarr_recyclarr_profiles": RADARR_PROFILES,
    }


def _validate(form: dict) -> dict[str, str]:
    errors: dict[str, str] = {}

    tz = form.get("tz", "").strip()
    if not tz:
        errors["tz"] = "Timezone is required."

    for field in ("puid", "pgid"):
        raw = form.get(field, "")
        try:
            val = int(raw)
            # 0 (root) is valid: headless/root installs use PUID=0, which
            # the linuxserver.io images accept.
            if val < 0:
                errors[field] = "Must be a non-negative integer."
        except (TypeError, ValueError):
            errors[field] = "Must be a non-negative integer."

    for svc in DEFAULT_PORTS:
        key = f"port_{svc}"
        raw = form.get(key, "")
        if raw == "" or raw is None:
            continue  # not overridden — use default
        try:
            port = int(raw)
            # Privileged ports (1-1023) are allowed for Caddy (80/443) when
            # using Docker Desktop or OrbStack, which handle the binding.
            if not (1 <= port <= 65535):
                errors[key] = "Port must be between 1 and 65535."
        except (TypeError, ValueError):
            errors[key] = "Must be a valid port number."

    return errors


def _parse_gluetun(f) -> dict:
    return {
        "provider": f.get("gluetun_provider", "").strip(),
        "vpn_type": f.get("gluetun_vpn_type", "wireguard").strip() or "wireguard",
        "wireguard_private_key": f.get("gluetun_wireguard_private_key", "").strip(),
        "wireguard_addresses": f.get("gluetun_wireguard_addresses", "").strip(),
        "openvpn_user": f.get("gluetun_openvpn_user", "").strip(),
        "openvpn_password": f.get("gluetun_openvpn_password", "").strip(),
        "server_countries": f.get("gluetun_server_countries", "").strip(),
        "port_forwarding": "gluetun_port_forwarding" in f,
    }


def _validate_gluetun(cfg: dict) -> dict[str, str]:
    """Require the credentials matching the chosen VPN type."""
    errs: dict[str, str] = {}
    if not cfg.get("provider"):
        errs["gluetun_provider"] = "VPN provider is required."
    if cfg.get("vpn_type") == "openvpn":
        if not (cfg.get("openvpn_user") and cfg.get("openvpn_password")):
            errs["gluetun"] = "OpenVPN username and password are required."
    elif not cfg.get("wireguard_private_key"):
        errs["gluetun"] = "WireGuard private key is required."
    return errs


def _parse_retention(f) -> dict:
    """Parse the seedbox retention fields, falling back to sane defaults."""

    def _num(key, default, cast):
        raw = f.get(key, "").strip()
        try:
            return cast(raw) if raw else default
        except (TypeError, ValueError):
            return default

    return {
        "seed_ratio": _num("retention_seed_ratio", 2.0, float),
        "seed_time_minutes": _num("retention_seed_time_minutes", 10080, int),
        "remove_on_limit": "retention_remove_on_limit" in f,
    }


@bp.get("/")
def index():
    defaults = _default_form()
    return render_template(
        "settings.html",
        step="settings",
        errors={},
        **defaults,
    )


@bp.post("/")
def submit():
    f = request.form

    auto_passwords = "auto_passwords" in f

    # Resolve enabled optional services (auto-add prerequisites). The seedbox
    # and receiver roles always include Syncthing — it's the whole point.
    allowed_optional = set(_optional_services_for(roles.current()).keys())
    raw_enabled = [k for k in f.getlist("enabled_services") if k in allowed_optional]
    if roles.forces_syncthing(roles.current()):
        raw_enabled.append("syncthing")
    enabled = services.resolve_dependencies(raw_enabled)
    gluetun_cfg = _parse_gluetun(f)
    retention_cfg = _parse_retention(f)

    # Rebuild a form dict for re-rendering on error
    port_overrides: dict[str, int | str] = {}
    for svc in DEFAULT_PORTS:
        raw = f.get(f"port_{svc}", "").strip()
        port_overrides[svc] = raw if raw else DEFAULT_PORTS[svc]

    qb_username = f.get("qbittorrent_username", "").strip() or "admin"

    form_data = {
        "tz": f.get("tz", "").strip(),
        "puid": f.get("puid", ""),
        "pgid": f.get("pgid", ""),
        "auto_passwords": auto_passwords,
        "shared_password": f.get("shared_password", "").strip() or generate_password(),
        "qbittorrent_username": qb_username,
        "ports": port_overrides,
        **{f"port_{svc}": f.get(f"port_{svc}", "") for svc in DEFAULT_PORTS},
    }

    errors = _validate(
        {
            "tz": form_data["tz"],
            "puid": form_data["puid"],
            "pgid": form_data["pgid"],
            **{f"port_{svc}": form_data[f"port_{svc}"] for svc in DEFAULT_PORTS},
        }
    )
    if "gluetun" in enabled:
        errors.update(_validate_gluetun(gluetun_cfg))

    if errors:
        return (
            render_template(
                "settings.html",
                step="settings",
                errors=errors,
                role=roles.current(),
                tz=form_data["tz"],
                puid=form_data["puid"],
                pgid=form_data["pgid"],
                auto_passwords=form_data["auto_passwords"],
                shared_password=form_data["shared_password"],
                qbittorrent_username=form_data["qbittorrent_username"],
                ports=form_data["ports"],
                enabled_services=enabled,
                optional_services=_optional_services_for(roles.current()),
                notifiarr={
                    "telegram_bot_token": f.get("notifiarr_telegram_bot_token", "").strip(),
                    "telegram_chat_id": f.get("notifiarr_telegram_chat_id", "").strip(),
                },
                caddy={
                    "domain": f.get("caddy_domain", "mediahub.local").strip(),
                    "mode": f.get("caddy_mode", "local").strip() or "local",
                },
                syncthing={
                    "folder_label": f.get("syncthing_folder_label", "").strip(),
                    "folder_id": f.get("syncthing_folder_id", "").strip(),
                    "remote_device_id": f.get("syncthing_remote_device_id", "").strip(),
                },
                gluetun=gluetun_cfg,
                retention=retention_cfg,
                recyclarr_profiles={
                    "sonarr": f.getlist("recyclarr_sonarr_profiles")
                    or default_recyclarr_profiles()["sonarr"],
                    "radarr": f.getlist("recyclarr_radarr_profiles")
                    or default_recyclarr_profiles()["radarr"],
                },
                sonarr_recyclarr_profiles=SONARR_PROFILES,
                radarr_recyclarr_profiles=RADARR_PROFILES,
            ),
            422,
        )

    # Build final resolved ports (use default if blank)
    final_ports: dict[str, int] = {}
    for svc, default in DEFAULT_PORTS.items():
        raw = f.get(f"port_{svc}", "").strip()
        final_ports[svc] = int(raw) if raw else default

    # Resolve Recyclarr profile selection. Unknown keys are ignored.
    recyclarr_profiles = {
        "sonarr": [k for k in f.getlist("recyclarr_sonarr_profiles") if k in SONARR_PROFILES],
        "radarr": [k for k in f.getlist("recyclarr_radarr_profiles") if k in RADARR_PROFILES],
    }
    # Fall back to defaults if user disabled all checkboxes for an arr.
    if not recyclarr_profiles["sonarr"]:
        recyclarr_profiles["sonarr"] = default_recyclarr_profiles()["sonarr"]
    if not recyclarr_profiles["radarr"]:
        recyclarr_profiles["radarr"] = default_recyclarr_profiles()["radarr"]

    state.set(
        "settings",
        {
            "role": roles.current(),
            "tz": form_data["tz"],
            "puid": int(form_data["puid"]),
            "pgid": int(form_data["pgid"]),
            "ports": final_ports,
            "auto_passwords": auto_passwords,
            "shared_password": form_data["shared_password"] if auto_passwords else None,
            "qbittorrent_username": form_data["qbittorrent_username"],
            "enabled_services": enabled,
            "recyclarr_profiles": recyclarr_profiles,
            "notifiarr": {
                "telegram_bot_token": f.get("notifiarr_telegram_bot_token", "").strip(),
                "telegram_chat_id": f.get("notifiarr_telegram_chat_id", "").strip(),
            },
            "caddy": {
                "domain": f.get("caddy_domain", "mediahub.local").strip(),
                "mode": f.get("caddy_mode", "local").strip() or "local",
            },
            "caddy_mode": f.get("caddy_mode", "local").strip() or "local",
            "syncthing": {
                "folder_label": f.get("syncthing_folder_label", "").strip() or "MediaHub Library",
                "folder_id": f.get("syncthing_folder_id", "").strip() or "mediahub-media",
                "remote_device_id": f.get("syncthing_remote_device_id", "").strip(),
            },
            "gluetun": gluetun_cfg,
            "retention": retention_cfg,
        },
    )

    return redirect(url_for("install.index"), 303)
