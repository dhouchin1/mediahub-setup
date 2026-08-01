"""Unit tests for mediahub_setup.syncthing_client.

All network and subprocess calls are mocked. No real Syncthing instance or
Docker daemon is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from mediahub_setup.syncthing_client import (
    _RECEIVEONLY_DEFAULT_VERSIONING,
    SyncthingClient,
    read_syncthing_apikey,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(body: object) -> MagicMock:
    """Build a mock 200 requests.Response with a JSON body."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    return resp


def _proc(returncode: int = 0, stdout: str = "") -> MagicMock:
    """Build a mock subprocess.CompletedProcess."""
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = ""
    return p


_SAMPLE_CONFIG_XML = (
    "<configuration>"
    '<gui enabled="true">'
    "<address>0.0.0.0:8384</address>"
    "<apikey>TESTKEY123</apikey>"
    "</gui>"
    "</configuration>"
)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def test_syncthing_client_init_strips_trailing_slash():
    """SyncthingClient must store base_url with trailing slash stripped."""
    client = SyncthingClient("http://localhost:8384/", api_key=None)
    assert client.base_url == "http://localhost:8384"


def test_syncthing_client_init_sets_api_key_header():
    """SyncthingClient must set X-API-Key session header when api_key is given."""
    client = SyncthingClient("http://localhost:8384", api_key="mysecretkey")
    assert client._session.headers["X-API-Key"] == "mysecretkey"


def test_syncthing_client_init_no_header_when_api_key_none():
    """SyncthingClient must not set X-API-Key when api_key is None."""
    client = SyncthingClient("http://localhost:8384", api_key=None)
    assert "X-API-Key" not in client._session.headers


# ---------------------------------------------------------------------------
# read_syncthing_apikey — success path
# ---------------------------------------------------------------------------


def test_read_syncthing_apikey_parses_key_from_xml():
    """read_syncthing_apikey must return the key from a valid config.xml."""
    with patch(
        "mediahub_setup.syncthing_client.subprocess.run",
        return_value=_proc(returncode=0, stdout=_SAMPLE_CONFIG_XML),
    ):
        key = read_syncthing_apikey("mediahub-syncthing", timeout=10)
    assert key == "TESTKEY123"


# ---------------------------------------------------------------------------
# read_syncthing_apikey — retry then success
# ---------------------------------------------------------------------------


def test_read_syncthing_apikey_retries_then_succeeds():
    """read_syncthing_apikey must retry when the first call fails and succeed
    when a subsequent call returns a valid config.xml."""
    fail_proc = _proc(returncode=1, stdout="")
    ok_proc = _proc(returncode=0, stdout=_SAMPLE_CONFIG_XML)

    with patch(
        "mediahub_setup.syncthing_client.subprocess.run",
        side_effect=[fail_proc, ok_proc],
    ):
        with patch("mediahub_setup.syncthing_client.time.sleep"):
            key = read_syncthing_apikey("mediahub-syncthing", timeout=30)
    assert key == "TESTKEY123"


# ---------------------------------------------------------------------------
# read_syncthing_apikey — timeout path
# ---------------------------------------------------------------------------


def test_read_syncthing_apikey_raises_on_timeout():
    """read_syncthing_apikey must raise RuntimeError when the deadline passes."""
    with patch(
        "mediahub_setup.syncthing_client.subprocess.run",
        return_value=_proc(returncode=1, stdout=""),
    ):
        with patch("mediahub_setup.syncthing_client.time.sleep"):
            with pytest.raises(RuntimeError, match="Could not read Syncthing API key"):
                read_syncthing_apikey("mediahub-syncthing", timeout=1)


# ---------------------------------------------------------------------------
# wait_until_ready — success path
# ---------------------------------------------------------------------------


