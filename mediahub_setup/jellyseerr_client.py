"""Jellyseerr API client.

Jellyseerr is the Jellyfin-flavored fork of Overseerr. Its REST API
requires an admin session or API key generated during first-run setup,
which the user does in the web UI. The wizard therefore only:

  1. Waits for the server to be reachable (so we know it booted).
  2. Surfaces the URL and a setup hint on the Done page.

This module is a thin client so future versions can deepen the
integration (importing libraries automatically, etc.) without touching
wiring_runner.py.
"""

from __future__ import annotations

import time

import requests


class JellyseerrClient:
    """Minimal Jellyseerr REST client."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        if api_key:
            self._session.headers["X-Api-Key"] = api_key

    def status(self) -> dict:
        """GET /api/v1/status — public health endpoint.

        Returns version + commitTag + updateAvailable.
        """
        resp = self._session.get(f"{self.base_url}/api/v1/status", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def wait_until_ready(self, timeout: int = 180) -> dict:
        """Poll /status until reachable or *timeout* expires."""
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                return self.status()
            except Exception as exc:
                last_error = exc
                time.sleep(3)
        raise RuntimeError(
            f"Jellyseerr did not respond at {self.base_url} within {timeout}s. "
            f"Last error: {last_error}"
        )
