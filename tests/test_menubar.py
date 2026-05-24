"""Smoke tests for mediahub_setup.menubar.

rumps is macOS-only and requires a running event loop, so we skip the full
app instantiation in CI and only test the helpers that can run anywhere.

The ImportError guard on missing `rumps` is tested in test_import_guard.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def test_server_is_up_returns_false_for_closed_port():
    """_server_is_up should return False for a port with nothing listening."""
    import socket

    # Find a port that's definitely not in use
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    # Port is now released — nothing listening

    # Patch the module so we don't need rumps installed
    rumps_mock = MagicMock()
    with patch.dict(sys.modules, {"rumps": rumps_mock}):
        from mediahub_setup.menubar import _server_is_up

        assert _server_is_up(free_port) is False


# ── Import guard ──────────────────────────────────────────────────────────────


def test_import_guard_raises_on_missing_rumps():
    """Importing menubar without rumps installed should raise SystemExit."""
    # Temporarily remove rumps from sys.modules and make it unimportable
    saved = sys.modules.pop("mediahub_setup.menubar", None)
    rumps_saved = sys.modules.pop("rumps", None)

    try:
        with patch.dict(sys.modules, {"rumps": None}):
            with pytest.raises((SystemExit, ImportError)):
                import mediahub_setup.menubar  # noqa: F401, PLC0415
    finally:
        # Restore original state
        sys.modules.pop("mediahub_setup.menubar", None)
        if saved is not None:
            sys.modules["mediahub_setup.menubar"] = saved
        if rumps_saved is not None:
            sys.modules["rumps"] = rumps_saved


# ── Entry point ───────────────────────────────────────────────────────────────


def test_main_callable_with_mocked_rumps():
    """main() should call rumps.App.run() when rumps is available."""
    rumps_mock = MagicMock()

    # Make MediaHubMenuBarApp instantiation succeed without a real event loop
    app_instance = MagicMock()
    rumps_mock.App = MagicMock(return_value=app_instance)
    rumps_mock.timer = lambda interval: (lambda fn: fn)  # no-op decorator
    rumps_mock.MenuItem = MagicMock()
    rumps_mock.quit_application = MagicMock()

    saved = sys.modules.pop("mediahub_setup.menubar", None)

    try:
        with patch.dict(sys.modules, {"rumps": rumps_mock}):
            # Re-import so the module sees our mock
            import importlib

            import mediahub_setup.menubar as mb

            importlib.reload(mb)

            # main() constructs the app and calls run()
            with patch.object(mb, "MediaHubMenuBarApp") as MockApp:
                mock_instance = MagicMock()
                MockApp.return_value = mock_instance
                mb.main()
                MockApp.assert_called_once()
                mock_instance.run.assert_called_once()
    finally:
        sys.modules.pop("mediahub_setup.menubar", None)
        if saved is not None:
            sys.modules["mediahub_setup.menubar"] = saved
