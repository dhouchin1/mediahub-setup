"""Command-line entry point.

``mediahub-setup`` with no command launches the web wizard (unchanged
behaviour). ``mediahub-setup serve`` does the same explicitly.
``mediahub-setup install`` runs a non-interactive, config-driven install for
unattended bring-up — e.g. a remote seedbox on a VPS.
"""

from __future__ import annotations

import socket
import threading
import webbrowser

import click
from waitress import serve as _waitress_serve

from . import __version__, headless, roles, state
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


def _serve_wizard(port: int | None, no_browser: bool, role: str | None) -> None:
    """Launch the local web wizard (shared by the bare command and `serve`)."""
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
        _waitress_serve(app, host="127.0.0.1", port=port, _quiet=True)
    except KeyboardInterrupt:
        click.echo("\nBye.")


# Wizard options shared by the bare group and the explicit `serve` command.
_opt_port = click.option(
    "--port",
    type=int,
    default=None,
    help="Port to listen on (default: first free port at/after 7842)",
)
_opt_no_browser = click.option(
    "--no-browser",
    is_flag=True,
    help="Don't auto-open the browser. Print the URL instead.",
)
_opt_role = click.option(
    "--role",
    type=click.Choice(["all-in-one", "seedbox", "receiver"]),
    default=None,
    help=(
        "Deployment role: all-in-one (default, everything here), "
        "seedbox (remote VPS download stack), or receiver (home sync target)."
    ),
)


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@_opt_port
@_opt_no_browser
@_opt_role
@click.version_option(__version__, prog_name="mediahub-setup")
@click.pass_context
def main(ctx: click.Context, port: int | None, no_browser: bool, role: str | None) -> None:
    """MediaHub Setup — installer for a self-hosted *arr stack.

    Run with no command to launch the web wizard. Use `install` for an
    unattended, config-driven setup (e.g. a remote seedbox on a VPS).
    """
    if ctx.invoked_subcommand is not None:
        return  # a subcommand (serve/install) will run instead
    _serve_wizard(port, no_browser, role)


@main.command()
@_opt_port
@_opt_no_browser
@_opt_role
def serve(port: int | None, no_browser: bool, role: str | None) -> None:
    """Launch the interactive web wizard (the default action)."""
    _serve_wizard(port, no_browser, role)


@main.command()
@click.option(
    "--role",
    type=click.Choice(["seedbox", "receiver", "all-in-one"]),
    required=True,
    help="Deployment role to install.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to a YAML or JSON config file describing the install.",
)
@click.option(
    "--data-dir",
    "data_dir",
    type=click.Path(),
    default=None,
    help="Media data directory (overrides 'data_dir' in the config).",
)
@click.option("--skip-preflight", is_flag=True, help="Skip preflight checks entirely.")
@click.option("--force", is_flag=True, help="Proceed even if preflight reports failures.")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Assume yes / never prompt (headless is non-interactive anyway).",
)
def install(
    config_path: str | None,
    data_dir: str | None,
    role: str,
    skip_preflight: bool,
    force: bool,
    assume_yes: bool,
) -> None:
    """Install the stack non-interactively from a config file (headless).

    Example:

        mediahub-setup install --role seedbox --config seedbox.yml
    """
    rc = headless.run(
        role=role,
        config_path=config_path,
        data_dir=data_dir,
        skip_preflight=skip_preflight,
        force=force,
        assume_yes=assume_yes,
    )
    raise SystemExit(rc)
