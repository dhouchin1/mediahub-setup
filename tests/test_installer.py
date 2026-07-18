"""Tests for mediahub_setup.installer.

Covers:
- render_compose: template renders with correct substitutions
- render_env: .env file has expected key=value pairs
- prepare_install_dir: creates the directory
- prepare_media_layout: creates expected subdirectory tree
- install_status: returns expected dict shape at idle
- start_install: idempotent, does not spawn a real docker process
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
import yaml

from mediahub_setup import installer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SETTINGS = {
    "tz": "America/Detroit",
    "puid": 501,
    "pgid": 20,
    "ports": {
        "sonarr": 8989,
        "radarr": 7878,
        "prowlarr": 9696,
        "qbittorrent_web": 8080,
        "qbittorrent_bt": 6881,
    },
    "password": "s3cr3t",
}

SAMPLE_DRIVE = {"mount_path": "/Volumes/Ultra", "name": "Ultra", "free_gb": 800}


# ---------------------------------------------------------------------------
# render_compose
# ---------------------------------------------------------------------------


def test_render_compose_creates_file(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    assert out.exists()
    assert out.name == "docker-compose.yml"


def test_render_compose_contains_service_names(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    text = out.read_text()
    for svc in ("sonarr", "radarr", "prowlarr", "qbittorrent"):
        assert svc in text, f"'{svc}' not found in rendered compose"


def test_render_compose_substitutes_timezone(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    assert "America/Detroit" in out.read_text()


def test_render_compose_substitutes_puid_pgid(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    text = out.read_text()
    assert "501" in text
    assert "20" in text


def test_render_compose_substitutes_sonarr_port(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    assert "8989:8989" in out.read_text()


def test_render_compose_substitutes_radarr_port(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    assert "7878:7878" in out.read_text()


def test_render_compose_substitutes_prowlarr_port(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    assert "9696:9696" in out.read_text()


def test_render_compose_substitutes_qbt_web_port(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    text = out.read_text()
    assert "8080:8080" in text


def test_render_compose_substitutes_qbt_bt_port(tmp_path):
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    text = out.read_text()
    assert "6881:6881" in text


def test_render_compose_keeps_media_root_env_var(tmp_path):
    """${MEDIA_ROOT} must remain in the file for docker compose .env expansion."""
    out = installer.render_compose(tmp_path, SAMPLE_SETTINGS)
    assert "${MEDIA_ROOT}" in out.read_text()


def test_render_compose_custom_ports(tmp_path):
    settings = dict(SAMPLE_SETTINGS)
    settings["ports"] = dict(SAMPLE_SETTINGS["ports"])
    settings["ports"]["sonarr"] = 19000
    out = installer.render_compose(tmp_path, settings)
    assert "19000:8989" in out.read_text()


def test_render_compose_caddy_local_hides_notifiarr_flaresolverr_ports(tmp_path):
    """With Caddy in local mode, notifiarr/flaresolverr must not publish host
    ports directly (Caddy fronts them via its IP allowlist), and Caddy itself
    must publish their ports so the allowlisted routes are reachable."""
    settings = {
        **SAMPLE_SETTINGS,
        "enabled_services": ["caddy", "notifiarr", "flaresolverr"],
        "caddy_mode": "local",
        "ports": {**SAMPLE_SETTINGS["ports"], "notifiarr": 5454, "flaresolverr": 8191},
    }
    doc = yaml.safe_load(installer.render_compose(tmp_path, settings).read_text())
    assert "ports" not in doc["services"]["notifiarr"]
    assert "ports" not in doc["services"]["flaresolverr"]
    caddy_ports = doc["services"]["caddy"]["ports"]
    assert "5454:5454" in caddy_ports
    assert "8191:8191" in caddy_ports


def test_render_compose_no_caddy_publishes_notifiarr_flaresolverr(tmp_path):
    """Without Caddy the services keep publishing their own host ports."""
    settings = {
        **SAMPLE_SETTINGS,
        "enabled_services": ["notifiarr", "flaresolverr"],
        "ports": {**SAMPLE_SETTINGS["ports"], "notifiarr": 5454, "flaresolverr": 8191},
    }
    doc = yaml.safe_load(installer.render_compose(tmp_path, settings).read_text())
    assert "5454:5454" in doc["services"]["notifiarr"]["ports"]
    assert "8191:8191" in doc["services"]["flaresolverr"]["ports"]


def test_render_compose_creates_parent_dir(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    out = installer.render_compose(nested, SAMPLE_SETTINGS)
    assert out.exists()


def test_render_compose_seedbox_keeps_arr(tmp_path):
    """The seedbox role installs the full *arr acquisition stack."""
    text = installer.render_compose(tmp_path, {**SAMPLE_SETTINGS, "role": "seedbox"}).read_text()
    assert "mediahub-sonarr" in text
    assert "mediahub-qbittorrent" in text
    assert "8989:8989" in text


def test_render_compose_receiver_omits_arr(tmp_path):
    """The receiver role holds only the synced library — no *arr stack."""
    text = installer.render_compose(tmp_path, {**SAMPLE_SETTINGS, "role": "receiver"}).read_text()
    assert "mediahub-sonarr" not in text
    assert "mediahub-radarr" not in text
    assert "mediahub-prowlarr" not in text
    assert "mediahub-qbittorrent" not in text


def _settings_with_syncthing(**extra):
    return {
        **SAMPLE_SETTINGS,
        "enabled_services": ["syncthing"],
        "ports": {**SAMPLE_SETTINGS["ports"], "syncthing": 8384},
        **extra,
    }


def test_render_compose_syncthing_shares_media_only(tmp_path):
    """Syncthing mounts ONLY the Media subtree and publishes its sync ports."""
    text = installer.render_compose(tmp_path, _settings_with_syncthing()).read_text()
    assert "mediahub-syncthing" in text
    assert "${MEDIA_ROOT}/Media:/data/Media" in text
    assert "22000:22000/tcp" in text
    assert "21027:21027/udp" in text
    # The Syncthing service block must never mount the Torrents subtree.
    block = text[text.index("  syncthing:") :]
    block = block[: block.index("restart: unless-stopped")]
    assert "/data/Torrents" not in block


def test_render_compose_seedbox_loopback_binds_syncthing_gui(tmp_path):
    """On a seedbox the GUI binds to loopback (reached over Tailscale)."""
    text = installer.render_compose(tmp_path, _settings_with_syncthing(role="seedbox")).read_text()
    assert "127.0.0.1:8384:8384" in text


def test_render_compose_all_in_one_does_not_loopback_bind(tmp_path):
    """All-in-one keeps 0.0.0.0 binding (LAN access) — no 127.0.0.1 prefix."""
    text = installer.render_compose(tmp_path, _settings_with_syncthing()).read_text()
    assert "127.0.0.1:8384" not in text
    assert "8384:8384" in text


def test_render_compose_seedbox_loopback_binds_all_web_uis(tmp_path):
    """On a seedbox every published web UI binds to loopback; torrent ports don't."""
    text = installer.render_compose(tmp_path, {**SAMPLE_SETTINGS, "role": "seedbox"}).read_text()
    assert "127.0.0.1:8989:8989" in text  # sonarr
    assert "127.0.0.1:7878:7878" in text  # radarr
    assert "127.0.0.1:9696:9696" in text  # prowlarr
    assert "127.0.0.1:8080:8080" in text  # qbittorrent web (SAMPLE uses 8080)
    # The BitTorrent port must stay public so peers can connect.
    assert "127.0.0.1:6881" not in text
    assert "6881:6881" in text


