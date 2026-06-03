"""Tests for the headless (non-interactive) install path.

No real Docker, *arr APIs, or preflight side-effects: installer + wiring +
preflight are mocked so we exercise orchestration, state contracts, and exit
codes only. The data dir is a real tmp_path so drives.drive_from_path works.
"""

from __future__ import annotations

import pytest

from mediahub_setup import headless, installer, preflight, state, wiring_runner


@pytest.fixture(autouse=True)
def clean_state():
    state.clear()
    yield
    state.clear()


def _mock_preflight(monkeypatch, overall="pass"):
    monkeypatch.setattr(preflight, "run_all", lambda role=None: [])
    monkeypatch.setattr(preflight, "overall_status", lambda results: overall)
    monkeypatch.setattr(preflight, "tailscale_ip", lambda: None)


def _mock_install_ready(monkeypatch, tmp_path, status="ready"):
    monkeypatch.setattr(installer, "prepare_install_dir", lambda: tmp_path)
    monkeypatch.setattr(installer, "prepare_media_layout", lambda *a, **k: None)
    monkeypatch.setattr(installer, "render_compose", lambda d, s: tmp_path / "docker-compose.yml")
    monkeypatch.setattr(installer, "render_env", lambda d, dr, s: tmp_path / ".env")
    monkeypatch.setattr(installer, "start_install", lambda *a, **k: True)
    monkeypatch.setattr(
        installer,
        "install_status",
        lambda: {
            "status": status,
            "services": {"sonarr": "ready", "qbittorrent": "ready"},
            "compose_path": str(tmp_path / "docker-compose.yml"),
            "env_path": str(tmp_path / ".env"),
            "log_lines": ["boom"] if status == "error" else [],
            "error": "compose failed" if status == "error" else None,
            "progress": 100,
        },
    )


def _mock_wiring_complete(monkeypatch):
    monkeypatch.setattr(
        wiring_runner, "planned_task_names", lambda enabled, role: ["Connect to qBittorrent"]
    )
    monkeypatch.setattr(wiring_runner, "start_wiring", lambda: None)
    monkeypatch.setattr(
        wiring_runner,
        "wiring_status",
        lambda: {
            "phase": "complete",
            "tasks": [{"name": "Connect to qBittorrent", "status": "ok", "message": "ok"}],
        },
    )


# --- load_config -----------------------------------------------------------


def test_load_config_yaml(tmp_path):
    p = tmp_path / "c.yml"
    p.write_text("role: seedbox\ndata_dir: /mnt/data\n")
    cfg = headless.load_config(p)
    assert cfg["role"] == "seedbox"
    assert cfg["data_dir"] == "/mnt/data"


def test_load_config_rejects_non_mapping(tmp_path):
    p = tmp_path / "bad.yml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ValueError):
        headless.load_config(p)


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        headless.load_config(tmp_path / "nope.yml")


# --- run() -----------------------------------------------------------------


