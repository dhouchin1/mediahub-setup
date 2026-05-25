"""Unit tests for mediahub_setup.jellyseerr_client.

All network calls are mocked. No real Jellyseerr instance is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from mediahub_setup.jellyseerr_client import JellyseerrClient

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


def test_jellyseerr_client_init_sets_base_url():
    """JellyseerrClient must store base_url with trailing slash stripped."""
    client = JellyseerrClient("http://localhost:5055/")
    assert client.base_url == "http://localhost:5055"


# ---------------------------------------------------------------------------
# wait_until_ready — timeout path
# ---------------------------------------------------------------------------


def test_wait_until_ready_raises_on_timeout():
    """wait_until_ready must raise RuntimeError when Jellyseerr never responds."""
    client = JellyseerrClient("http://localhost:5055")
    with patch.object(
        client._session,
        "get",
        side_effect=requests.ConnectionError("refused"),
    ):
        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Jellyseerr"):
                client.wait_until_ready(timeout=1)


# ---------------------------------------------------------------------------
# wait_until_ready — success path
# ---------------------------------------------------------------------------


def test_wait_until_ready_returns_on_success():
    """wait_until_ready must return the status dict when Jellyseerr responds."""
    client = JellyseerrClient("http://localhost:5055")
    body = {"version": "1.7.0", "commitTag": "HEAD", "updateAvailable": False}
    with patch.object(client._session, "get", return_value=_ok_response(body)):
        result = client.wait_until_ready(timeout=10)
    assert result == body
