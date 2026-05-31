"""Operating-system detection helpers.

Centralised so the rest of the codebase branches on these functions
(and tests monkeypatch a single place) instead of calling
``platform.system()`` ad hoc. Named ``platform_detect`` to avoid
shadowing the stdlib :mod:`platform` module.

``is_macos`` / ``is_linux`` call :func:`system` rather than the stdlib
directly so that monkeypatching ``platform_detect.system`` flips every
branch at once in tests.
"""

from __future__ import annotations

import platform as _platform


def system() -> str:
    """Return the OS name, e.g. ``'Darwin'``, ``'Linux'``, ``'Windows'``."""
    return _platform.system()


def is_macos() -> bool:
    """True on macOS (Darwin)."""
    return system() == "Darwin"


def is_linux() -> bool:
    """True on Linux."""
    return system() == "Linux"
