"""Tests for mediahub_setup.routes.repair.

Uses the Flask test client. Docker calls are mocked to False so no daemon
is required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mediahub_setup import state
from mediahub_setup.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Flask test client with clean state and Docker stubbed to unavailable."""
    state.clear()
    app = create_app()
    with patch("mediahub_setup.docker_ops.docker_available", return_value=False):
        yield app.test_client()
    state.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_repair_index_with_no_state_recommends_welcome(client):
    """Repair index with empty state must recommend the welcome step."""
    r = client.get("/repair/")
    assert r.status_code == 200
    body = r.data.decode()
    # The template renders the next_endpoint; without state it should point to welcome
    assert "welcome" in body.lower() or "fresh install" in body.lower() or "start" in body.lower()


def test_repair_index_with_only_drive_recommends_settings(client):
    """Repair index with drive but no settings must recommend the settings step."""
    state.set(
        "drive",
        {
            "name": "TestDrive",
            "mount_path": "/Volumes/TestDrive",
            "filesystem": "apfs",
            "free_bytes": 1_000_000_000,
            "total_bytes": 2_000_000_000,
            "free_gb": 1.0,
            "total_gb": 2.0,
            "writable": True,
        },
    )
    r = client.get("/repair/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "settings" in body.lower()


def test_repair_index_with_full_state_recommends_dashboard(tmp_path):
    """Repair index with complete state (and running containers) recommends dashboard."""
    state.clear()
    # Create a real compose file so compose_exists passes
    install_dir = tmp_path / "mediahub"
    install_dir.mkdir()
    (install_dir / "docker-compose.yml").touch()

    task_names = [
        "Connect to qBittorrent",
        "Change qBittorrent password",
        "Create qBittorrent category: movies",
        "Create qBittorrent category: tv",
        "Read Sonarr API key",
        "Read Radarr API key",
        "Read Prowlarr API key",
        "Register Sonarr in Prowlarr",
        "Register Radarr in Prowlarr",
        "Add qBittorrent to Sonarr",
        "Add root folder to Sonarr (/data/media/tv)",
        "Enable hardlinks in Sonarr",
        "Add qBittorrent to Radarr",
        "Add root folder to Radarr (/data/media/movies)",
        "Enable hardlinks in Radarr",
    ]
    state.update(
        drive={
            "name": "X",
            "mount_path": "/Volumes/X",
            "filesystem": "apfs",
            "free_bytes": 0,
            "total_bytes": 0,
            "free_gb": 0.0,
            "total_gb": 0.0,
            "writable": True,
        },
        settings={
            "tz": "UTC",
            "puid": 1000,
            "pgid": 1000,
            "ports": {
                "sonarr": 8989,
                "radarr": 7878,
                "prowlarr": 9696,
                "qbittorrent_web": 8080,
                "qbittorrent_bt": 6881,
            },
            "shared_password": "TestPassword1234",
            "enabled_services": [],
        },
        install={"compose_path": str(install_dir / "docker-compose.yml")},
        wiring={
            "status": "complete",
            "tasks": [{"name": t, "status": "ok", "message": ""} for t in task_names],
            "api_keys": {},
            "qb_credentials": {"username": "admin", "password": "TestPassword1234"},
        },
    )

    import mediahub_setup.installer as installer_mod

    app = create_app()
    with (
        patch("mediahub_setup.docker_ops.docker_available", return_value=True),
        patch(
            "mediahub_setup.docker_ops.list_containers",
            return_value=[{"name": "mediahub-sonarr", "state": "running"}],
        ),
        patch.object(installer_mod, "INSTALL_DIR", install_dir),
    ):
        r = app.test_client().get("/repair/")

    state.clear()
    assert r.status_code == 200
    body = r.data.decode()
    assert "dashboard" in body.lower()


def test_repair_clear_wipes_state(client):
    """POST /repair/clear must wipe wizard state and redirect to welcome."""
    state.update(drive={"name": "X"}, settings={"foo": "bar"})
    r = client.post("/repair/clear")
    assert r.status_code == 303
    assert state.snapshot() == {}


def test_repair_rerun_wiring_redirects_to_wiring(client):
    """POST /repair/rerun-wiring must redirect to the wiring page."""
    with patch("mediahub_setup.wiring_runner.start_wiring"):
        r = client.post("/repair/rerun-wiring")
    assert r.status_code == 303
    assert "/wiring" in r.headers.get("Location", "")
