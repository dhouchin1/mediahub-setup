"""Bazarr API client + API-key extractor.

Bazarr stores its API key in /config/config.ini after first launch. The
wiring runner reads that file via `docker exec` and then uses the REST
API to register Sonarr + Radarr connections.
"""

from __future__ import annotations

import configparser
import subprocess
import time

import requests


def read_bazarr_api_key(container_name: str, timeout: int = 120) -> str:
    """Read the API key from /config/config.ini inside the Bazarr container.

    Retries up to *timeout* seconds since the config file is created on
    first launch and may not exist immediately.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["docker", "exec", container_name, "cat", "/config/config/config.ini"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                # Try the alternate path used by some Bazarr versions
                result = subprocess.run(
                    ["docker", "exec", container_name, "cat", "/config/config.ini"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "non-zero exit from docker exec")

            parser = configparser.ConfigParser()
            parser.read_string(result.stdout)
            if "auth" in parser and parser["auth"].get("apikey"):
                return parser["auth"]["apikey"].strip()
            raise RuntimeError("apikey not yet present in config.ini")
        except (RuntimeError, configparser.Error, subprocess.TimeoutExpired) as exc:
            last_error = exc
            time.sleep(3)

    raise RuntimeError(
        f"Could not read Bazarr API key from {container_name!r} after {timeout}s. "
        f"Last error: {last_error}"
    )


class BazarrClient:
    """REST client for Bazarr — used to wire Sonarr/Radarr connections."""

    def __init__(self, base_url: str, api_key: str | None) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        if api_key:
            self._session.headers["X-API-KEY"] = api_key

    def system(self) -> dict:
        """GET /api/system — health check (lists Bazarr/Sonarr/Radarr status)."""
        resp = self._session.get(f"{self.base_url}/api/system", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def wait_until_ready(self, timeout: int = 180) -> dict:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                # /api/system requires API key — fall back to plain root for health probe
                try:
                    return self.system()
                except Exception:
                    resp = self._session.get(self.base_url + "/", timeout=10)
                    resp.raise_for_status()
                    return {"reachable": True}
            except Exception as exc:
                last_error = exc
                time.sleep(3)
        raise RuntimeError(
            f"Bazarr did not respond at {self.base_url} within {timeout}s. Last error: {last_error}"
        )

    def get_settings(self) -> dict:
        """GET /api/system/settings — full settings dict (auth required)."""
        resp = self._session.get(f"{self.base_url}/api/system/settings", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def post_settings(self, partial: dict) -> None:
        """POST /api/system/settings — partial-merge updates."""
        resp = self._session.post(
            f"{self.base_url}/api/system/settings",
            json=partial,
            timeout=15,
        )
        resp.raise_for_status()

    def set_sonarr(self, sonarr_url: str, api_key: str) -> None:
        """Configure Bazarr to fetch series from Sonarr (idempotent).

        Parses the URL into ip/port/baseurl per Bazarr's settings schema.
        """
        host, port, base = _split_url(sonarr_url)
        payload = {
            "general": {
                "use_sonarr": True,
            },
            "sonarr": {
                "ip": host,
                "port": port,
                "base_url": base or "/",
                "ssl": False,
                "http_timeout": 60,
                "apikey": api_key,
            },
        }
        self.post_settings(payload)

    def set_radarr(self, radarr_url: str, api_key: str) -> None:
        host, port, base = _split_url(radarr_url)
        payload = {
            "general": {
                "use_radarr": True,
            },
            "radarr": {
                "ip": host,
                "port": port,
                "base_url": base or "/",
                "ssl": False,
                "http_timeout": 60,
                "apikey": api_key,
            },
        }
        self.post_settings(payload)


def _split_url(url: str) -> tuple[str, int, str]:
    """Crude URL splitter. Returns (host, port, base_path)."""
    from urllib.parse import urlparse

    p = urlparse(url)
    host = p.hostname or "localhost"
    port = p.port or (443 if p.scheme == "https" else 80)
    base = p.path.rstrip("/")
    return host, port, base
