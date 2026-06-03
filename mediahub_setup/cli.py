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

from . import __version__, docker_ops, doctor, headless, roles, state
from . import backup as backup_mod
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
    "--dry-run",
    is_flag=True,
    help="Validate config + preflight and print the install plan without starting anything.",
)
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
    dry_run: bool,
    assume_yes: bool,
) -> None:
    """Install the stack non-interactively from a config file (headless).

    Example:

        mediahub-setup install --role seedbox --config seedbox.yml

    Pass --dry-run to validate the config and preview the plan without
    touching Docker — handy as a cloud-init pre-check.
    """
    rc = headless.run(
        role=role,
        config_path=config_path,
        data_dir=data_dir,
        skip_preflight=skip_preflight,
        force=force,
        dry_run=dry_run,
        assume_yes=assume_yes,
    )
    raise SystemExit(rc)


@main.command("doctor")
@click.option(
    "--data-dir",
    "data_dir",
    type=click.Path(),
    default=None,
    help="Media data directory to check for free space (in addition to the install dir).",
)
@click.option(
    "--role",
    type=click.Choice(["all-in-one", "seedbox", "receiver"]),
    default=None,
    help="Deployment role — enables the Tailscale connectivity check for server roles.",
)
def doctor_cmd(data_dir: str | None, role: str | None) -> None:
    """Health-check a running deployment (read-only); exits non-zero on problems.

    Probes the Docker daemon, reports every mediahub-* container's state, and
    shows disk headroom — handy for a cron/monitoring check on a remote seedbox.
    """
    raise SystemExit(doctor.run(media_dir=data_dir, role=role))


@main.command()
@click.option(
    "--volumes",
    is_flag=True,
    help="Also delete named volumes (service configs + databases). Destructive.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Don't prompt for confirmation (required with --volumes when non-interactive).",
)
def down(volumes: bool, assume_yes: bool) -> None:
    """Stop the stack (docker compose down). Media library is never touched.

    By default the named volumes (configs + *arr/qBittorrent databases) are
    preserved, so `mediahub-setup` brings the same deployment back. Pass
    --volumes to wipe them for a clean slate.
    """
    if volumes and not assume_yes:
        click.confirm(
            "This deletes all service configs and databases (not your media). Continue?",
            abort=True,
        )
    ok, output = docker_ops.compose_down(remove_volumes=volumes)
    if output:
        click.echo(output)
    if ok:
        click.secho("✓ Stack stopped." + (" Volumes removed." if volumes else ""), fg="green")
        raise SystemExit(0)
    click.secho("✘ Teardown failed (see output above).", fg="red")
    raise SystemExit(1)


@main.command()
@click.option(
    "--output",
    "-o",
    "output",
    type=click.Path(dir_okay=False),
    default=None,
    help="Archive path to write (default: ./mediahub-backup-<timestamp>.tar.gz).",
)
def backup(output: str | None) -> None:
    """Back up the deployment's config (configs + compose + .env) to a tarball.

    The media library is NOT included. For the most consistent snapshot of the
    live databases, stop the stack first with `mediahub-setup down`.
    """
    try:
        path = backup_mod.create_backup(output=output)
    except FileNotFoundError as exc:
        click.secho(f"✘ {exc}", fg="red")
        raise SystemExit(1) from exc
    size_mb = path.stat().st_size / 1e6
    click.secho(f"✓ Backup written: {path} ({size_mb:.1f} MB)", fg="green")
    raise SystemExit(0)


@main.command()
@click.argument("archive", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing config/ in the install dir.",
)
def restore(archive: str, force: bool) -> None:
    """Restore a deployment config from a backup tarball, then start the stack.

    Restores into ~/mediahub. Bring the stack up afterwards with
    `mediahub-setup` (or `install`). The stack should be stopped during restore.
    """
    try:
        restored = backup_mod.restore_backup(archive, force=force)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        click.secho(f"✘ {exc}", fg="red")
        raise SystemExit(1) from exc
    click.secho(f"✓ Restored: {', '.join(restored)}", fg="green")
    click.echo("  Start the stack with `mediahub-setup` (or `mediahub-setup install`).")
    raise SystemExit(0)