def test_render_compose_all_in_one_has_no_loopback_anywhere(tmp_path):
    """The default role never loopback-binds — preserves LAN access."""
    text = installer.render_compose(tmp_path, SAMPLE_SETTINGS).read_text()
    assert "127.0.0.1:" not in text


def _qbittorrent_block(text: str) -> str:
    start = text.index("  qbittorrent:")
    return text[start : text.index("restart: unless-stopped", start)]


def _settings_with_gluetun(**extra):
    return {
        **SAMPLE_SETTINGS,
        "enabled_services": ["gluetun"],
        "gluetun": {
            "provider": "mullvad",
            "vpn_type": "wireguard",
            "wireguard_private_key": "PRIVKEY",
            "wireguard_addresses": "10.64.0.2/32",
            "port_forwarding": True,
        },
        **extra,
    }


def test_render_compose_gluetun_routes_qbittorrent_through_vpn(tmp_path):
    text = installer.render_compose(tmp_path, _settings_with_gluetun()).read_text()
    assert "mediahub-gluetun" in text
    assert 'network_mode: "service:gluetun"' in text
    assert "${WIREGUARD_PRIVATE_KEY}" in text
    assert 'VPN_PORT_FORWARDING: "on"' in text
    # qBittorrent must NOT declare its own ports when sharing gluetun's netns.
    qb = _qbittorrent_block(text)
    assert "ports:" not in qb
    assert "network_mode" in qb


