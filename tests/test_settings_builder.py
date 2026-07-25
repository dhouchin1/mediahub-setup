"""Tests for mediahub_setup.settings_builder.

The headless installer and the web wizard must produce the *same* settings
contract. ``test_key_parity_with_wizard`` is the guard against drift.
"""

from __future__ import annotations

import pytest

from mediahub_setup import roles, services
from mediahub_setup.settings_builder import SettingsError, build_settings, validate_settings

# The exact top-level keys routes/settings.py stores under state["settings"].
_WIZARD_KEYS = {
    "role",
    "tz",
    "puid",
    "pgid",
    "ports",
    "auto_passwords",
    "shared_password",
    "qbittorrent_username",
    "enabled_services",
    "recyclarr_profiles",
    "notifiarr",
    "caddy",
    "caddy_mode",
    "syncthing",
    "gluetun",
    "retention",
}


def test_key_parity_with_wizard():
    """build_settings must emit exactly the keys the wizard stores."""
    assert set(build_settings("seedbox", {}).keys()) == _WIZARD_KEYS


def test_seedbox_defaults():
    s = build_settings("seedbox", {"data_dir": "/mnt/data"})
    assert s["role"] == roles.SEEDBOX
    assert "syncthing" in s["enabled_services"]  # forced for the role
    assert "caddy" in s["enabled_services"]  # pre-enabled on a fresh seedbox
    assert s["ports"]["sonarr"] == 8989
    assert s["shared_password"] and len(s["shared_password"]) == 16
    assert s["caddy_mode"] == s["caddy"]["mode"] == "local"


def test_receiver_has_no_caddy_default_but_forces_syncthing():
    s = build_settings("receiver", {})
    assert s["role"] == roles.RECEIVER
    assert s["enabled_services"] == services.resolve_dependencies(["syncthing"])
    assert "caddy" not in s["enabled_services"]


def test_explicit_services_filtered_and_unknown_dropped():
    s = build_settings("seedbox", {"services": ["jellyfin", "bogus", "bazarr"]})
    assert "jellyfin" in s["enabled_services"]
    assert "bazarr" in s["enabled_services"]
    assert "bogus" not in s["enabled_services"]
    assert "syncthing" in s["enabled_services"]  # still forced


def test_receiver_drops_arr_only_optional_services():
    s = build_settings("receiver", {"services": ["gluetun", "bazarr", "jellyfin"]})
    assert "gluetun" not in s["enabled_services"]
    assert "bazarr" not in s["enabled_services"]
    assert "jellyfin" in s["enabled_services"]


def test_port_override():
    s = build_settings("seedbox", {"ports": {"sonarr": 19000}})
    assert s["ports"]["sonarr"] == 19000


def test_explicit_password_respected():
    s = build_settings("seedbox", {"shared_password": "MyTopSecret123"})
    assert s["shared_password"] == "MyTopSecret123"


def test_syncthing_remote_device_id_carried_through():
    s = build_settings("seedbox", {"syncthing": {"remote_device_id": "ABC-123"}})
    assert s["syncthing"]["remote_device_id"] == "ABC-123"


def test_gluetun_enabled_without_credentials_raises():
    with pytest.raises(SettingsError) as ei:
        build_settings("seedbox", {"services": ["gluetun"]})
    assert "gluetun" in str(ei.value).lower()


def test_gluetun_wireguard_credentials_ok():
    s = build_settings(
        "seedbox",
        {
            "services": ["gluetun"],
            "gluetun": {
                "provider": "mullvad",
                "vpn_type": "wireguard",
                "wireguard_private_key": "PRIVKEY",
            },
        },
    )
    assert "gluetun" in s["enabled_services"]
    assert s["gluetun"]["provider"] == "mullvad"


def test_gluetun_openvpn_requires_user_and_password():
    with pytest.raises(SettingsError):
        build_settings(
            "seedbox",
            {
                "services": ["gluetun"],
                "gluetun": {"provider": "pia", "vpn_type": "openvpn", "openvpn_user": "u"},
            },
        )


def test_validate_rejects_out_of_range_port():
    s = build_settings("seedbox", {})
    s["ports"]["sonarr"] = 99999
    errs = validate_settings(s)
    assert "port_sonarr" in errs


def test_role_aliases_normalise():
    assert build_settings("vps", {})["role"] == roles.SEEDBOX
    assert build_settings("home", {})["role"] == roles.RECEIVER


def test_receiver_cannot_enable_caddy():
    """A receiver never runs the wiring step, so the Caddyfile is never
    generated — offering caddy would ship a guaranteed crash-looping
    container mounting a nonexistent config."""
    s = build_settings("receiver", {"services": ["caddy", "jellyfin"]})
    assert "caddy" not in s["enabled_services"]
    assert "jellyfin" in s["enabled_services"]
