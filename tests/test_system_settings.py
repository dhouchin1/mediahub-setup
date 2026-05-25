"""Tests for mediahub_setup.system_settings helpers."""

from __future__ import annotations

import os
from unittest.mock import patch

from mediahub_setup.system_settings import (
    _AMBIGUOUS,
    _CHARSET,
    DEFAULT_PORTS,
    detect_gid,
    detect_tz,
    detect_uid,
    generate_password,
)

# ---------------------------------------------------------------------------
# detect_tz
# ---------------------------------------------------------------------------


def test_detect_tz_parses_zoneinfo_symlink(tmp_path):
    """Symlink that contains zoneinfo/<tz> returns the timezone portion."""
    fake_tz = tmp_path / "America" / "Detroit"
    fake_tz.parent.mkdir(parents=True)
    fake_tz.touch()

    localtime = tmp_path / "localtime"
    localtime.symlink_to(fake_tz)

    with patch("mediahub_setup.system_settings.os.readlink", return_value=str(fake_tz)):
        # Inject a path that contains "zoneinfo/" so the marker is found
        zoneinfo_path = str(tmp_path) + "/zoneinfo/America/Detroit"
        with patch("mediahub_setup.system_settings.os.readlink", return_value=zoneinfo_path):
            result = detect_tz()
    assert result == "America/Detroit"


def test_detect_tz_falls_back_to_utc_on_oserror():
    """If readlink raises OSError, return 'UTC'."""
    with patch("mediahub_setup.system_settings.os.readlink", side_effect=OSError):
        assert detect_tz() == "UTC"


def test_detect_tz_falls_back_to_utc_when_no_marker():
    """If the symlink target doesn't contain 'zoneinfo/', return 'UTC'."""
    with patch(
        "mediahub_setup.system_settings.os.readlink",
        return_value="/etc/some/random/path",
    ):
        assert detect_tz() == "UTC"


def test_detect_tz_strips_correctly_for_common_macos_path():
    symlink_target = "/var/db/timezone/zoneinfo/Europe/London"
    with patch("mediahub_setup.system_settings.os.readlink", return_value=symlink_target):
        result = detect_tz()
    assert result == "Europe/London"


# ---------------------------------------------------------------------------
# detect_uid / detect_gid
# ---------------------------------------------------------------------------


def test_detect_uid_matches_os_getuid():
    assert detect_uid() == os.getuid()


def test_detect_gid_matches_os_getgid():
    assert detect_gid() == os.getgid()


# ---------------------------------------------------------------------------
# generate_password
# ---------------------------------------------------------------------------


def test_generate_password_default_length():
    pw = generate_password()
    assert len(pw) == 16


def test_generate_password_custom_length():
    for length in (8, 20, 32):
        pw = generate_password(length)
        assert len(pw) == length, f"expected length {length}, got {len(pw)}"


def test_generate_password_no_ambiguous_chars():
    for _ in range(100):
        pw = generate_password(32)
        for ch in _AMBIGUOUS:
            assert ch not in pw, f"ambiguous char {ch!r} found in password"


def test_generate_password_only_charset_chars():
    charset = set(_CHARSET)
    for _ in range(50):
        pw = generate_password(24)
        for ch in pw:
            assert ch in charset, f"unexpected char {ch!r}"


def test_generate_password_uniqueness():
    """Two calls should (virtually always) produce different results."""
    passwords = {generate_password() for _ in range(20)}
    assert len(passwords) > 1, "all 20 passwords were identical — suspiciously broken"


# ---------------------------------------------------------------------------
# DEFAULT_PORTS
# ---------------------------------------------------------------------------


def test_default_ports_contains_all_core_services():
    """Core services must always be present in DEFAULT_PORTS."""
    required = {"sonarr", "radarr", "prowlarr", "qbittorrent_web", "qbittorrent_bt"}
    assert required <= set(DEFAULT_PORTS.keys())


def test_default_ports_includes_optional_services():
    """Optional services should also have default ports (used when enabled)."""
    optional = {"jellyfin", "jellyseerr", "bazarr", "flaresolverr", "notifiarr", "caddy"}
    assert optional <= set(DEFAULT_PORTS.keys())


def test_default_ports_values_are_valid():
    """Every port must be in the valid 1-65535 range. Caddy uses privileged
    port 80, which is valid; the launcher tier (Docker Desktop / OrbStack)
    handles the privileged-bind."""
    for svc, port in DEFAULT_PORTS.items():
        assert 1 <= port <= 65535, f"port {port} for {svc} is out of range"