def test_render_compose_gluetun_off_is_unchanged(tmp_path):
    """With gluetun off, qBittorrent keeps its own ports and no network_mode."""
    qb = _qbittorrent_block(installer.render_compose(tmp_path, SAMPLE_SETTINGS).read_text())
    assert "ports:" in qb
    assert "network_mode" not in qb
    assert "mediahub-gluetun" not in qb


def test_render_env_writes_vpn_placeholders(tmp_path):
    text = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS).read_text()
    for key in (
        "WIREGUARD_PRIVATE_KEY=",
        "WIREGUARD_ADDRESSES=",
        "OPENVPN_USER=",
        "OPENVPN_PASSWORD=",
    ):
        assert key in text


def test_render_env_backfills_vpn_secrets_from_settings(tmp_path):
    text = installer.render_env(tmp_path, SAMPLE_DRIVE, _settings_with_gluetun()).read_text()
    assert "WIREGUARD_PRIVATE_KEY=PRIVKEY" in text


# ---------------------------------------------------------------------------
# render_env
# ---------------------------------------------------------------------------


def test_render_env_creates_file(tmp_path):
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    assert out.exists()
    assert out.name == ".env"


def test_render_env_contains_puid(tmp_path):
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    assert "PUID=501" in out.read_text()


def test_render_env_contains_pgid(tmp_path):
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    assert "PGID=20" in out.read_text()


def test_render_env_contains_tz(tmp_path):
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    assert "TZ=America/Detroit" in out.read_text()


def test_render_env_contains_media_root(tmp_path):
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    assert "MEDIA_ROOT=/Volumes/Ultra" in out.read_text()


