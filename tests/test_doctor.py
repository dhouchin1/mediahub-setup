"""Tests for the `doctor` health-check path.

Docker introspection (``docker_ops``) and Tailscale (``preflight``) are mocked
so we exercise classification, the rolled-up status, and exit codes only —
no real ``docker`` CLI is invoked.
"""

from __future__ import annotations

from mediahub_setup import doctor


def _mock_containers(monkeypatch, containers, *, available=True):
    monkeypatch.setattr(doctor.docker_ops, "docker_available", lambda: available)
    monkeypatch.setattr(doctor.docker_ops, "list_containers", lambda *a, **k: containers)


def _mock_no_disks(monkeypatch):
    # No media_dir is passed and the install dir may or may not exist; force a
    # deterministic "healthy disk" reading regardless of the host.
    monkeypatch.setattr(
        doctor.docker_ops,
        "disk_usage",
        lambda path: {"total_gb": 100.0, "used_gb": 10.0, "free_gb": 90.0, "percent_used": 10.0},
    )


# --- container classification ----------------------------------------------


def test_classify_container_states():
    assert doctor._classify_container("running") == "ok"
    assert doctor._classify_container("restarting") == "warn"
    assert doctor._classify_container("exited") == "fail"
    assert doctor._classify_container("") == "fail"


# --- top-level status ------------------------------------------------------


def test_no_docker_returns_exit_2(monkeypatch):
    _mock_containers(monkeypatch, [], available=False)
    report = doctor.diagnose()
    assert report["status"] == "no_docker"
    assert doctor.run() == doctor.EXIT_NO_DOCKER


def test_no_containers_returns_not_installed(monkeypatch):
    _mock_containers(monkeypatch, [])
    report = doctor.diagnose()
    assert report["status"] == "not_installed"
    assert doctor.run() == doctor.EXIT_NOT_INSTALLED


def test_all_running_is_healthy(monkeypatch):
    _mock_containers(
        monkeypatch,
        [
            {"name": "mediahub-sonarr", "state": "running", "status": "Up 2h", "ports": ""},
            {"name": "mediahub-radarr", "state": "running", "status": "Up 2h", "ports": ""},
        ],
    )
    _mock_no_disks(monkeypatch)
    report = doctor.diagnose()
    assert report["status"] == "ok"
    assert len(report["containers"]) == 2
    assert doctor.run() == doctor.EXIT_OK


def test_a_stopped_container_is_unhealthy(monkeypatch):
    _mock_containers(
        monkeypatch,
        [
            {"name": "mediahub-sonarr", "state": "running", "status": "Up 2h", "ports": ""},
            {
                "name": "mediahub-radarr",
                "state": "exited",
                "status": "Exited (1) 5m ago",
                "ports": "",
            },
        ],
    )
    _mock_no_disks(monkeypatch)
    report = doctor.diagnose()
    assert report["status"] == "unhealthy"
    assert doctor.run() == doctor.EXIT_UNHEALTHY


def test_low_disk_is_unhealthy(monkeypatch, tmp_path):
    _mock_containers(
        monkeypatch,
        [{"name": "mediahub-qbittorrent", "state": "running", "status": "Up", "ports": ""}],
    )
    monkeypatch.setattr(
        doctor.docker_ops,
        "disk_usage",
        lambda path: {"total_gb": 100.0, "used_gb": 98.0, "free_gb": 2.0, "percent_used": 98.0},
    )
    report = doctor.diagnose(media_dir=str(tmp_path))
    assert report["status"] == "unhealthy"
    low = [d for d in report["disks"] if d["health"] == "fail"]
    assert low, "expected the low-space disk to be flagged"
    assert doctor.run(media_dir=str(tmp_path)) == doctor.EXIT_UNHEALTHY


def test_seedbox_without_tailscale_warns(monkeypatch):
    _mock_containers(
        monkeypatch,
        [{"name": "mediahub-qbittorrent", "state": "running", "status": "Up", "ports": ""}],
    )
    _mock_no_disks(monkeypatch)
    monkeypatch.setattr(doctor.preflight, "tailscale_ip", lambda: None)
    report = doctor.diagnose(role="seedbox")
    assert report["tailscale"] == {"connected": False, "ip": None}
    assert report["status"] == "unhealthy"  # warn rolls up to unhealthy exit


def test_json_output_is_valid_and_keeps_exit_code(monkeypatch, capsys):
    import json

    _mock_containers(
        monkeypatch,
        [{"name": "mediahub-radarr", "state": "exited", "status": "Exited (1)", "ports": ""}],
    )
    _mock_no_disks(monkeypatch)
    rc = doctor.run(as_json=True)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["status"] == "unhealthy"
    assert parsed["containers"][0]["name"] == "mediahub-radarr"
    assert rc == doctor.EXIT_UNHEALTHY


def test_json_output_no_docker_exit_code(monkeypatch, capsys):
    import json

    _mock_containers(monkeypatch, [], available=False)
    rc = doctor.run(as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "no_docker"
    assert rc == doctor.EXIT_NO_DOCKER


def test_seedbox_with_tailscale_is_healthy(monkeypatch):
    _mock_containers(
        monkeypatch,
        [{"name": "mediahub-qbittorrent", "state": "running", "status": "Up", "ports": ""}],
    )
    _mock_no_disks(monkeypatch)
    monkeypatch.setattr(doctor.preflight, "tailscale_ip", lambda: "100.64.0.1")
    report = doctor.diagnose(role="seedbox")
    assert report["tailscale"]["connected"] is True
    assert report["status"] == "ok"