def test_run_seedbox_happy_path(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    _mock_preflight(monkeypatch)
    _mock_install_ready(monkeypatch, tmp_path)
    _mock_wiring_complete(monkeypatch)

    rc = headless.run(role="seedbox", data_dir=str(data_dir), poll_interval=0)

    assert rc == headless.EXIT_OK
    assert state.get("role") == "seedbox"
    settings = state.get("settings")
    assert settings["role"] == "seedbox"
    assert "syncthing" in settings["enabled_services"]
    assert state.get("drive")["mount_path"] == str(data_dir)
    assert state.get("install")["status"] == "ready"


def test_run_receiver_happy_path(tmp_path, monkeypatch):
    data_dir = tmp_path / "rx"
    _mock_preflight(monkeypatch)
    _mock_install_ready(monkeypatch, tmp_path)
    _mock_wiring_complete(monkeypatch)

    rc = headless.run(role="receiver", data_dir=str(data_dir), poll_interval=0)
    assert rc == headless.EXIT_OK
    assert state.get("settings")["role"] == "receiver"


def test_run_missing_data_dir_returns_drive_error(monkeypatch):
    _mock_preflight(monkeypatch)
    rc = headless.run(role="seedbox", data_dir=None, poll_interval=0)
    assert rc == headless.EXIT_DRIVE


def test_run_preflight_fail_aborts(tmp_path, monkeypatch):
    _mock_preflight(monkeypatch, overall="fail")
    rc = headless.run(role="seedbox", data_dir=str(tmp_path / "d"), poll_interval=0)
    assert rc == headless.EXIT_PREFLIGHT


def test_run_preflight_fail_with_force_continues(tmp_path, monkeypatch):
    _mock_preflight(monkeypatch, overall="fail")
    _mock_install_ready(monkeypatch, tmp_path)
    _mock_wiring_complete(monkeypatch)
    rc = headless.run(role="seedbox", data_dir=str(tmp_path / "d"), force=True, poll_interval=0)
    assert rc == headless.EXIT_OK


def test_run_skip_preflight(tmp_path, monkeypatch):
    # run_all must NOT be called when skipped.
    def _boom(role=None):
        raise AssertionError("preflight should be skipped")

    monkeypatch.setattr(preflight, "run_all", _boom)
    monkeypatch.setattr(preflight, "tailscale_ip", lambda: None)
    _mock_install_ready(monkeypatch, tmp_path)
    _mock_wiring_complete(monkeypatch)
    rc = headless.run(
        role="seedbox", data_dir=str(tmp_path / "d"), skip_preflight=True, poll_interval=0
    )
    assert rc == headless.EXIT_OK


def test_run_bad_gluetun_config_returns_config_error(tmp_path, monkeypatch):
    _mock_preflight(monkeypatch)
    cfg = tmp_path / "c.yml"
    cfg.write_text("services:\n  - gluetun\n")  # no creds -> SettingsError
    rc = headless.run(
        role="seedbox", config_path=str(cfg), data_dir=str(tmp_path / "d"), poll_interval=0
    )
    assert rc == headless.EXIT_CONFIG


def test_run_install_error_returns_install_error(tmp_path, monkeypatch):
    _mock_preflight(monkeypatch)
    _mock_install_ready(monkeypatch, tmp_path, status="error")
    rc = headless.run(role="seedbox", data_dir=str(tmp_path / "d"), poll_interval=0)
    assert rc == headless.EXIT_INSTALL


def test_run_wiring_failure_returns_wiring_error(tmp_path, monkeypatch):
    _mock_preflight(monkeypatch)
    _mock_install_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(wiring_runner, "planned_task_names", lambda enabled, role: ["t"])
    monkeypatch.setattr(wiring_runner, "start_wiring", lambda: None)
    monkeypatch.setattr(
        wiring_runner,
        "wiring_status",
        lambda: {"phase": "failed", "tasks": [{"name": "t", "status": "failed", "message": "x"}]},
    )
    rc = headless.run(role="seedbox", data_dir=str(tmp_path / "d"), poll_interval=0)
    assert rc == headless.EXIT_WIRING


# --- CLI wiring ------------------------------------------------------------


def test_cli_install_invokes_headless(monkeypatch):
    from click.testing import CliRunner

    from mediahub_setup import cli

    captured: dict = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli.headless, "run", fake_run)
    result = CliRunner().invoke(
        cli.main, ["install", "--role", "seedbox", "--data-dir", "/mnt/data", "--yes"]
    )
    assert result.exit_code == 0
    assert captured["role"] == "seedbox"
    assert captured["data_dir"] == "/mnt/data"
    assert captured["assume_yes"] is True


def test_cli_install_propagates_nonzero_exit(monkeypatch):
    from click.testing import CliRunner

    from mediahub_setup import cli

    monkeypatch.setattr(cli.headless, "run", lambda **k: headless.EXIT_INSTALL)
    result = CliRunner().invoke(cli.main, ["install", "--role", "seedbox", "--data-dir", "/x"])
    assert result.exit_code == headless.EXIT_INSTALL


def test_cli_help_lists_install_command():
    from click.testing import CliRunner

    from mediahub_setup import cli

    result = CliRunner().invoke(cli.main, ["--help"])
    assert result.exit_code == 0
    assert "install" in result.output
    assert "serve" in result.output
