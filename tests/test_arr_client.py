"""Unit tests for mediahub_setup.arr_client.

All network and subprocess calls are mocked. No real containers or
services are required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from mediahub_setup.arr_client import (
    ArrClient,
    ProwlarrClient,
    QBittorrentClient,
    RadarrClient,
    SonarrClient,
    get_qbittorrent_temp_password,
    read_arr_api_key,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(body: object, status: int = 200) -> MagicMock:
    """Build a mock requests.Response with a JSON body."""
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


def _text_response(text: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    resp.text = text
    resp.json.return_value = {}
    return resp


# ---------------------------------------------------------------------------
# Docker helper tests
# ---------------------------------------------------------------------------


class TestGetQbittorrentTempPassword:
    def test_extracts_password_from_stdout(self):
        proc = MagicMock()
        proc.stdout = "A temporary password is provided for this session: xK9mPqR2\n"
        proc.stderr = ""
        with patch("subprocess.run", return_value=proc):
            pw = get_qbittorrent_temp_password("mediahub-qbittorrent")
        assert pw == "xK9mPqR2"

    def test_extracts_password_from_stderr(self):
        proc = MagicMock()
        proc.stdout = ""
        proc.stderr = "WebUI: temporary password for this session: AbCdEfGh\n"
        with patch("subprocess.run", return_value=proc):
            pw = get_qbittorrent_temp_password("mediahub-qbittorrent")
        assert pw == "AbCdEfGh"

    def test_raises_when_not_found(self):
        proc = MagicMock()
        proc.stdout = "Starting qBittorrent...\n"
        proc.stderr = ""
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(RuntimeError, match="temporary password"):
                get_qbittorrent_temp_password("mediahub-qbittorrent")


class TestReadArrApiKey:
    _XML = """<?xml version="1.0"?>
<Config>
  <ApiKey>deadbeef1234567890abcdef12345678</ApiKey>
  <Port>8989</Port>
