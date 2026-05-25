"""Jellyfin API client.

Jellyfin uses the MediaBrowser/Emby API. Full admin operations require
an access token created during first-run web-UI setup, so this wizard
limits itself to health checks and surfacing the URL on the Done page.
"""

from __future__ import annotations

import time

import requests


class JellyfinClient:
    """Minimal Jellyfin client — health probe + public info."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()

    def public_info(self) -> dict:
        """GET /System/Info/Public — does not require auth.

        Returns Jellyfin server info: server name, version, id.
        """
        resp = self._session.get(f"{self.base_url}/System/Info/Public", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def wait_until_ready(self, timeout: int = 180) -> dict:
        """Poll public_info until Jellyfin responds or the timeout expires.

        Returns the public info dict on success; raises RuntimeError on timeout.
        """
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                return self.public_info()
            except Exception as exc:
                last_error = exc
                time.sleep(3)
        raise RuntimeError(
            f"Jellyfin did not respond at {self.base_url} within {timeout}s. "
            f"Last error: {last_error}"
        )
