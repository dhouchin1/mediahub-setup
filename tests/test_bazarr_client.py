"""Unit tests for mediahub_setup.bazarr_client.

All network and subprocess calls are mocked. No real Bazarr instance is
required.
"""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest
import requests

from mediahub_setup.bazarr_client import BazarrClient, read_bazarr_api_key

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
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = ""
    return p


_SAMPLE_CONFIG_INI = textwrap.dedent(
    """\
    [auth]
    apikey = bazarr_api_key_xyz_123
    type = form

    [general]
    ip = 0.0.0.0
    """
)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def test_bazarr_client_init_sets_base_url():
    """BazarrClient must store base_url with trailing slash stripped."""
    client = BazarrClient("http://localhost:6767/", api_key=None)
    assert client.base_url == "http://localhost:6767"


# ---------------------------------------------------------------------------
# wait_until_ready — timeout path
# ---------------------------------------------------------------------------


def test_wait_until_ready_raises_on_timeout():
    """wait_until_ready must raise RuntimeError when Bazarr never responds."""
    client = BazarrClient("http://localhost:6767", api_key=None)
    with patch.object(
        client._session,
        "get",
        side_effect=requests.ConnectionError("refused"),
    ):
        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Bazarr"):
                client.wait_until_ready(timeout=1)


# ---------------------------------------------------------------------------
# wait_until_ready — success path
# ---------------------------------------------------------------------------


def test_wait_until_ready_returns_on_success():
    """wait_until_ready must return a dict when Bazarr responds."""
    client = BazarrClient("http://localhost:6767", api_key="somekey")
    body = {"data": {"bazarr_version": "1.2.3"}}
    with patch.object(client._session, "get", return_value=_ok_response(body)):
        result = client.wait_until_ready(timeout=10)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# read_bazarr_api_key
# ---------------------------------------------------------------------------


def test_read_bazarr_api_key_finds_key_in_ini():
    """read_bazarr_api_key must parse the API key from a valid config.ini."""
    with patch(
        "subprocess.run",
        return_value=_proc(returncode=0, stdout=_SAMPLE_CONFIG_INI),
    ):
        key = read_bazarr_api_key("mediahub-bazarr", timeout=10)
    assert key == "bazarr_api_key_xyz_123"


# ---------------------------------------------------------------------------
# set_sonarr
# ---------------------------------------------------------------------------


def test_set_sonarr_posts_correct_payload():
    """set_sonarr must POST a payload that includes sonarr ip, port, and api key."""
    client = BazarrClient("http://localhost:6767", api_key="bazarrkey")
    mock_post = MagicMock(return_value=_ok_response({}))
    with patch.object(client._session, "post", mock_post):
        client.set_sonarr(sonarr_url="http://sonarr:8989", api_key="sonarrkey123")

    mock_post.assert_called_once()
    payload = mock_post.call_args[1]["json"]
    assert payload["sonarr"]["ip"] == "sonarr"
    assert payload["sonarr"]["port"] == 8989
    assert payload["sonarr"]["apikey"] == "sonarrkey123"
    assert payload["general"]["use_sonarr"] is True
