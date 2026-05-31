"""Syncthing REST API client + API-key extractor.

Syncthing stores its API key inside ``/var/syncthing/config/config.xml``
which is generated on first start. The wiring runner reads that key via
``docker exec``, then drives the REST API to: discover this node's device ID,
create/replace the shared folder (Send-Only on a seedbox, Receive-Only WITH
forced staggered versioning on a receiver), add the remote peer device, and
share the folder with it.

SAFETY NOTE — Receive-Only + versioning
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Syncthing's "Receive Only" folder type does *not* stop remote deletions from
propagating locally. Whenever a folder is configured as ``receiveonly``, the
wiring layer MUST attach staggered file versioning with an unlimited retention
window (``maxAge: "0"``). This ensures that a deletion on the sender parks the
file in ``.stversions`` instead of destroying the local copy. ``set_folder``
enforces this automatically: if ``folder_type == "receiveonly"`` and no custom
``versioning`` dict is supplied, the default staggered policy is injected.
"""

from __future__ import annotations

import subprocess
import time
import xml.etree.ElementTree as ET

import requests

# ---------------------------------------------------------------------------
# Default versioning policy for receive-only folders
# ---------------------------------------------------------------------------

_RECEIVEONLY_DEFAULT_VERSIONING: dict = {
    "type": "staggered",
    "params": {"maxAge": "0"},
    "cleanupIntervalS": 3600,
}


# ---------------------------------------------------------------------------
# API-key extractor
# ---------------------------------------------------------------------------


def read_syncthing_apikey(container_name: str = "mediahub-syncthing", timeout: int = 120) -> str:
    """Read the GUI API key from ``/var/syncthing/config/config.xml`` inside
    the container.

    Syncthing generates the config (including API key) on first start, so this
    function retries up to *timeout* seconds. On timeout it raises
    ``RuntimeError`` with the last error message.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["docker", "exec", container_name, "cat", "/var/syncthing/config/config.xml"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "non-zero exit from docker exec")

            root = ET.fromstring(result.stdout)
            apikey_el = root.find(".//gui/apikey")
            if apikey_el is not None and apikey_el.text and apikey_el.text.strip():
                return apikey_el.text.strip()
            raise RuntimeError("apikey not yet present in config.xml")
        except (RuntimeError, ET.ParseError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            time.sleep(3)

    raise RuntimeError(
        f"Could not read Syncthing API key from {container_name!r} after {timeout}s. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# REST client
# ---------------------------------------------------------------------------


class SyncthingClient:
    """REST client for the Syncthing API (default port 8384).

    All requests use a single :class:`requests.Session` with the
    ``X-API-Key`` header pre-set.
    """

    def __init__(self, base_url: str, api_key: str | None) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        if api_key:
            self._session.headers["X-API-Key"] = api_key

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """GET /rest/system/ping — returns ``{"ping": "pong"}`` when alive."""
        resp = self._session.get(f"{self.base_url}/rest/system/ping", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def wait_until_ready(self, timeout: int = 180) -> dict:
        """Block until :meth:`ping` succeeds or *timeout* seconds elapse.

        Raises :class:`RuntimeError` on timeout.
        """
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                return self.ping()
            except Exception as exc:
                last_error = exc
                time.sleep(3)
        raise RuntimeError(
            f"Syncthing did not respond at {self.base_url} within {timeout}s. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Device identity
    # ------------------------------------------------------------------

    def my_device_id(self) -> str:
        """Return this node's device ID via GET /rest/system/status."""
        resp = self._session.get(f"{self.base_url}/rest/system/status", timeout=15)
        resp.raise_for_status()
        return resp.json()["myID"]

    def add_device(
        self,
        device_id: str,
        *,
        name: str = "mediahub-peer",
        introducer: bool = False,
        auto_accept: bool = False,
    ) -> None:
        """Add (or replace) a remote peer device.

        PUT /rest/config/devices/{device_id}
        """
        body = {
            "deviceID": device_id,
            "name": name,
            "addresses": ["dynamic"],
            "introducer": introducer,
            "autoAcceptFolders": auto_accept,
        }
        resp = self._session.put(
            f"{self.base_url}/rest/config/devices/{device_id}",
            json=body,
            timeout=15,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def set_folder(
        self,
        *,
        folder_id: str,
        label: str,
        path: str,
        folder_type: str,
        device_ids: list[str],
        versioning: dict | None = None,
    ) -> None:
        """Create or replace a shared folder.

        ``folder_type`` must be ``"sendonly"`` or ``"receiveonly"``.

        Safety rule: if ``folder_type == "receiveonly"`` and *versioning* is
        ``None``, the default staggered policy with unlimited retention is
        injected automatically, so remote deletions are parked in
        ``.stversions`` instead of being applied locally.

        PUT /rest/config/folders/{folder_id}
        """
        if folder_type == "receiveonly" and versioning is None:
            versioning = _RECEIVEONLY_DEFAULT_VERSIONING

        body: dict = {
            "id": folder_id,
            "label": label,
            "path": path,
            "type": folder_type,
            "devices": [{"deviceID": d} for d in device_ids],
            "fsWatcherEnabled": True,
            "fsWatcherDelayS": 10,
            "rescanIntervalS": 3600,
        }
        if versioning is not None:
            body["versioning"] = versioning

        resp = self._session.put(
            f"{self.base_url}/rest/config/folders/{folder_id}",
            json=body,
            timeout=15,
        )
        resp.raise_for_status()

    def share_folder_with(self, folder_id: str, device_id: str) -> None:
        """Idempotently add *device_id* to the sharing list of *folder_id*.

        GET /rest/config/folders/{folder_id} then PUT back with the device
        appended if not already present.
        """
        resp = self._session.get(
            f"{self.base_url}/rest/config/folders/{folder_id}",
            timeout=15,
        )
        resp.raise_for_status()
        folder_cfg = resp.json()

        existing_ids = {d["deviceID"] for d in folder_cfg.get("devices", [])}
        if device_id not in existing_ids:
            folder_cfg.setdefault("devices", []).append({"deviceID": device_id})
            put_resp = self._session.put(
                f"{self.base_url}/rest/config/folders/{folder_id}",
                json=folder_cfg,
                timeout=15,
            )
            put_resp.raise_for_status()
