"""Overseerr / Jellyseerr REST client.

Overseerr is a TV/movie request app; Jellyseerr is its Jellyfin-focused
fork and exposes an *identical* REST API. This module works against
either — the wiring step instantiates the same client class for both.

The API requires a key generated during first-run setup in the web UI,
so the wizard only:

  1. Polls the public ``/api/v1/status`` health endpoint to confirm
     the container booted.
  2. Surfaces the URL + setup hints on the Done page.

The client is kept thin so future versions can deepen the integration
(e.g. seeding the Sonarr/Radarr server records via REST) without
touching ``wiring_runner.py``.
"""

from __future__ import annotations

import time

import requests


class RequestAppClient:
    """Minimal Overseerr/Jellyseerr REST client (identical API)."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        if api_key:
            self._session.headers["X-Api-Key"] = api_key

    def status(self) -> dict:
        """GET ``/api/v1/status`` — public health endpoint.

        Returns version + commitTag + updateAvailable.
        """
        resp = self._session.get(f"{self.base_url}/api/v1/status", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def wait_until_ready(self, timeout: int = 180) -> dict:
        """Poll ``/api/v1/status`` until reachable or *timeout* expires."""
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                return self.status()
            except Exception as exc:
                last_error = exc
                time.sleep(3)
        raise RuntimeError(
            f"Request app did not respond at {self.base_url} within {timeout}s. "
            f"Last error: {last_error}"
        )


# Aliases for back-compat / readability — callers can pick whichever name
# matches the service they're talking to.
OverseerrClient = RequestAppClient
JellyseerrClient = RequestAppClient
