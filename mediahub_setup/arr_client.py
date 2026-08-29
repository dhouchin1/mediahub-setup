"""API clients for the *arr stack and qBittorrent.

All clients are idempotent — each mutating method checks the current
state first and skips the write if nothing needs to change.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests  # noqa: I001

# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def get_qbittorrent_temp_password(container_name: str) -> str:
    """Extract the temporary password from the container logs.

    Raises RuntimeError if the password cannot be found.
    """
    result = subprocess.run(
        ["docker", "logs", container_name],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker logs failed for {container_name!r}: {result.stderr.strip()}"
        )
    # The log line looks like:
    #   A temporary password is provided for this session: AbCdEfGh
    # qBittorrent mints a NEW temporary password on every start and docker
    # logs retain all prior boots, so only the LAST match is still valid.
    output = result.stdout + result.stderr
    matches = re.findall(
        r"temporary password[^:]*:\s*(\S+)",
        output,
        re.IGNORECASE,
    )
    if matches:
        return matches[-1]
    raise RuntimeError(
        f"Could not find temporary password in logs for {container_name!r}.\n"
        "Ensure the container is running and has finished its first-boot init."
    )


def read_arr_api_key(container_name: str, timeout: int = 60) -> str:
    """Read the API key from /config/config.xml inside a container.

    Retries up to *timeout* seconds to handle containers that haven't
    finished their first-launch init yet.

    Raises RuntimeError if the key cannot be read within the timeout.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["docker", "exec", container_name, "cat", "/config/config.xml"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "non-zero exit from docker exec")

            root = ET.fromstring(result.stdout)
            key_elem = root.find("ApiKey")
            if key_elem is None or not (key_elem.text or "").strip():
                raise RuntimeError("ApiKey element missing or empty in config.xml")
            return key_elem.text.strip()

        except (RuntimeError, ET.ParseError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            time.sleep(3)

    raise RuntimeError(
        f"Could not read API key from {container_name!r} after {timeout}s. Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# qBittorrent client
# ---------------------------------------------------------------------------


class QBittorrentClient:
    """Thin client for the qBittorrent Web API v2."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()

    def login(self, password: str, username: str = "admin") -> None:
        """Log in and persist the auth cookie in the session."""
        resp = self._session.post(
            f"{self.base_url}/api/v2/auth/login",
            data={"username": username, "password": password},
            timeout=15,
        )
        resp.raise_for_status()
        if resp.text.strip().lower() == "fails.":
            raise RuntimeError("qBittorrent login failed — wrong credentials.")

    def change_password(self, new_password: str, username: str = "admin") -> None:
        """Change the Web UI password via setPreferences."""
        resp = self._session.post(
            f"{self.base_url}/api/v2/app/setPreferences",
            data={
                "json": (f'{{"web_ui_username":"{username}","web_ui_password":"{new_password}"}}')
            },
            timeout=15,
        )
        resp.raise_for_status()

    def list_categories(self) -> dict[str, Any]:
        """Return current categories as {name: {savePath: ...}}."""
        resp = self._session.get(
            f"{self.base_url}/api/v2/torrents/categories",
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def create_category(self, name: str, save_path: str) -> None:
        """Create a category if it does not already exist (idempotent)."""
        existing = self.list_categories()
        if name in existing:
            return  # already present — skip

        resp = self._session.post(
            f"{self.base_url}/api/v2/torrents/createCategory",
            data={"category": name, "savePath": save_path},
            timeout=15,
        )
        resp.raise_for_status()

    def set_listen_port(self, port: int) -> None:
        """Set the incoming BitTorrent listen port (disables random port).

        Used when qBittorrent egresses through a VPN with port-forwarding:
        the forwarded port must match qBittorrent's listen port for seeding.
        """
        resp = self._session.post(
            f"{self.base_url}/api/v2/app/setPreferences",
            data={"json": json.dumps({"listen_port": int(port), "random_port": False})},
            timeout=15,
        )
        resp.raise_for_status()

    def set_global_share_limits(
        self, *, ratio: float, seeding_time_minutes: int, remove_on_limit: bool
    ) -> None:
        """Set global ratio + seed-time limits and the action when reached.

        ``max_ratio_act`` is qBittorrent's share-limit action enum:
        ``0`` = stop (pause), ``2`` = remove torrent **and** delete its files.
        On a seedbox we remove+delete so disk is freed once seeding is done —
        the organised copy in ``/data/Media`` survives because Sonarr/Radarr
        hardlinked it (separate directory entry, same inode).
        """
        prefs = {
            "max_ratio_enabled": ratio > 0,
            "max_ratio": float(ratio),
            "max_seeding_time_enabled": seeding_time_minutes > 0,
            "max_seeding_time": int(seeding_time_minutes),
            "max_ratio_act": 2 if remove_on_limit else 0,
        }
        resp = self._session.post(
            f"{self.base_url}/api/v2/app/setPreferences",
            data={"json": json.dumps(prefs)},
            timeout=15,
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# *arr base client
# ---------------------------------------------------------------------------


class ArrClient:
    """Base REST client for Sonarr / Radarr / Prowlarr.

    Authentication is via the X-Api-Key header.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["X-Api-Key"] = api_key

    def get(self, path: str) -> Any:
        resp = self._session.get(f"{self.base_url}{path}", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, json: Any) -> Any:
        resp = self._session.post(f"{self.base_url}{path}", json=json, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def put(self, path: str, json: Any) -> Any:
        resp = self._session.put(f"{self.base_url}{path}", json=json, timeout=15)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Prowlarr client
# ---------------------------------------------------------------------------

# Sync categories per the *arr convention
_SONARR_CATEGORIES = [5000, 5010, 5020, 5030, 5040, 5045, 5050, 5060, 5070, 5080]
_RADARR_CATEGORIES = [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060, 2070]


class ProwlarrClient(ArrClient):
    """Prowlarr-specific operations."""

    def list_applications(self) -> list[dict]:
        return self.get("/api/v1/applications")

    def add_application(
        self,
        *,
        name: str,
        app_type: str,
        sync_categories: list[int],
        app_url: str,
        prowlarr_url: str,
        api_key: str,
    ) -> dict:
        """Register a downstream app in Prowlarr (idempotent).

        If an application with *name* already exists the call is skipped
        and the existing record is returned.
        """
        existing = self.list_applications()
        for app in existing:
            if app.get("name", "").lower() == name.lower():
                return app  # already registered

        payload = {
            "name": name,
            "syncLevel": "fullSync",
            "enable": True,
            "implementationName": app_type,
            "implementation": app_type,
            "configContract": f"{app_type}Settings",
            "infoLink": f"https://wiki.servarr.com/prowlarr/supported#{app_type.lower()}",
            "syncCategories": sync_categories,
            "fields": [
                {"name": "prowlarrUrl", "value": prowlarr_url},
                {"name": "baseUrl", "value": app_url},
                {"name": "apiKey", "value": api_key},
                {"name": "syncCategories", "value": sync_categories},
            ],
        }
        return self.post("/api/v1/applications", payload)

    def add_sonarr(self, *, sonarr_url: str, prowlarr_url: str, sonarr_api_key: str) -> dict:
        return self.add_application(
            name="Sonarr",
            app_type="Sonarr",
            sync_categories=_SONARR_CATEGORIES,
            app_url=sonarr_url,
            prowlarr_url=prowlarr_url,
            api_key=sonarr_api_key,
        )

    def add_radarr(self, *, radarr_url: str, prowlarr_url: str, radarr_api_key: str) -> dict:
        return self.add_application(
            name="Radarr",
            app_type="Radarr",
            sync_categories=_RADARR_CATEGORIES,
            app_url=radarr_url,
            prowlarr_url=prowlarr_url,
            api_key=radarr_api_key,
        )


# ---------------------------------------------------------------------------
# Sonarr client
# ---------------------------------------------------------------------------


class SonarrClient(ArrClient):
    """Sonarr v3 API operations."""

    def list_root_folders(self) -> list[dict]:
        return self.get("/api/v3/rootfolder")

    def add_root_folder(self, path: str) -> dict:
        """Add a root folder if it is not already configured (idempotent)."""
        existing = self.list_root_folders()
        for folder in existing:
            if folder.get("path", "").rstrip("/") == path.rstrip("/"):
                return folder
        return self.post("/api/v3/rootfolder", {"path": path})

    def list_download_clients(self) -> list[dict]:
        return self.get("/api/v3/downloadclient")

    def add_qbittorrent(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        category: str,
    ) -> dict:
        """Add a qBittorrent download client if one isn't already present (idempotent)."""
        existing = self.list_download_clients()
        for client in existing:
            if client.get("implementation", "").lower() == "qbittorrent":
                return client

        payload = {
            "enable": True,
            "protocol": "torrent",
            "priority": 1,
            "removeCompletedDownloads": True,
            "removeFailedDownloads": True,
            "name": "qBittorrent",
            "implementationName": "qBittorrent",
            "implementation": "qBittorrent",
            "configContract": "QBittorrentSettings",
            "fields": [
                {"name": "host", "value": host},
                {"name": "port", "value": port},
                {"name": "useSsl", "value": False},
                {"name": "urlBase", "value": "/"},
                {"name": "username", "value": username},
                {"name": "password", "value": password},
                {"name": "tvCategory", "value": category},
                {"name": "tvImportedCategory", "value": ""},
                {"name": "recentTvPriority", "value": 0},
                {"name": "olderTvPriority", "value": 0},
                {"name": "initialState", "value": 0},
                {"name": "sequentialOrder", "value": False},
                {"name": "firstAndLast", "value": False},
            ],
        }
        return self.post("/api/v3/downloadclient", payload)

    def enable_hardlinks(self) -> dict:
        """Enable hardlinks in media management settings."""
        current = self.get("/api/v3/config/mediamanagement")
        if current.get("copyUsingHardlinks"):
            return current  # already enabled
        current["copyUsingHardlinks"] = True
        return self.put("/api/v3/config/mediamanagement", current)


# ---------------------------------------------------------------------------
# Radarr client
# ---------------------------------------------------------------------------


class RadarrClient(ArrClient):
    """Radarr v3 API operations (same shape as SonarrClient)."""

    def list_root_folders(self) -> list[dict]:
        return self.get("/api/v3/rootfolder")

    def add_root_folder(self, path: str) -> dict:
        """Add a root folder if it is not already configured (idempotent)."""
        existing = self.list_root_folders()
        for folder in existing:
            if folder.get("path", "").rstrip("/") == path.rstrip("/"):
                return folder
        return self.post("/api/v3/rootfolder", {"path": path})

    def list_download_clients(self) -> list[dict]:
        return self.get("/api/v3/downloadclient")

    def add_qbittorrent(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        category: str,
    ) -> dict:
        """Add a qBittorrent download client if one isn't already present (idempotent)."""
        existing = self.list_download_clients()
        for client in existing:
            if client.get("implementation", "").lower() == "qbittorrent":
                return client

        payload = {
            "enable": True,
            "protocol": "torrent",
            "priority": 1,
            "removeCompletedDownloads": True,
            "removeFailedDownloads": True,
            "name": "qBittorrent",
            "implementationName": "qBittorrent",
            "implementation": "qBittorrent",
            "configContract": "QBittorrentSettings",
            "fields": [
                {"name": "host", "value": host},
                {"name": "port", "value": port},
                {"name": "useSsl", "value": False},
                {"name": "urlBase", "value": "/"},
                {"name": "username", "value": username},
                {"name": "password", "value": password},
                {"name": "movieCategory", "value": category},
                {"name": "movieImportedCategory", "value": ""},
                {"name": "recentMoviePriority", "value": 0},
                {"name": "olderMoviePriority", "value": 0},
                {"name": "initialState", "value": 0},
                {"name": "sequentialOrder", "value": False},
                {"name": "firstAndLast", "value": False},
            ],
        }
        return self.post("/api/v3/downloadclient", payload)

    def enable_hardlinks(self) -> dict:
        """Enable hardlinks in media management settings."""
        current = self.get("/api/v3/config/mediamanagement")
        if current.get("copyUsingHardlinks"):
            return current  # already enabled
        current["copyUsingHardlinks"] = True
        return self.put("/api/v3/config/mediamanagement", current)
