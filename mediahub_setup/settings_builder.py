"""Build the wizard ``settings`` dict from a plain config mapping.

The web wizard collects settings through the ``/settings`` form
(:mod:`mediahub_setup.routes.settings`). The headless installer
(:mod:`mediahub_setup.headless`) needs the *same* resolved ``settings``
dict — the contract consumed by ``installer.render_compose`` /
``installer.render_env`` and ``wiring_runner`` — but built from a config
file instead of an HTTP form.

This module is that single, form-free builder. It reuses the same low-level
helpers the route uses (``DEFAULT_PORTS``, ``generate_password``,
``services.resolve_dependencies``, ``roles.*``, the recyclarr defaults) so the
two paths can't drift on defaults. ``tests/test_settings_builder.py`` asserts
key-parity against what the route stores.
"""

from __future__ import annotations

from typing import Any

from . import roles, services
from .recyclarr import RADARR_PROFILES, SONARR_PROFILES, default_recyclarr_profiles
from .system_settings import (
    DEFAULT_PORTS,
    detect_gid,
    detect_tz,
    detect_uid,
    generate_password,
)

# Mirrors routes/settings.py: a receiver has no *arr stack, so only services
# that work against the synced library (or are infrastructure) make sense.
_RECEIVER_SAFE_OPTIONAL = {"jellyfin", "syncthing", "caddy"}


