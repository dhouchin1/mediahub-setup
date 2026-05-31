"""Back-compat shim — the canonical client now lives in ``overseerr_client``.

Overseerr and Jellyseerr expose the same REST API (Jellyseerr forked
from Overseerr), so the wizard uses a single ``RequestAppClient`` class
under the hood. Existing imports of ``JellyseerrClient`` continue to
work via this re-export.
"""

from __future__ import annotations

from .overseerr_client import JellyseerrClient, OverseerrClient, RequestAppClient

__all__ = ["JellyseerrClient", "OverseerrClient", "RequestAppClient"]
