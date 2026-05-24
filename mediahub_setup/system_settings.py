"""System introspection helpers for the Settings wizard step."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

DEFAULT_PORTS: dict[str, int] = {
    "sonarr": 8989,
    "radarr": 7878,
    "prowlarr": 9696,
    "qbittorrent_web": 8080,
    "qbittorrent_bt": 6881,
}

# Characters that look alike (0/O, 1/l/I) are excluded for readability.
_AMBIGUOUS = set("0O1lI")
_CHARSET = "".join(
    c
    for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    if c not in _AMBIGUOUS
)


def detect_tz() -> str:
    """Return the system timezone string by reading /etc/localtime.

    Falls back to 'UTC' if the symlink is missing or unreadable.
    """
    localtime = Path("/etc/localtime")
    try:
        target = os.readlink(localtime)
    except (OSError, ValueError):
        return "UTC"

    # The symlink typically points to something like:
    #   /var/db/timezone/zoneinfo/America/Detroit
    # or
    #   /usr/share/zoneinfo/America/Detroit
    for marker in ("zoneinfo/", "zoneinfo\\"):
        idx = target.find(marker)
        if idx != -1:
            tz = target[idx + len(marker) :]
            if tz:
                return tz

    return "UTC"


def detect_uid() -> int:
    """Return the effective UID of the current process."""
    return os.getuid()


def detect_gid() -> int:
    """Return the effective GID of the current process."""
    return os.getgid()


def generate_password(length: int = 16) -> str:
    """Generate a strong random password, excluding ambiguous characters.

    Uses :mod:`secrets` for cryptographic randomness.
    Each character is drawn uniformly from *_CHARSET* (mixed-case letters
    and digits, with 0/O/1/l/I removed).
    """
    return "".join(secrets.choice(_CHARSET) for _ in range(length))