class SettingsError(ValueError):
    """Raised when a headless config produces an invalid ``settings`` dict.

    Carries a ``{field: message}`` mapping in :attr:`errors` so the caller can
    print every problem at once rather than failing on the first.
    """

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_settings(role: str | None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a config mapping into the wizard ``settings`` dict.

    *role* (from ``--role`` / the config) wins over ``cfg['role']``. Unknown or
    receiver-unsafe service names are dropped; Syncthing is force-added for the
    seedbox and receiver roles (it is the whole point of those topologies).
    Passwords are auto-generated when not supplied.

    Raises :class:`SettingsError` if the resolved settings fail validation.
    """
    cfg = dict(cfg or {})
    role = roles.normalize(role or cfg.get("role"))

    tz = str(cfg.get("timezone") or cfg.get("tz") or detect_tz()).strip() or "UTC"
    puid = _coerce_int(cfg.get("puid", detect_uid()), detect_uid())
    pgid = _coerce_int(cfg.get("pgid", detect_gid()), detect_gid())

    qb_user = str(cfg.get("qbittorrent_username") or "admin").strip() or "admin"
    shared_password = str(cfg.get("shared_password") or "").strip() or generate_password()

    # Ports: full default set, with optional per-service overrides.
    ports = dict(DEFAULT_PORTS)
    for key, value in (cfg.get("ports") or {}).items():
        if key in DEFAULT_PORTS:
            ports[key] = _coerce_int(value, DEFAULT_PORTS[key])

    # Enabled optional services. ``services: null`` (key absent) mirrors the
    # wizard default (pre-check Caddy on a fresh seedbox); an explicit list is
    # filtered to allowed/role-safe optional services.
    allowed = set(services.optional_keys())
    if role == roles.RECEIVER:
        allowed &= _RECEIVER_SAFE_OPTIONAL
    requested = cfg.get("services")
    if requested is None:
        raw_enabled = ["caddy"] if role == roles.SEEDBOX else []
    else:
        raw_enabled = [str(s) for s in requested if str(s) in allowed]
    if roles.forces_syncthing(role):
        raw_enabled.append("syncthing")
    enabled = services.resolve_dependencies(raw_enabled)

    caddy_cfg = cfg.get("caddy") or {}
    caddy = {
        "domain": str(caddy_cfg.get("domain", "mediahub.local")).strip() or "mediahub.local",
        "mode": str(caddy_cfg.get("mode", "local")).strip().lower() or "local",
    }

    syncthing_cfg = cfg.get("syncthing") or {}
    syncthing = {
        "folder_label": str(syncthing_cfg.get("folder_label") or "MediaHub Library").strip(),
        "folder_id": str(syncthing_cfg.get("folder_id") or "mediahub-media").strip(),
        # The PEER's device ID — for a seedbox this is the home Mac (receiver).
        "remote_device_id": str(syncthing_cfg.get("remote_device_id") or "").strip(),
    }

    gluetun_cfg = cfg.get("gluetun") or {}
    gluetun = {
        "provider": str(gluetun_cfg.get("provider", "")).strip(),
        "vpn_type": str(gluetun_cfg.get("vpn_type", "wireguard")).strip() or "wireguard",
        "wireguard_private_key": str(gluetun_cfg.get("wireguard_private_key", "")).strip(),
        "wireguard_addresses": str(gluetun_cfg.get("wireguard_addresses", "")).strip(),
        "openvpn_user": str(gluetun_cfg.get("openvpn_user", "")).strip(),
        "openvpn_password": str(gluetun_cfg.get("openvpn_password", "")).strip(),
        "server_countries": str(gluetun_cfg.get("server_countries", "")).strip(),
        "port_forwarding": bool(gluetun_cfg.get("port_forwarding", True)),
    }

    retention_cfg = cfg.get("retention") or {}
    retention = {
        "seed_ratio": _coerce_float(retention_cfg.get("seed_ratio", 2.0), 2.0),
        "seed_time_minutes": _coerce_int(retention_cfg.get("seed_time_minutes", 10080), 10080),
        "remove_on_limit": bool(retention_cfg.get("remove_on_limit", True)),
    }

    notifiarr_cfg = cfg.get("notifiarr") or {}
    notifiarr = {
        "telegram_bot_token": str(notifiarr_cfg.get("telegram_bot_token", "")).strip(),
        "telegram_chat_id": str(notifiarr_cfg.get("telegram_chat_id", "")).strip(),
    }

    rec_defaults = default_recyclarr_profiles()
    rec_cfg = cfg.get("recyclarr_profiles") or {}

    def _profiles(arr: str, catalog: dict) -> list[str]:
        chosen = rec_cfg.get(arr) or rec_defaults[arr]
        return [k for k in chosen if k in catalog] or rec_defaults[arr]

    recyclarr_profiles = {
        "sonarr": _profiles("sonarr", SONARR_PROFILES),
        "radarr": _profiles("radarr", RADARR_PROFILES),
    }

    settings: dict[str, Any] = {
        "role": role,
        "tz": tz,
        "puid": puid,
        "pgid": pgid,
        "ports": ports,
        "auto_passwords": True,
        "shared_password": shared_password,
        "qbittorrent_username": qb_user,
        "enabled_services": enabled,
        "recyclarr_profiles": recyclarr_profiles,
        "notifiarr": notifiarr,
        "caddy": caddy,
        # render_compose / wiring read the top-level alias; keep both like the route.
        "caddy_mode": caddy["mode"],
        "syncthing": syncthing,
        "gluetun": gluetun,
        "retention": retention,
    }

    errors = validate_settings(settings)
    if errors:
        raise SettingsError(errors)
    return settings


def validate_settings(settings: dict[str, Any]) -> dict[str, str]:
    """Return a ``{field: message}`` map of problems (empty == valid).

    Mirrors the route's ``_validate`` + ``_validate_gluetun`` rules.
    """
    errors: dict[str, str] = {}

    if not str(settings.get("tz", "")).strip():
        errors["tz"] = "Timezone is required."

    for field in ("puid", "pgid"):
        try:
            if int(settings.get(field)) <= 0:
                errors[field] = "Must be a positive integer."
        except (TypeError, ValueError):
            errors[field] = "Must be a positive integer."

    for key, port in (settings.get("ports") or {}).items():
        try:
            value = int(port)
            if not (1 <= value <= 65535):
                errors[f"port_{key}"] = "Port must be between 1 and 65535."
        except (TypeError, ValueError):
            errors[f"port_{key}"] = "Must be a valid port number."

    # An unknown caddy mode is worse than invalid — the compose template and
    # the Caddyfile renderer disagree on the fallback, so every port ends up
    # unpublished and the whole stack comes up unreachable. Reject it early.
    mode = str(settings.get("caddy_mode", "local"))
    if mode not in ("local", "public"):
        errors["caddy_mode"] = "Caddy mode must be 'local' or 'public'."

    if "gluetun" in (settings.get("enabled_services") or []):
        g = settings.get("gluetun") or {}
        if not g.get("provider"):
            errors["gluetun_provider"] = "VPN provider is required when Gluetun is enabled."
        if g.get("vpn_type") == "openvpn":
            if not (g.get("openvpn_user") and g.get("openvpn_password")):
                errors["gluetun"] = "OpenVPN username and password are required."
        elif not g.get("wireguard_private_key"):
            errors["gluetun"] = "WireGuard private key is required."

    return errors
