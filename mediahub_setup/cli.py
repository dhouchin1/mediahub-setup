"""Command-line entry point.

Launches the wizard as a local web server and opens the user's browser.
"""

from __future__ import annotations

import socket
import threading
import webbrowser

import click
from waitress import serve

from . import __version__, roles, state
from .app import create_app


def find_free_port(start: int = 7842, span: int = 100) -> int:
    """Find the first free TCP port at or after `start`."""
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise click.ClickException(
        f"No free port in {start}..{start + span - 1}. Try --port to override."
    )


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--port",
    type=int,
    default=None,
    help="Port to listen on (default: first free port at/after 7842)",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Don't auto-open the browser. Print the URL instead.",
)
@click.option(
    "--role",
    type=click.Choice(["all-in-one", "seedbox", "receiver"]),
    default=None,
    help=(
        "Deployment role: all-in-one (default, everything on this machine), "
        "seedbox (remote VPS download stack), or receiver (home sync target)."
    ),
)
@click.version_option(__version__, prog_name="mediahub-setup")
def main(port: int | None, no_browser: bool, role: str | None) -> None:
    """MediaHub Setup — web wizard for a self-hosted *arr stack."""
    if role:
        state.set("role", roles.normalize(role))
    port = port or find_free_port()
    url = f"http://localhost:{port}/"

    click.secho("MediaHub Setup", fg="magenta", bold=True)
    click.echo(f"  v{__version__}")
    click.echo()
    click.echo(f"  Open {click.style(url, fg='cyan', underline=True)} in your browser.")
    click.echo("  Ctrl-C to quit.")
    click.echo()

    if not no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    app = create_app()
    try:
        serve(app, host="127.0.0.1", port=port, _quiet=True)
    except KeyboardInterrupt:
        click.echo("\nBye.")
