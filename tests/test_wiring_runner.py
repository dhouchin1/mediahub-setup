"""Unit tests for mediahub_setup.wiring_runner.

Validates the task plan builder and status helpers. No real Docker or
container calls are made.
"""

from __future__ import annotations

import pytest

from mediahub_setup import state, wiring_runner
from mediahub_setup.wiring_runner import WiringTask, _build_task_plan, planned_task_names

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORE_TASK_COUNT = 15  # number of tasks in the baseline core-only plan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_state():
    """Clear wizard state before and after every test."""
    state.clear()
    yield
    state.clear()


# ---------------------------------------------------------------------------
# planned_task_names — task count assertions
# ---------------------------------------------------------------------------


def test_planned_task_names_core_only_returns_15_tasks():
    """Core-only plan must produce exactly 15 tasks."""
    names = planned_task_names([])
    assert len(names) == _CORE_TASK_COUNT


def test_planned_task_names_with_jellyfin_adds_two_tasks():
    """Adding jellyfin appends exactly 2 more tasks."""
    base = len(planned_task_names([]))
    with_jf = len(planned_task_names(["jellyfin"]))
    assert with_jf == base + 2


def test_planned_task_names_with_jellyseerr_adds_two_tasks():
    """Adding jellyseerr alone appends exactly 2 more tasks (on top of core)."""
    base = len(planned_task_names([]))
    with_js = len(planned_task_names(["jellyseerr"]))
    assert with_js == base + 2


def test_planned_task_names_with_bazarr_adds_three_tasks():
    """Adding bazarr appends exactly 3 more tasks."""
    base = len(planned_task_names([]))
    with_b = len(planned_task_names(["bazarr"]))
    assert with_b == base + 3


def test_planned_task_names_with_notifiarr_adds_two_tasks():
    """Adding notifiarr appends exactly 2 more tasks."""
    base = len(planned_task_names([]))
    with_n = len(planned_task_names(["notifiarr"]))
    assert with_n == base + 2


def test_planned_task_names_with_recyclarr_adds_one_task():
    """Adding recyclarr appends exactly 1 more task."""
    base = len(planned_task_names([]))
    with_r = len(planned_task_names(["recyclarr"]))
    assert with_r == base + 1


def test_planned_task_names_with_caddy_adds_one_task():
    """Adding caddy appends exactly 1 more task."""
    base = len(planned_task_names([]))
    with_c = len(planned_task_names(["caddy"]))
    assert with_c == base + 1


def test_planned_task_names_reads_from_state_when_none():
    """planned_task_names(None) reads enabled_services from saved settings."""
    state.set("settings", {"enabled_services": ["jellyfin"]})
    names_from_state = planned_task_names(None)
    names_explicit = planned_task_names(["jellyfin"])
    assert names_from_state == names_explicit


# ---------------------------------------------------------------------------
# Role-aware planning
# ---------------------------------------------------------------------------


def test_planned_task_names_seedbox_keeps_core_plus_retention():
    """Seedbox runs the full core plan plus the retention share-limit task."""
    names = planned_task_names([], role="seedbox")
    assert len(names) == _CORE_TASK_COUNT + 1
    assert "Connect to qBittorrent" in names
    assert "Set qBittorrent share limits" in names


def test_all_in_one_has_no_retention_task():
    """The retention task is seedbox-only, so all-in-one stays at the core count."""
    names = planned_task_names([], role="all_in_one")
    assert "Set qBittorrent share limits" not in names
    assert len(names) == _CORE_TASK_COUNT


def test_planned_task_names_receiver_has_no_core_tasks():
    """Receiver has no *arr stack — the core plan is empty."""
    assert planned_task_names([], role="receiver") == []


def test_planned_task_names_receiver_runs_only_optional_tasks():
    """A receiver running an optional service wires only that service."""
    names = planned_task_names(["jellyfin"], role="receiver")
    assert len(names) == 2  # the two jellyfin tasks, no core
    assert not any("Sonarr" in n or "qBittorrent" in n for n in names)


def test_planned_task_names_with_syncthing_adds_two_tasks():
    """Syncthing appends a wait + a configure task."""
    base = len(planned_task_names([]))
    assert len(planned_task_names(["syncthing"])) == base + 2


def test_receiver_with_syncthing_runs_only_syncthing_tasks():
    """A receiver + syncthing runs exactly the two Syncthing tasks, no core."""
    names = planned_task_names(["syncthing"], role="receiver")
    assert len(names) == 2
    assert all("Syncthing" in n for n in names)


def test_planned_task_names_with_gluetun_adds_one_task():
    """Gluetun appends the best-effort listen-port task."""
    base = len(planned_task_names([]))
    assert len(planned_task_names(["gluetun"])) == base + 1


def test_qb_host_is_gluetun_when_vpn_enabled():
    state.set("settings", {"enabled_services": ["gluetun"], "ports": {}})
    assert wiring_runner._build_context().qb_host == "gluetun"


def test_qb_host_defaults_to_qbittorrent():
    state.set("settings", {"enabled_services": [], "ports": {}})
    assert wiring_runner._build_context().qb_host == "qbittorrent"


# ---------------------------------------------------------------------------
# _build_task_plan — dataclass structure
# ---------------------------------------------------------------------------