def test_wait_until_ready_returns_on_success():
    """wait_until_ready must return a dict when ping succeeds."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    with patch.object(client._session, "get", return_value=_ok_response({"ping": "pong"})):
        result = client.wait_until_ready(timeout=10)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# wait_until_ready — timeout path
# ---------------------------------------------------------------------------


def test_wait_until_ready_raises_on_timeout():
    """wait_until_ready must raise RuntimeError when Syncthing never responds."""
    client = SyncthingClient("http://localhost:8384", api_key=None)
    with patch.object(
        client._session,
        "get",
        side_effect=requests.ConnectionError("refused"),
    ):
        with patch("mediahub_setup.syncthing_client.time.sleep"):
            with pytest.raises(RuntimeError, match="Syncthing"):
                client.wait_until_ready(timeout=1)


# ---------------------------------------------------------------------------
# my_device_id
# ---------------------------------------------------------------------------


def test_my_device_id_reads_myid_from_status():
    """my_device_id must return the myID field from /rest/system/status."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    expected_id = "ABCDEF1-ABCDEF1-ABCDEF1-ABCDEF1-ABCDEF1-ABCDEF1-ABCDEF1-ABCDEF1"
    with patch.object(
        client._session,
        "get",
        return_value=_ok_response({"myID": expected_id, "uptime": 42}),
    ) as mock_get:
        result = client.my_device_id()

    assert result == expected_id
    call_url = mock_get.call_args[0][0]
    assert call_url.endswith("/rest/system/status")


# ---------------------------------------------------------------------------
# add_device
# ---------------------------------------------------------------------------


def test_add_device_puts_correct_body():
    """add_device must PUT the correct body to /rest/config/devices/{device_id}."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    device_id = "PEER111-PEER111-PEER111-PEER111-PEER111-PEER111-PEER111-PEER111"
    mock_put = MagicMock(return_value=_ok_response({}))

    with patch.object(client._session, "put", mock_put):
        client.add_device(device_id, name="my-peer", introducer=False, auto_accept=True)

    mock_put.assert_called_once()
    call_url = mock_put.call_args[0][0]
    assert call_url.endswith(f"/rest/config/devices/{device_id}")

    body = mock_put.call_args[1]["json"]
    assert body["deviceID"] == device_id
    assert body["name"] == "my-peer"
    assert body["addresses"] == ["dynamic"]
    assert body["introducer"] is False
    assert body["autoAcceptFolders"] is True


# ---------------------------------------------------------------------------
# set_folder — receiveonly MUST have staggered versioning
# ---------------------------------------------------------------------------


def test_set_folder_receiveonly_has_staggered_versioning():
    """set_folder with folder_type='receiveonly' must always attach staggered
    versioning with maxAge=0, protecting local files from remote deletions."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    folder_id = "media-lib"
    device_ids = ["DEVID001-DEVID001-DEVID001-DEVID001-DEVID001-DEVID001-DEVID001-DEVID001"]
    mock_put = MagicMock(return_value=_ok_response({}))

    with patch.object(client._session, "put", mock_put):
        client.set_folder(
            folder_id=folder_id,
            label="Media Library",
            path="/data/Media",
            folder_type="receiveonly",
            device_ids=device_ids,
        )

    mock_put.assert_called_once()
    call_url = mock_put.call_args[0][0]
    assert call_url.endswith(f"/rest/config/folders/{folder_id}")

    body = mock_put.call_args[1]["json"]
    assert body["type"] == "receiveonly"
    assert body["path"] == "/data/Media"
    assert body["versioning"] == _RECEIVEONLY_DEFAULT_VERSIONING
    assert body["versioning"]["type"] == "staggered"
    assert body["versioning"]["params"]["maxAge"] == "0"
    assert body["versioning"]["cleanupIntervalS"] == 3600

    # Devices list must contain the given device IDs
    device_id_values = [d["deviceID"] for d in body["devices"]]
    assert device_ids[0] in device_id_values


# ---------------------------------------------------------------------------
# set_folder — sendonly must NOT have versioning
# ---------------------------------------------------------------------------


