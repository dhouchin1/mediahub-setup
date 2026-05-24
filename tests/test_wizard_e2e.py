"""End-to-end wizard smoke test.

Walks every page in order through the Flask test client, simulating
the state writes that each step would do, then asserts the next step
can consume that state. This is the test that would have caught the
drive["mount"] vs drive["mount_path"] contract drift between parallel
agents.

The test does NOT actually run docker compose or hit any *arr APIs —
it only verifies that every route renders, the state shape contracts
match across step boundaries, and the redirect graph is consistent.
"""

from __future__ import annotations

import pytest

from mediahub_setup import state
from mediahub_setup.app import create_app


@pytest.fixture
def client():
    state.clear()
    app = create_app()
    yield app.test_client()
    state.clear()


def test_welcome_renders(client):
    r = client.get("/")
    assert r.status_code == 200


def test_preflight_renders_and_rerun_is_partial(client):
    r = client.get("/preflight/")
    assert r.status_code == 200
    rerun = client.post("/preflight/rerun")
    assert rerun.status_code == 200
    # Partial should not include the full HTML shell
    assert b"<html" not in rerun.data
    # Should still mention at least one check
    assert b"Docker" in rerun.data


def test_drive_picker_renders_with_no_drives(client):
    r = client.get("/drive/")
    assert r.status_code == 200
    refresh = client.post("/drive/refresh")
    assert refresh.status_code == 200
    assert b"<html" not in refresh.data


def test_settings_uses_drive_state_contract(client):
    # Simulate the user picking a drive — matches the exact shape
    # mediahub_setup/routes/drive.py:pick writes to state.
    state.set(
        "drive",
        {
            "name": "MediaHub",
            "mount_path": "/Volumes/MediaHub",
            "filesystem": "apfs",
            "free_bytes": 2_000_000_000_000,
            "total_bytes": 4_000_000_000_000,
            "free_gb": 2000.0,
            "total_gb": 4000.0,
            "writable": True,
        },
    )

    r = client.get("/settings/")
    assert r.status_code == 200

    r = client.post(
        "/settings/",
        data={"tz": "America/Detroit", "puid": "501", "pgid": "20", "auto_passwords": "on"},
    )
    assert r.status_code == 303
    assert "/install" in r.headers.get("Location", "")

    s = state.get("settings")
    assert s is not None
    assert s["tz"] == "America/Detroit"
    assert s["ports"]["sonarr"] == 8989
    assert s["puid"] == 501
    assert s["shared_password"] and len(s["shared_password"]) == 16


def test_install_consumes_drive_and_settings_state(client):
    """Regression: drive writes mount_path; install must read mount_path
    (not 'mount'). This is the cross-agent contract that broke once."""
    state.update(
        drive={
            "name": "X",
            "mount_path": "/Volumes/MediaHub",
            "filesystem": "apfs",
            "free_bytes": 0,
            "total_bytes": 0,
            "free_gb": 0,
            "total_gb": 0,
            "writable": True,
        },
        settings={
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
            "auto_passwords": True,
            "shared_password": "TestPass1234abcd",
        },
    )

    r = client.get("/install/")
    assert r.status_code == 200, r.data[:200]

    # The HTMX status partial must also render with this state shape.
    r = client.get("/install/status")
    assert r.status_code == 200


def test_install_redirects_back_if_drive_missing(client):
    """Guard: without upstream state, install bounces back."""
    r = client.get("/install/")
    assert r.status_code in (302, 303)
    assert "/drive" in r.headers.get("Location", "")


def test_install_redirects_back_if_settings_missing(client):
    state.set(
        "drive",
        {
            "name": "X",
            "mount_path": "/tmp/x",
            "writable": True,
            "free_bytes": 0,
            "total_bytes": 0,
            "filesystem": "apfs",
            "free_gb": 0,
            "total_gb": 0,
        },
    )
    r = client.get("/install/")
    assert r.status_code in (302, 303)
    assert "/settings" in r.headers.get("Location", "")


def test_wiring_renders(client):
    r = client.get("/wiring/")
    assert r.status_code == 200
    r = client.get("/wiring/status")
    assert r.status_code == 200


def test_done_renders_with_full_state(client):
    """All four service URLs + the shared password should land on the
    done page when the upstream steps populated state."""
    state.update(
        settings={
            "ports": {
                "sonarr": 8989,
                "radarr": 7878,
                "prowlarr": 9696,
                "qbittorrent_web": 8080,
                "qbittorrent_bt": 6881,
            },
            "shared_password": "UniqueP4sswordXYZ",
        },
        drive={"name": "X", "mount_path": "/Volumes/MediaHub"},
        install={"compose_path": "/Users/x/mediahub/docker-compose.yml"},
        wiring={
            "status": "complete",
            "api_keys": {"sonarr": "k1", "radarr": "k2", "prowlarr": "k3"},
            "qb_credentials": {"username": "admin", "password": "UniqueP4sswordXYZ"},
        },
    )
    r = client.get("/done/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "localhost:8989" in body
    assert "localhost:7878" in body
    assert "localhost:9696" in body
    assert "localhost:8080" in body
    assert "UniqueP4sswordXYZ" in body


def test_done_renders_with_empty_state(client):
    """Tolerates missing keys (e.g. user navigates here directly)."""
    r = client.get("/done/")
    assert r.status_code == 200


def test_reset_clears_all_state(client):
    state.update(drive={"x": 1}, settings={"y": 2})
    r = client.post("/done/reset")
    assert r.status_code == 303
    assert state.get("drive") is None
    assert state.get("settings") is None