def test_render_env_creates_parent_dir(tmp_path):
    nested = tmp_path / "x" / "y"
    out = installer.render_env(nested, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    assert out.exists()


def test_render_env_writes_api_key_placeholders(tmp_path):
    """The .env file must include the API-key keys so the web container can
    pull them from the environment even before the wiring step fills them in."""
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    text = out.read_text()
    for key in ("SONARR_API_KEY=", "RADARR_API_KEY=", "PROWLARR_API_KEY=", "BAZARR_API_KEY="):
        assert key in text, f"{key!r} missing from .env"


def test_render_env_writes_qbittorrent_credentials(tmp_path):
    """The web container reads QBITTORRENT_USERNAME/PASSWORD from the .env."""
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    text = out.read_text()
    assert "QBITTORRENT_USERNAME=admin" in text
    assert "QBITTORRENT_PASSWORD=" in text


def test_render_env_backfills_api_keys_from_settings(tmp_path):
    """When the wiring step has populated api_keys, render_env writes them in."""
    settings = {**SAMPLE_SETTINGS, "api_keys": {"sonarr": "abc123", "radarr": "def456"}}
    out = installer.render_env(tmp_path, SAMPLE_DRIVE, settings)
    text = out.read_text()
    assert "SONARR_API_KEY=abc123" in text
    assert "RADARR_API_KEY=def456" in text


# ---------------------------------------------------------------------------
# prepare_install_dir
# ---------------------------------------------------------------------------


def test_prepare_install_dir_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_DIR", tmp_path / "mediahub")
    result = installer.prepare_install_dir()
    assert result.is_dir()
    assert result == tmp_path / "mediahub"


def test_prepare_install_dir_idempotent(tmp_path, monkeypatch):
    target = tmp_path / "mediahub"
    monkeypatch.setattr(installer, "INSTALL_DIR", target)
    installer.prepare_install_dir()
    installer.prepare_install_dir()  # should not raise
    assert target.is_dir()


# ---------------------------------------------------------------------------
# prepare_media_layout
# ---------------------------------------------------------------------------


def test_prepare_media_layout_creates_subdirs(tmp_path):
    installer.prepare_media_layout(str(tmp_path))
    for sub in (
        "Torrents/Movies",
        "Torrents/TV Shows",
        "Media/Movies",
        "Media/TV Shows",
    ):
        assert (tmp_path / sub).is_dir(), f"{sub} not created"


def test_prepare_media_layout_idempotent(tmp_path):
    installer.prepare_media_layout(str(tmp_path))
    installer.prepare_media_layout(str(tmp_path))  # should not raise


def test_prepare_media_layout_receiver_skips_torrents(tmp_path):
    """Receiver only needs the Media library — no Torrents subtree."""
    installer.prepare_media_layout(str(tmp_path), include_torrents=False)
    assert (tmp_path / "Media/Movies").is_dir()
    assert (tmp_path / "Media/TV Shows").is_dir()
    assert not (tmp_path / "Torrents").exists()


# ---------------------------------------------------------------------------
# install_status (idle)
# ---------------------------------------------------------------------------


def test_install_status_shape():
    status = installer.install_status()
    assert "status" in status
    assert "log_lines" in status
    assert "services" in status
    assert "progress" in status
    assert set(status["services"].keys()) == {"sonarr", "radarr", "prowlarr", "qbittorrent"}


# ---------------------------------------------------------------------------
# start_install (mocked — no real docker)
# ---------------------------------------------------------------------------


def _reset_install_state():
    """Reset module-level install state between tests."""
    with installer._lock:
        from collections import deque

        installer._install_state.update(
            {
                "status": "idle",
                "log_lines": deque(maxlen=500),
                "services": {
                    "sonarr": "pending",
                    "radarr": "pending",
                    "prowlarr": "pending",
                    "qbittorrent": "pending",
                },
                "started_at": None,
                "finished_at": None,
                "error": None,
                "compose_path": None,
                "env_path": None,
            }
        )


@pytest.fixture(autouse=True)
def reset_state():
    _reset_install_state()
    yield
    _reset_install_state()


def test_start_install_returns_true_on_first_call(tmp_path):
    event = threading.Event()

    def fake_run(install_dir, settings):
        event.wait(timeout=2)

    with patch.object(installer, "_run_install", side_effect=fake_run):
        result = installer.start_install(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
    assert result is True
    event.set()


def test_start_install_sets_status_running(tmp_path):
    event = threading.Event()

    def fake_run(install_dir, settings):
        event.wait(timeout=2)

    with patch.object(installer, "_run_install", side_effect=fake_run):
        installer.start_install(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)

    status = installer.install_status()
    assert status["status"] == "running"
    event.set()


def test_start_install_idempotent_while_running(tmp_path):
    event = threading.Event()

    def fake_run(install_dir, settings):
        event.wait(timeout=2)

    with patch.object(installer, "_run_install", side_effect=fake_run):
        first = installer.start_install(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)
        second = installer.start_install(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)

    assert first is True
    assert second is False
    event.set()


def test_start_install_records_compose_and_env_paths(tmp_path):
    event = threading.Event()

    def fake_run(install_dir, settings):
        event.wait(timeout=2)

    with patch.object(installer, "_run_install", side_effect=fake_run):
        installer.start_install(tmp_path, SAMPLE_DRIVE, SAMPLE_SETTINGS)

    status = installer.install_status()
    assert status["compose_path"] == str(tmp_path / "docker-compose.yml")
    assert status["env_path"] == str(tmp_path / ".env")
    event.set()
