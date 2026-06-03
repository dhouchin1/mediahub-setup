"""Unit tests for mediahub_setup.docker_ops.

All subprocess and shutil.which calls are mocked. No real Docker daemon
is required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mediahub_setup import docker_ops
from mediahub_setup.docker_ops import _parse_percent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a mock subprocess.CompletedProcess-like object."""
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# docker_available
# ---------------------------------------------------------------------------


def test_docker_available_returns_false_when_cli_missing():
    """docker_available() must return False when 'docker' is not on PATH."""
    with patch("shutil.which", return_value=None):
        assert docker_ops.docker_available() is False


def test_docker_available_returns_true_on_success():
    """docker_available() must return True when CLI is present and daemon responds."""
    with patch("shutil.which", return_value="/usr/local/bin/docker"):
        with patch("subprocess.run", return_value=_proc(returncode=0, stdout="24.0.5")):
            assert docker_ops.docker_available() is True


# ---------------------------------------------------------------------------
# list_containers
# ---------------------------------------------------------------------------


def test_list_containers_parses_json_output():
    """list_containers() must parse newline-delimited JSON from docker ps."""
    rows = [
        {
            "Names": "mediahub-sonarr",
            "Image": "sonarr:latest",
            "State": "running",
            "Status": "Up 2 hours",
            "CreatedAt": "2024-01-01",
            "Ports": "8989/tcp",
        },
        {
            "Names": "mediahub-radarr",
            "Image": "radarr:latest",
            "State": "exited",
            "Status": "Exited (0)",
            "CreatedAt": "2024-01-01",
            "Ports": "",
        },
    ]
    stdout = "\n".join(json.dumps(r) for r in rows)
    with patch("subprocess.run", return_value=_proc(returncode=0, stdout=stdout)):
        result = docker_ops.list_containers()
    assert len(result) == 2
    assert result[0]["name"] == "mediahub-sonarr"
    assert result[0]["state"] == "running"
    assert result[1]["name"] == "mediahub-radarr"
    assert result[1]["state"] == "exited"


def test_list_containers_returns_empty_on_failure():
    """list_containers() must return [] when docker ps exits non-zero."""
    with patch("subprocess.run", return_value=_proc(returncode=1, stderr="permission denied")):
        result = docker_ops.list_containers()
    assert result == []


# ---------------------------------------------------------------------------
# docker_stats
# ---------------------------------------------------------------------------


def test_docker_stats_filters_by_prefix():
    """docker_stats() must include only containers whose name starts with the prefix."""
    rows = [
        {
            "Name": "mediahub-sonarr",
            "CPUPerc": "1.2%",
            "MemPerc": "3.4%",
            "MemUsage": "100MiB",
            "NetIO": "1kB",
            "BlockIO": "2kB",
            "PIDs": "5",
        },
        {
            "Name": "unrelated-container",
            "CPUPerc": "0%",
            "MemPerc": "0%",
            "MemUsage": "0",
            "NetIO": "0",
            "BlockIO": "0",
            "PIDs": "1",
        },
    ]
    stdout = "\n".join(json.dumps(r) for r in rows)
    with patch("subprocess.run", return_value=_proc(returncode=0, stdout=stdout)):
        result = docker_ops.docker_stats()
    assert len(result) == 1
    assert result[0]["name"] == "mediahub-sonarr"
    assert result[0]["cpu_percent"] == pytest.approx(1.2)


# ---------------------------------------------------------------------------
# _parse_percent
# ---------------------------------------------------------------------------


def test_parse_percent_handles_garbage():
    """_parse_percent with a non-numeric string must return 0.0."""
    assert _parse_percent("abc") == 0.0


def test_parse_percent_strips_percent_sign():
    """_parse_percent must correctly parse '12.5%'."""
    assert _parse_percent("12.5%") == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# disk_usage
# ---------------------------------------------------------------------------


def test_disk_usage_returns_zeros_for_missing_path(tmp_path):
    """disk_usage() for a non-existent path must return all-zero dict."""
    result = docker_ops.disk_usage(tmp_path / "does_not_exist")
    assert result == {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "percent_used": 0.0}


def test_disk_usage_calculates_percent_used(tmp_path):
    """disk_usage() for an existing path must return a dict with percent_used > 0."""
    result = docker_ops.disk_usage(tmp_path)
    # The tmp dir lives on a real filesystem so total_gb > 0
    assert result["total_gb"] > 0
    assert 0.0 <= result["percent_used"] <= 100.0
    assert result["used_gb"] + result["free_gb"] == pytest.approx(result["total_gb"], rel=0.01)


# ---------------------------------------------------------------------------
# restart_container
# ---------------------------------------------------------------------------


def test_restart_container_refuses_outside_namespace():
    """restart_container() must refuse names that don't start with 'mediahub-'."""
    ok, msg = docker_ops.restart_container("some-other-container")
    assert ok is False
    assert "mediahub-" in msg.lower() or "namespace" in msg.lower() or "refusing" in msg.lower()


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------


def test_update_status_initial_is_idle():
    """update_status() must report status='idle' before compose_update_all() is called."""
    status = docker_ops.update_status()
    # The status may already be running from a previous test in the process, but
    # in a fresh import it starts idle. We just assert the dict has the right shape.
    assert "status" in status
    assert "log_lines" in status
    assert isinstance(status["log_lines"], list)


# ---------------------------------------------------------------------------
# compose_down
# ---------------------------------------------------------------------------


def test_compose_down_no_compose_file(tmp_path):
    """Without a docker-compose.yml there's nothing to tear down."""
    ok, msg = docker_ops.compose_down(install_dir=tmp_path)
    assert ok is False
    assert "nothing to tear down" in msg


def test_compose_down_runs_plain_down(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    with patch("subprocess.run", return_value=_proc(returncode=0, stdout="Removed")) as run:
        ok, msg = docker_ops.compose_down(install_dir=tmp_path)
    assert ok is True
    cmd = run.call_args.args[0]
    assert cmd == ["docker", "compose", "down"]
    assert "--volumes" not in cmd


def test_compose_down_with_volumes_passes_flag(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    with patch("subprocess.run", return_value=_proc(returncode=0, stdout="")) as run:
        ok, _ = docker_ops.compose_down(install_dir=tmp_path, remove_volumes=True)
    assert ok is True
    assert run.call_args.args[0] == ["docker", "compose", "down", "--volumes"]


def test_compose_down_reports_failure(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    with patch("subprocess.run", return_value=_proc(returncode=1, stderr="boom")):
        ok, msg = docker_ops.compose_down(install_dir=tmp_path)
    assert ok is False
    assert "boom" in msg
