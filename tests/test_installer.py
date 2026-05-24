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


def test_render_compose_creates_parent_dir(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    out = installer.render_compose(nested, SAMPLE_SETTINGS)
    assert out.exists()


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
    for sub in ("torrents/movies", "torrents/tv", "media/movies", "media/tv"):
        assert (tmp_path / sub).is_dir(), f"{sub} not created"


def test_prepare_media_layout_idempotent(tmp_path):
    installer.prepare_media_layout(str(tmp_path))
    installer.prepare_media_layout(str(tmp_path))  # should not raise


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