def test_build_task_plan_returns_dataclass_instances():
    """Every item returned by _build_task_plan must be a WiringTask instance."""
    plan = _build_task_plan([])
    assert all(isinstance(t, WiringTask) for t in plan)


def test_initial_status_is_idle():
    """wiring_status() must report phase='idle' before start_wiring() is called."""
    status = wiring_runner.wiring_status()
    assert status["phase"] == "idle"


# ---------------------------------------------------------------------------
# _build_context — container vs host ports
# ---------------------------------------------------------------------------


def test_build_context_internal_urls_use_container_ports_not_host_ports():
    """Regression: a user who moves Sonarr to host port 8990 (because 8989
    is taken) still has Sonarr listening on 8989 *inside* the compose
    network. The *_internal URLs handed to Prowlarr/Bazarr/Recyclarr were
    built from the host port, so every cross-app call went to a port
    nothing listened on — while the wizard reported green."""
    state.set(
        "settings",
        {
            "ports": {"sonarr": 8990, "radarr": 7879, "prowlarr": 9697, "bazarr": 6768},
            "enabled_services": ["bazarr"],
        },
    )
    ctx = wiring_runner._build_context()
    assert ctx.sonarr_internal == "http://sonarr:8989"
    assert ctx.radarr_internal == "http://radarr:7878"
    assert ctx.prowlarr_internal == "http://prowlarr:9696"
    assert ctx.bazarr_internal == "http://bazarr:6767"
    # Host-side URLs still honour the user's override.
    assert ctx.sonarr_url == "http://localhost:8990"
    assert ctx.radarr_url == "http://localhost:7879"


def test_build_context_jellyseerr_internal_uses_container_port():
    """Jellyseerr's default host port is 5056 but it listens on 5055 inside."""
    state.set("settings", {"ports": {"jellyseerr": 5056}})
    assert wiring_runner._build_context().jellyseerr_internal == "http://jellyseerr:5055"


# ---------------------------------------------------------------------------
# _run_wiring — failures must be persisted and surfaced
# ---------------------------------------------------------------------------


def _prime_status(names):
    wiring_runner._status = {
        "phase": "running",
        "tasks": wiring_runner._initial_tasks(names),
        "error": "",
    }


def test_failed_task_is_persisted_for_the_repair_page(monkeypatch):
    """Regression: only successful runs wrote state['wiring'], so the repair
    page's 'Previously failed' list was permanently empty and a half-wired
    stack looked like wiring had never run."""
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.api_keys = {"sonarr": "abc", "jellyfin": "ignored"}
    ctx.settings = {"qbittorrent_username": "admin"}
    ctx.shared_password = "pw"
    ctx.syncthing_device_id = ""
    monkeypatch.setattr(wiring_runner, "_build_context", lambda: ctx)

    def boom(_ctx):
        raise RuntimeError("Prowlarr not reachable")

    plan = [
        WiringTask("Task one", lambda c: "ok", []),
        WiringTask("Task two", boom, []),
        WiringTask("Task three", lambda c: "never", []),
    ]
    _prime_status([t.name for t in plan])
    wiring_runner._run_wiring(plan)

    assert wiring_runner.wiring_status()["phase"] == "failed"
    saved = state.get("wiring")
    assert saved["status"] == "failed"
    by_name = {t["name"]: t for t in saved["tasks"]}
    assert by_name["Task one"]["status"] == "ok"
    assert by_name["Task two"]["status"] == "failed"
    assert "Prowlarr not reachable" in by_name["Task two"]["message"]
    assert by_name["Task three"]["status"] == "skipped"
    assert saved["api_keys"] == {"sonarr": "abc"}


def test_failed_rerun_keeps_api_keys_from_earlier_success(monkeypatch):
    from unittest.mock import MagicMock

    state.set("wiring", {"status": "complete", "api_keys": {"sonarr": "old", "radarr": "r"}})
    ctx = MagicMock()
    ctx.api_keys = {"sonarr": "new"}
    ctx.settings = {}
    ctx.shared_password = "pw"
    ctx.syncthing_device_id = ""
    monkeypatch.setattr(wiring_runner, "_build_context", lambda: ctx)

    def boom(_ctx):
        raise RuntimeError("nope")

    plan = [WiringTask("Only", boom, [])]
    _prime_status(["Only"])
    wiring_runner._run_wiring(plan)
    assert state.get("wiring")["api_keys"] == {"sonarr": "new", "radarr": "r"}


def test_context_build_failure_surfaces_error_and_skips_tasks(monkeypatch):
    """Regression: an exception outside any task (corrupt settings) set an
    'error' that nothing ever read, and left every task 'pending' with no
    explanation anywhere in the UI."""

    def bad_context():
        raise AttributeError("'list' object has no attribute 'get'")

    monkeypatch.setattr(wiring_runner, "_build_context", bad_context)
    plan = [WiringTask("Only", lambda c: "x", [])]
    _prime_status(["Only"])
    wiring_runner._run_wiring(plan)

    status = wiring_runner.wiring_status()
    assert status["phase"] == "failed"
    assert "'list' object has no attribute 'get'" in status["error"]
    assert status["tasks"][0]["status"] == "skipped"
    saved = state.get("wiring")
    assert saved["status"] == "failed"
    assert "attribute 'get'" in saved["error"]
