"""Unit tests for mediahub_setup.jellyfin_client.

All network calls are mocked. No real Jellyfin instance is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from mediahub_setup.jellyfin_client import JellyfinClient

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


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def test_jellyfin_client_init_sets_base_url():
    """JellyfinClient must store base_url with trailing slash stripped."""
    client = JellyfinClient("http://localhost:8096/")
    assert client.base_url == "http://localhost:8096"


# ---------------------------------------------------------------------------
# wait_until_ready — timeout path
# ---------------------------------------------------------------------------


def test_wait_until_ready_raises_on_timeout():
    """wait_until_ready must raise RuntimeError when Jellyfin never responds."""
    client = JellyfinClient("http://localhost:8096")
    with patch.object(
        client._session,
        "get",
        side_effect=requests.ConnectionError("refused"),
    ):
        with patch("time.sleep"):  # skip actual sleeping
            with pytest.raises(RuntimeError, match="Jellyfin"):
                client.wait_until_ready(timeout=1)


# ---------------------------------------------------------------------------
# wait_until_ready — success path
# ---------------------------------------------------------------------------


def test_wait_until_ready_returns_on_success():
    """wait_until_ready must return the public-info dict when Jellyfin responds."""
    client = JellyfinClient("http://localhost:8096")
    info = {"ServerName": "TestServer", "Version": "10.8.0", "Id": "abc123"}
    with patch.object(client._session, "get", return_value=_ok_response(info)):
        result = client.wait_until_ready(timeout=10)
    assert result == info