</Config>"""

    def _proc(self, returncode: int = 0, stdout: str = "") -> MagicMock:
        p = MagicMock()
        p.returncode = returncode
        p.stdout = stdout
        p.stderr = ""
        return p

    def test_reads_key_from_xml(self):
        with patch("subprocess.run", return_value=self._proc(stdout=self._XML)):
            key = read_arr_api_key("mediahub-sonarr", timeout=5)
        assert key == "deadbeef1234567890abcdef12345678"

    def test_retries_on_nonzero_exit_then_succeeds(self):
        fail = self._proc(returncode=1, stdout="")
        ok = self._proc(returncode=0, stdout=self._XML)
        with patch("subprocess.run", side_effect=[fail, ok]):
            with patch("time.sleep"):  # skip actual sleep
                key = read_arr_api_key("mediahub-sonarr", timeout=10)
        assert key == "deadbeef1234567890abcdef12345678"

    def test_raises_after_timeout(self):
        fail = self._proc(returncode=1)
        with patch("subprocess.run", return_value=fail):
            with patch("time.sleep"):
                with patch("time.monotonic", side_effect=[0, 0, 100]):  # expire immediately
                    with pytest.raises(RuntimeError, match="Could not read API key"):
                        read_arr_api_key("mediahub-sonarr", timeout=5)

    def test_raises_on_missing_api_key_element(self):
        xml = "<Config><Port>8989</Port></Config>"
        with patch("subprocess.run", return_value=self._proc(stdout=xml)):
            with patch("time.sleep"):
                with patch("time.monotonic", side_effect=[0, 0, 100]):
                    with pytest.raises(RuntimeError):
                        read_arr_api_key("mediahub-sonarr", timeout=5)


# ---------------------------------------------------------------------------
# QBittorrentClient tests
# ---------------------------------------------------------------------------


class TestQBittorrentClient:
    def setup_method(self):
        self.qb = QBittorrentClient("http://localhost:8080")

    def test_login_success(self):
        with patch.object(self.qb._session, "post", return_value=_text_response("Ok.")):
            self.qb.login("somepassword")  # should not raise

    def test_login_failure_raises(self):
        with patch.object(self.qb._session, "post", return_value=_text_response("Fails.")):
            with pytest.raises(RuntimeError, match="login failed"):
                self.qb.login("wrongpassword")

    def test_change_password_posts_preferences(self):
        mock_post = MagicMock(return_value=_text_response(""))
        with patch.object(self.qb._session, "post", mock_post):
            self.qb.change_password("newpass")
        assert mock_post.called
        call_args = mock_post.call_args
        assert "setPreferences" in call_args[0][0]

    def test_list_categories_returns_dict(self):
        categories = {"movies": {"savePath": "/data/torrents/movies"}, "tv": {}}
        with patch.object(self.qb._session, "get", return_value=_ok_response(categories)):
            result = self.qb.list_categories()
        assert result == categories

    def test_create_category_skips_if_exists(self):
        existing = {"movies": {"savePath": "/data/torrents/movies"}}
        mock_get = MagicMock(return_value=_ok_response(existing))
        mock_post = MagicMock()
        with patch.object(self.qb._session, "get", mock_get):
            with patch.object(self.qb._session, "post", mock_post):
                self.qb.create_category("movies", "/data/torrents/movies")
        mock_post.assert_not_called()

    def test_create_category_posts_when_absent(self):
        mock_get = MagicMock(return_value=_ok_response({}))
        mock_post = MagicMock(return_value=_text_response(""))
        with patch.object(self.qb._session, "get", mock_get):
            with patch.object(self.qb._session, "post", mock_post):
                self.qb.create_category("tv", "/data/torrents/tv")
        assert mock_post.called
        call_args = mock_post.call_args
        assert "createCategory" in call_args[0][0]

    def test_create_category_idempotent_called_twice(self):
        """Calling create_category twice for the same name only POSTs once."""
        call_count = {"get": 0, "post": 0}

        def mock_get(*a, **kw):
            call_count["get"] += 1
            # After first post, return the category as existing
            cats = {"tv": {}} if call_count["get"] > 1 else {}
            return _ok_response(cats)

        def mock_post(*a, **kw):
            call_count["post"] += 1
            return _text_response("")

        with patch.object(self.qb._session, "get", side_effect=mock_get):
            with patch.object(self.qb._session, "post", side_effect=mock_post):
                self.qb.create_category("tv", "/data/torrents/tv")
                self.qb.create_category("tv", "/data/torrents/tv")

        assert call_count["post"] == 1

    def test_set_listen_port_posts_preferences(self):
        import json

        mock_post = MagicMock(return_value=_text_response(""))
        with patch.object(self.qb._session, "post", mock_post):
            self.qb.set_listen_port(51820)
        assert "setPreferences" in mock_post.call_args[0][0]
        payload = json.loads(mock_post.call_args.kwargs["data"]["json"])
        assert payload["listen_port"] == 51820
        assert payload["random_port"] is False

    def test_share_limits_remove_uses_action_2(self):
        import json

        mock_post = MagicMock(return_value=_text_response(""))
        with patch.object(self.qb._session, "post", mock_post):
            self.qb.set_global_share_limits(
                ratio=2.0, seeding_time_minutes=10080, remove_on_limit=True
            )
        payload = json.loads(mock_post.call_args.kwargs["data"]["json"])
        assert payload["max_ratio"] == 2.0
        assert payload["max_seeding_time"] == 10080
        assert payload["max_ratio_act"] == 2  # remove torrent + delete files

    def test_share_limits_pause_uses_action_0(self):
        import json

        mock_post = MagicMock(return_value=_text_response(""))
        with patch.object(self.qb._session, "post", mock_post):
            self.qb.set_global_share_limits(
                ratio=1.0, seeding_time_minutes=0, remove_on_limit=False
            )
        payload = json.loads(mock_post.call_args.kwargs["data"]["json"])
        assert payload["max_ratio_act"] == 0
        assert payload["max_seeding_time_enabled"] is False


# ---------------------------------------------------------------------------
# ArrClient header auth test
# ---------------------------------------------------------------------------


class TestArrClientAuth:
    def test_x_api_key_header_is_set(self):
        client = ArrClient("http://localhost:8989", api_key="mysecretkey")
        assert client._session.headers["X-Api-Key"] == "mysecretkey"

    def test_get_passes_api_key_header(self):
        client = ArrClient("http://localhost:8989", api_key="testkey123")
        resp = _ok_response({"result": "ok"})
        with patch.object(client._session, "get", return_value=resp) as mock_get:
            client.get("/api/v3/system/status")
        # The session already carries the header; verify get was called
        mock_get.assert_called_once()

    def test_error_response_raises(self):
        client = ArrClient("http://localhost:8989", api_key="testkey")
        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        with patch.object(client._session, "get", return_value=bad_resp):
            with pytest.raises(requests.HTTPError):
                client.get("/api/v3/nonexistent")


# ---------------------------------------------------------------------------
# ProwlarrClient tests
# ---------------------------------------------------------------------------


class TestProwlarrClient:
    def setup_method(self):
        self.prowlarr = ProwlarrClient("http://localhost:9696", api_key="prowlarrkey")

    def test_list_applications_returns_list(self):
        apps = [{"id": 1, "name": "Sonarr"}]
        with patch.object(self.prowlarr._session, "get", return_value=_ok_response(apps)):
            result = self.prowlarr.list_applications()
        assert result == apps

    def test_add_application_skips_if_name_exists(self):
        apps = [{"id": 1, "name": "Sonarr", "implementation": "Sonarr"}]
        mock_get = MagicMock(return_value=_ok_response(apps))
        mock_post = MagicMock()
        with patch.object(self.prowlarr._session, "get", mock_get):
            with patch.object(self.prowlarr._session, "post", mock_post):
                result = self.prowlarr.add_application(
                    name="Sonarr",
                    app_type="Sonarr",
                    sync_categories=[5000],
                    app_url="http://sonarr:8989",
                    prowlarr_url="http://prowlarr:9696",
                    api_key="sonarrkey",
                )
        mock_post.assert_not_called()
        assert result["name"] == "Sonarr"

    def test_add_application_posts_when_absent(self):
        mock_get = MagicMock(return_value=_ok_response([]))
        new_app = {"id": 2, "name": "Radarr"}
        mock_post = MagicMock(return_value=_ok_response(new_app))
        with patch.object(self.prowlarr._session, "get", mock_get):
            with patch.object(self.prowlarr._session, "post", mock_post):
                result = self.prowlarr.add_application(
                    name="Radarr",
                    app_type="Radarr",
                    sync_categories=[2000],
                    app_url="http://radarr:7878",
                    prowlarr_url="http://prowlarr:9696",
                    api_key="radarrkey",
                )
        assert mock_post.called
        assert result["name"] == "Radarr"

    def test_add_sonarr_idempotent(self):
        """Registering Sonarr twice only sends one POST."""
        apps_empty = []
        apps_with_sonarr = [{"id": 1, "name": "Sonarr"}]
        get_calls = {"count": 0}

        def mock_get(*a, **kw):
            get_calls["count"] += 1
            if get_calls["count"] == 1:
                return _ok_response(apps_empty)
            return _ok_response(apps_with_sonarr)

        mock_post = MagicMock(return_value=_ok_response({"id": 1, "name": "Sonarr"}))
        with patch.object(self.prowlarr._session, "get", side_effect=mock_get):
            with patch.object(self.prowlarr._session, "post", mock_post):
                self.prowlarr.add_sonarr(
                    sonarr_url="http://sonarr:8989",
                    prowlarr_url="http://prowlarr:9696",
                    sonarr_api_key="key1",
                )
                self.prowlarr.add_sonarr(
                    sonarr_url="http://sonarr:8989",
                    prowlarr_url="http://prowlarr:9696",
                    sonarr_api_key="key1",
                )
        assert mock_post.call_count == 1

    def test_add_application_payload_contains_api_key_field(self):
        mock_get = MagicMock(return_value=_ok_response([]))
        mock_post = MagicMock(return_value=_ok_response({"id": 1, "name": "Sonarr"}))
        with patch.object(self.prowlarr._session, "get", mock_get):
            with patch.object(self.prowlarr._session, "post", mock_post):
                self.prowlarr.add_sonarr(
                    sonarr_url="http://sonarr:8989",
                    prowlarr_url="http://prowlarr:9696",
                    sonarr_api_key="supersecretkey",
                )
        payload = mock_post.call_args[1]["json"]
        field_names = [f["name"] for f in payload["fields"]]
        field_values = {f["name"]: f["value"] for f in payload["fields"]}
        assert "apiKey" in field_names
        assert field_values["apiKey"] == "supersecretkey"


# ---------------------------------------------------------------------------
# SonarrClient tests
# ---------------------------------------------------------------------------


class TestSonarrClient:
    def setup_method(self):
        self.sonarr = SonarrClient("http://localhost:8989", api_key="sonarrkey")

    def test_add_root_folder_skips_if_exists(self):
        folders = [{"id": 1, "path": "/data/media/tv"}]
        mock_get = MagicMock(return_value=_ok_response(folders))
        mock_post = MagicMock()
        with patch.object(self.sonarr._session, "get", mock_get):
            with patch.object(self.sonarr._session, "post", mock_post):
                self.sonarr.add_root_folder("/data/media/tv")
        mock_post.assert_not_called()

    def test_add_root_folder_posts_when_absent(self):
        mock_get = MagicMock(return_value=_ok_response([]))
        new_folder = {"id": 1, "path": "/data/media/tv"}
        mock_post = MagicMock(return_value=_ok_response(new_folder))
        with patch.object(self.sonarr._session, "get", mock_get):
            with patch.object(self.sonarr._session, "post", mock_post):
                result = self.sonarr.add_root_folder("/data/media/tv")
        mock_post.assert_called_once()
        assert result["path"] == "/data/media/tv"

    def test_add_qbittorrent_skips_if_exists(self):
        clients = [{"id": 1, "implementation": "qBittorrent", "name": "qBittorrent"}]
        mock_get = MagicMock(return_value=_ok_response(clients))
        mock_post = MagicMock()
        with patch.object(self.sonarr._session, "get", mock_get):
            with patch.object(self.sonarr._session, "post", mock_post):
                self.sonarr.add_qbittorrent(
                    host="qbittorrent",
                    port=8080,
                    username="admin",
                    password="pass",
                    category="tv",
                )
        mock_post.assert_not_called()

    def test_add_qbittorrent_posts_when_absent(self):
        mock_get = MagicMock(return_value=_ok_response([]))
        mock_post = MagicMock(return_value=_ok_response({"id": 1}))
        with patch.object(self.sonarr._session, "get", mock_get):
            with patch.object(self.sonarr._session, "post", mock_post):
                self.sonarr.add_qbittorrent(
                    host="qbittorrent",
                    port=8080,
                    username="admin",
                    password="secret",
                    category="tv",
                )
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["implementation"] == "qBittorrent"
        fields = {f["name"]: f["value"] for f in payload["fields"]}
        assert fields["host"] == "qbittorrent"
        assert fields["password"] == "secret"
        assert fields["tvCategory"] == "tv"

    def test_enable_hardlinks_skips_when_already_on(self):
        current = {"copyUsingHardlinks": True, "id": 1}
        mock_get = MagicMock(return_value=_ok_response(current))
        mock_put = MagicMock()
        with patch.object(self.sonarr._session, "get", mock_get):
            with patch.object(self.sonarr._session, "put", mock_put):
                self.sonarr.enable_hardlinks()
        mock_put.assert_not_called()

    def test_enable_hardlinks_puts_when_off(self):
        current = {"copyUsingHardlinks": False, "id": 1}
        mock_get = MagicMock(return_value=_ok_response(current))
        mock_put = MagicMock(return_value=_ok_response({"copyUsingHardlinks": True, "id": 1}))
        with patch.object(self.sonarr._session, "get", mock_get):
            with patch.object(self.sonarr._session, "put", mock_put):
                self.sonarr.enable_hardlinks()
        mock_put.assert_called_once()
        put_payload = mock_put.call_args[1]["json"]
        assert put_payload["copyUsingHardlinks"] is True


# ---------------------------------------------------------------------------
# RadarrClient tests
# ---------------------------------------------------------------------------


class TestRadarrClient:
    def setup_method(self):
        self.radarr = RadarrClient("http://localhost:7878", api_key="radarrkey")

    def test_add_root_folder_idempotent(self):
        folders = [{"id": 1, "path": "/data/media/movies"}]
        mock_get = MagicMock(return_value=_ok_response(folders))
        mock_post = MagicMock()
        with patch.object(self.radarr._session, "get", mock_get):
            with patch.object(self.radarr._session, "post", mock_post):
                self.radarr.add_root_folder("/data/media/movies")
        mock_post.assert_not_called()

    def test_add_qbittorrent_uses_movie_category(self):
        mock_get = MagicMock(return_value=_ok_response([]))
        mock_post = MagicMock(return_value=_ok_response({"id": 1}))
        with patch.object(self.radarr._session, "get", mock_get):
            with patch.object(self.radarr._session, "post", mock_post):
                self.radarr.add_qbittorrent(
                    host="qbittorrent",
                    port=8080,
                    username="admin",
                    password="secret",
                    category="movies",
                )
        payload = mock_post.call_args[1]["json"]
        fields = {f["name"]: f["value"] for f in payload["fields"]}
        assert fields["movieCategory"] == "movies"

    def test_enable_hardlinks_puts_when_off(self):
        current = {"copyUsingHardlinks": False, "id": 1}
        mock_get = MagicMock(return_value=_ok_response(current))
        mock_put = MagicMock(return_value=_ok_response({"copyUsingHardlinks": True, "id": 1}))
        with patch.object(self.radarr._session, "get", mock_get):
            with patch.object(self.radarr._session, "put", mock_put):
                self.radarr.enable_hardlinks()
        assert mock_put.called