def test_set_folder_sendonly_has_no_versioning():
    """set_folder with folder_type='sendonly' must NOT include a versioning key
    (the authoritative source should not accumulate stale versions)."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    mock_put = MagicMock(return_value=_ok_response({}))

    with patch.object(client._session, "put", mock_put):
        client.set_folder(
            folder_id="seed-lib",
            label="Seed Library",
            path="/downloads/complete",
            folder_type="sendonly",
            device_ids=["DEVID002-DEVID002-DEVID002-DEVID002-DEVID002-DEVID002-DEVID002-DEVID002"],
        )

    body = mock_put.call_args[1]["json"]
    assert body["type"] == "sendonly"
    assert "versioning" not in body


# ---------------------------------------------------------------------------
# set_folder — receiveonly with explicit versioning override
# ---------------------------------------------------------------------------


def test_set_folder_receiveonly_respects_explicit_versioning():
    """set_folder with folder_type='receiveonly' and explicit versioning must
    use the provided versioning dict rather than the default."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    custom_versioning = {"type": "simple", "params": {"keep": "5"}, "cleanupIntervalS": 3600}
    mock_put = MagicMock(return_value=_ok_response({}))

    with patch.object(client._session, "put", mock_put):
        client.set_folder(
            folder_id="media-lib",
            label="Media Library",
            path="/data/Media",
            folder_type="receiveonly",
            device_ids=[],
            versioning=custom_versioning,
        )

    body = mock_put.call_args[1]["json"]
    assert body["versioning"] == custom_versioning


def test_set_folder_receiveonly_empty_versioning_gets_default():
    """An empty-dict versioning is falsy and must NOT bypass the safety
    default — otherwise a receive-only folder ends up with no versioning and
    remote deletions destroy the local copy instead of parking in .stversions."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    mock_put = MagicMock(return_value=_ok_response({}))

    with patch.object(client._session, "put", mock_put):
        client.set_folder(
            folder_id="media-lib",
            label="Media Library",
            path="/data/Media",
            folder_type="receiveonly",
            device_ids=[],
            versioning={},
        )

    body = mock_put.call_args[1]["json"]
    assert body["versioning"] == _RECEIVEONLY_DEFAULT_VERSIONING


# ---------------------------------------------------------------------------
# share_folder_with — idempotent
# ---------------------------------------------------------------------------


def test_share_folder_with_adds_device_when_absent():
    """share_folder_with must PUT an updated folder config with the new device
    appended when it is not already in the devices list."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    folder_id = "media-lib"
    existing_device = "EXIST001-EXIST001-EXIST001-EXIST001-EXIST001-EXIST001-EXIST001-EXIST001"
    new_device = "NEW00001-NEW00001-NEW00001-NEW00001-NEW00001-NEW00001-NEW00001-NEW00001"

    existing_folder_cfg = {
        "id": folder_id,
        "label": "Media Library",
        "path": "/data/Media",
        "type": "receiveonly",
        "devices": [{"deviceID": existing_device}],
    }
    mock_get = MagicMock(return_value=_ok_response(existing_folder_cfg))
    mock_put = MagicMock(return_value=_ok_response({}))

    with patch.object(client._session, "get", mock_get):
        with patch.object(client._session, "put", mock_put):
            client.share_folder_with(folder_id, new_device)

    mock_put.assert_called_once()
    put_body = mock_put.call_args[1]["json"]
    device_ids_in_body = [d["deviceID"] for d in put_body["devices"]]
    assert existing_device in device_ids_in_body
    assert new_device in device_ids_in_body


def test_share_folder_with_is_idempotent_when_device_already_present():
    """share_folder_with must NOT PUT when the device is already in the list."""
    client = SyncthingClient("http://localhost:8384", api_key="k")
    folder_id = "media-lib"
    device_id = "EXIST001-EXIST001-EXIST001-EXIST001-EXIST001-EXIST001-EXIST001-EXIST001"

    existing_folder_cfg = {
        "id": folder_id,
        "devices": [{"deviceID": device_id}],
    }
    mock_get = MagicMock(return_value=_ok_response(existing_folder_cfg))
    mock_put = MagicMock(return_value=_ok_response({}))

    with patch.object(client._session, "get", mock_get):
        with patch.object(client._session, "put", mock_put):
            client.share_folder_with(folder_id, device_id)

    mock_put.assert_not_called()
