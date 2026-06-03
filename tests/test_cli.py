"""CLI-surface tests — command registration and the `down` confirmation guard.

The heavy lifting (headless.run, doctor.run, docker_ops.compose_down) is tested
in its own module; here we only assert the click wiring: that the commands are
registered and that `down --volumes` refuses to wipe data without confirmation.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from mediahub_setup.cli import main


def test_subcommands_registered():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("serve", "install", "doctor", "down"):
        assert cmd in result.output


def test_down_plain_calls_compose_down_without_volumes():
    runner = CliRunner()
    with patch("mediahub_setup.cli.docker_ops.compose_down", return_value=(True, "done")) as cd:
        result = runner.invoke(main, ["down"])
    assert result.exit_code == 0
    assert cd.call_args.kwargs == {"remove_volumes": False}


def test_down_volumes_aborts_without_confirmation():
    runner = CliRunner()
    with patch("mediahub_setup.cli.docker_ops.compose_down") as cd:
        # Answer "n" to the confirmation prompt -> click aborts, compose_down
        # is never reached.
        result = runner.invoke(main, ["down", "--volumes"], input="n\n")
    assert result.exit_code != 0
    cd.assert_not_called()


def test_down_volumes_with_yes_skips_prompt_and_passes_flag():
    runner = CliRunner()
    with patch("mediahub_setup.cli.docker_ops.compose_down", return_value=(True, "wiped")) as cd:
        result = runner.invoke(main, ["down", "--volumes", "--yes"])
    assert result.exit_code == 0
    assert cd.call_args.kwargs == {"remove_volumes": True}


def test_doctor_propagates_exit_code():
    runner = CliRunner()
    with patch("mediahub_setup.cli.doctor.run", return_value=2):
        result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 2
