"""Native macOS menu-bar wrapper for mediahub-setup.

Requires the [menubar] optional dependency group:
    pip install 'mediahub-setup[menubar]'
or:
    pipx install 'mediahub-setup[menubar]'

The app:
  - Starts the Flask wizard server in a background daemon thread.
  - Shows a status-bar icon (dark-mode aware if you supply a template PNG).
  - Polls the server every 2 s and updates the menu item text.
  - "Open MediaHub Setup…" opens the browser; item is disabled until the
    server is accepting connections.
  - "Quit" stops both the menu-bar app and the server (daemon thread exits).
"""

from __future__ import annotations

import socket
import threading
import webbrowser

try:
    import rumps
except ImportError as exc:
    raise SystemExit(
        "The menu-bar extra is not installed.\n"
        "Run:  pip install 'mediahub-setup[menubar]'\n"
        " or:  pipx inject mediahub-setup rumps"
    ) from exc

from . import __version__
from .app import create_app
from .cli import find_free_port

# ---------------------------------------------------------------------------
# Optional: set this to an absolute path of a 22×22 PNG (template image)
# for a proper monochrome icon that inverts in dark mode.
# None falls back to the default macOS app icon from the app name.
# ---------------------------------------------------------------------------
_ICON: str | None = None


def _server_is_up(port: int) -> bool:
    """Return True if something is listening on 127.0.0.1:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


class MediaHubMenuBarApp(rumps.App):
    """Status-bar icon that starts and monitors the Flask wizard server."""

    def __init__(self) -> None:
        super().__init__(
            name="MediaHub Setup",
            icon=_ICON,
            template=True if _ICON else False,
            quit_button=None,  # we supply our own Quit item
        )
        self._port: int = find_free_port(start=7842)

        # ── Menu items ──────────────────────────────────────────────────────
        self.open_item = rumps.MenuItem(
            "Open MediaHub Setup…",
            callback=None,  # enabled once server is up
        )
        self._status = rumps.MenuItem("Starting…")  # no callback → greyed out
        self._version = rumps.MenuItem(f"v{__version__}")  # informational
        _quit = rumps.MenuItem("Quit MediaHub Setup", callback=self._on_quit)

        self.menu = [
            self.open_item,
            None,
            self._status,
            self._version,
            None,
            _quit,
        ]

        # ── Start Flask ──────────────────────────────────────────────────────
        self._start_server()

    # ── Flask server ─────────────────────────────────────────────────────────

    def _start_server(self) -> None:
        from waitress import serve

        port = self._port
        app = create_app()

        def _run() -> None:
            serve(app, host="127.0.0.1", port=port, _quiet=True)

        t = threading.Thread(target=_run, daemon=True, name="mediahub-flask")
        t.start()

    # ── Health poll every 2 s ────────────────────────────────────────────────

    @rumps.timer(2)
    def _poll(self, _sender: rumps.Timer) -> None:
        up = _server_is_up(self._port)
        if up:
            self._status.title = f"Running on port {self._port}"
            self.open_item.set_callback(self._on_open)
        else:
            self._status.title = "Starting…"
            self.open_item.set_callback(None)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _on_open(self, _sender: rumps.MenuItem) -> None:
        webbrowser.open(f"http://localhost:{self._port}/")

    def _on_quit(self, _sender: rumps.MenuItem) -> None:
        rumps.quit_application()


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Launch the menu-bar wrapper."""
    MediaHubMenuBarApp().run()


if __name__ == "__main__":
    main()
