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
