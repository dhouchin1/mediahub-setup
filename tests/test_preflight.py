"""Smoke tests for preflight checks.

These tests assert structural invariants — they don't make claims
about whether Docker is actually installed on the test machine, since
that varies. Functional integration tests would go in a separate
suite that the dev runs locally with Docker up.
"""

from __future__ import annotations

import pytest

from mediahub_setup import platform_detect, preflight

# Some checks probe macOS-only paths (/Volumes); skip them off macOS so the
# suite is green on a Linux CI runner.
macos_only = pytest.mark.skipif(
    not platform_detect.is_macos(), reason="exercises macOS /Volumes behaviour"
)


def test_run_all_returns_results_for_every_check():
    results = preflight.run_all()
    assert len(results) >= 5
    names = {r.name for r in results}
    assert "Docker installed" in names
    assert "Docker daemon running" in names
    assert "Compose plugin" in names
    assert "Required ports" in names


def test_every_result_has_required_fields():
    for r in preflight.run_all():
        assert r.name
        assert r.status in {"pass", "warn", "fail"}
        assert r.message


def test_overall_status_is_worst_of_results():
    pass_r = preflight.CheckResult("x", "pass", "ok")
    warn_r = preflight.CheckResult("x", "warn", "meh")
    fail_r = preflight.CheckResult("x", "fail", "no")

    assert preflight.overall_status([pass_r, pass_r]) == "pass"
    assert preflight.overall_status([pass_r, warn_r]) == "warn"
    assert preflight.overall_status([pass_r, warn_r, fail_r]) == "fail"
    assert preflight.overall_status([fail_r]) == "fail"


def test_run_all_includes_file_sharing_check():
    """File-sharing check must appear in run_all() output."""
    names = {r.name for r in preflight.run_all()}
    assert "Container file sharing" in names


def test_check_file_sharing_warns_when_docker_unreachable(monkeypatch):
    """When `docker run` fails (no daemon), check returns warn — never fail."""
    monkeypatch.setattr(preflight, "_run", lambda *a, **kw: None)
    result = preflight.check_file_sharing()
    assert result.status in {"warn", "pass"}  # may pass on machines with no /Volumes entries
    assert result.fix is not None or result.status == "pass"


def test_check_tailscale_warns_when_not_installed(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    r = preflight.check_tailscale()
    assert r.status == "warn"
    assert r.fix


def test_check_tailscale_passes_when_connected(monkeypatch):
    import subprocess

    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/tailscale")
    monkeypatch.setattr(
        preflight,
        "_run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="100.64.0.5\n", stderr=""),
    )
    r = preflight.check_tailscale()
    assert r.status == "pass"


def test_check_tailscale_warns_when_logged_out(monkeypatch):
    import subprocess

    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/tailscale")
    monkeypatch.setattr(
        preflight,
        "_run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="Logged out.\n", stderr=""),
    )
    r = preflight.check_tailscale()
    assert r.status == "warn"


def test_run_all_appends_tailscale_only_for_seedbox(monkeypatch):
    stub = lambda name: lambda: preflight.CheckResult(name, "pass", "ok")  # noqa: E731
    for fn, nm in [
        ("check_docker_installed", "d"),
        ("check_docker_daemon", "dd"),
        ("check_docker_compose", "c"),
        ("check_ports", "p"),
        ("check_file_sharing", "fs"),
        ("check_disk_space", "disk"),
        ("check_tailscale", "Tailscale (private access)"),
    ]:
        monkeypatch.setattr(preflight, fn, stub(nm))
    seedbox = {r.name for r in preflight.run_all(role="seedbox")}
    allinone = {r.name for r in preflight.run_all(role="all_in_one")}
    assert "Tailscale (private access)" in seedbox
    assert "Tailscale (private access)" not in allinone


def test_check_file_sharing_linux_returns_pass(monkeypatch):
    """On Linux the check is a no-op pass — it must not touch /Volumes."""
    monkeypatch.setattr(preflight.platform_detect, "is_macos", lambda: False)
    result = preflight.check_file_sharing()
    assert result.name == "Container file sharing"
    assert result.status == "pass"


@macos_only
def test_check_file_sharing_passes_when_all_drives_visible(monkeypatch):
    """When container output contains every host /Volumes entry, status is pass."""
    import os
    import subprocess

    # Mirror check_file_sharing's own filter (it ignores the boot volume), so
    # the test skips cleanly on a Mac with no external drive mounted.
    host_entries = [
        e for e in os.listdir("/Volumes") if not e.startswith(".") and e != "Macintosh HD"
    ]
    container_listing = "\n".join(host_entries) + "\n"

    fake_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=container_listing, stderr=""
    )
    monkeypatch.setattr(preflight, "_run", lambda *a, **kw: fake_proc)
    result = preflight.check_file_sharing()
    assert result.status == "pass"


@macos_only
def test_check_file_sharing_warns_when_drive_missing_from_container(monkeypatch):
    """If the container can't see a drive the host can, warn with a fix message."""
    import os
    import subprocess

    # Mirror check_file_sharing's own filter (it ignores the boot volume), so
    # the test skips cleanly on a Mac with no external drive mounted.
    host_entries = [
        e for e in os.listdir("/Volumes") if not e.startswith(".") and e != "Macintosh HD"
    ]
    if not host_entries:
        # Nothing to compare against on this machine — skip cleanly
        import pytest

        pytest.skip("No external drives mounted under /Volumes on this machine.")

    # Pretend the container saw nothing — every host drive is "missing"
    fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(preflight, "_run", lambda *a, **kw: fake_proc)
    result = preflight.check_file_sharing()
    assert result.status == "warn"
    assert result.fix is not None


def test_required_ports_match_stack_defaults():
    """Preflight must probe the ports the stack actually publishes.

    Regression: qBittorrent was probed on 8080 while DEFAULT_PORTS (and the
    compose template) publish 8090, so a busy 8090 passed preflight and then
    failed the install at docker compose up.
    """
    from mediahub_setup.system_settings import DEFAULT_PORTS

    probed = {port for port, _label in preflight.REQUIRED_PORTS}
    expected = {
        DEFAULT_PORTS["sonarr"],
        DEFAULT_PORTS["radarr"],
        DEFAULT_PORTS["prowlarr"],
        DEFAULT_PORTS["qbittorrent_web"],
        DEFAULT_PORTS["qbittorrent_bt"],
    }
    assert probed == expected
