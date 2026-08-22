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


def test_welcome_offers_all_three_roles(client):
    body = client.get("/").data.decode()
    assert "All-in-one" in body
    assert "Remote seedbox" in body
    assert "Home receiver" in body


def test_choose_role_persists_and_advances_to_preflight(client):
    r = client.post("/role", data={"role": "seedbox"})
    assert r.status_code == 303
    assert "/preflight" in r.headers["Location"]
    assert state.get("role") == "seedbox"


def test_receiver_skips_wiring_step(client):
    """The receiver has no *arr to wire, so /wiring/ redirects to Done."""
    state.set("role", "receiver")
    r = client.get("/wiring/")
    assert r.status_code in (301, 302, 303, 308)
    assert "/done" in r.headers["Location"]


def test_receiver_settings_show_syncthing_and_hide_qbittorrent(client):
    state.set("role", "receiver")
    body = client.get("/settings/").data.decode()
    assert "Syncthing library sync" in body
    assert "qBittorrent username" not in body


def test_seedbox_settings_force_enables_syncthing(client):
    """Submitting settings as a seedbox always enables Syncthing."""
    state.set("role", "seedbox")
    r = client.post("/settings/", data={"tz": "UTC", "puid": "501", "pgid": "20"})
    assert r.status_code in (302, 303)
    saved = state.get("settings") or {}
    assert "syncthing" in (saved.get("enabled_services") or [])
    assert saved.get("role") == "seedbox"


def test_done_renders_seedbox_syncthing_device_id(client):
    state.set("role", "seedbox")
    state.set("settings", {"role": "seedbox", "ports": {}, "enabled_services": ["syncthing"]})
    state.set(
        "wiring",
        {
            "status": "complete",
            "syncthing": {
                "device_id": "ABCDEFG-HIJKLMN",
                "folder_id": "mediahub-media",
                "folder_type": "sendonly",
            },
        },
    )
    r = client.get("/done/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Syncthing" in body
    assert "ABCDEFG-HIJKLMN" in body  # this node's device ID is surfaced


def test_done_renders_receiver_versioning_warning(client):
    state.set("role", "receiver")
    state.set("settings", {"role": "receiver", "ports": {}, "enabled_services": ["syncthing"]})
    state.set(
        "wiring",
        {
            "status": "complete",
            "syncthing": {
                "device_id": "XYZ1234-RECEIVER",
                "folder_id": "mediahub-media",
                "folder_type": "receiveonly",
            },
        },
    )
    r = client.get("/done/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "versioning" in body.lower()  # the P0 deletion-safety warning
    assert "Add your first movie" not in body  # no *arr CTA on a receiver


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


def test_settings_rerender_json_escapes_alpine_strings(client):
    """Regression: values echoed back into Alpine ``x-data`` JS string
    literals on the 422 re-render must be JSON-encoded. HTML entity
    escaping alone is not enough — the browser decodes ``&#39;`` back to
    ``'`` before Alpine evaluates the attribute as JavaScript, so a quote
    in the shared password (or caddy mode) broke out of the string."""
    state.set("role", "all-in-one")
    r = client.post(
        "/settings/",
        data={"tz": "", "shared_password": "x'+alert(1)+'x", "caddy_mode": "loc'al"},
    )
    assert r.status_code == 422
    body = r.data.decode()
    # Flask's tojson escapes quotes to \u0027, so the value never contains a
    # raw quote the browser could decode into a JS string terminator.
    assert 'sharedPassword: "x\\u0027+alert(1)+\\u0027x"' in body
    assert 'caddyMode: "loc\\u0027al"' in body
    assert "sharedPassword: '" not in body
    assert "&#39;+alert" not in body


def test_install_page_renders_while_install_is_running(client):
    """Regression: once an install has started, /install/ switches to the
    in-progress branch which includes the status partial *with context*.
    That partial reads ``data`` and ``ports`` (the names the /install/status
    poll passes), so the index route must pass them too — otherwise every
    visit after "Start install" raised UndefinedError (HTTP 500)."""
    from unittest.mock import patch

    from mediahub_setup import installer

    state.update(
        drive={"name": "X", "mount_path": "/Volumes/MediaHub", "writable": True},
        settings={"tz": "UTC", "puid": 501, "pgid": 20, "ports": {"sonarr": 8989}},
    )
    running = {
        "status": "running",
        "progress": 50,
        "services": {"sonarr": "starting"},
        "log_lines": ["[install] docker compose up -d …"],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "compose_path": "",
        "env_path": "",
    }
    with patch.object(installer, "install_status", return_value=running):
        r = client.get("/install/")
    assert r.status_code == 200, r.data[:300]
    assert b"Installing" in r.data
    assert b":8989" in r.data


def test_install_status_tolerates_settings_without_ports(client):
    """A persisted settings blob lacking ``ports`` must not turn the 1 s
    HTMX poll into a permanent 500."""
    state.update(
        drive={"name": "X", "mount_path": "/Volumes/MediaHub", "writable": True},
        settings={"tz": "UTC", "puid": 501, "pgid": 20},
    )
    r = client.get("/install/status")
    assert r.status_code == 200
