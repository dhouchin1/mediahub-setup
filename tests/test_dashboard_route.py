"""Tests for mediahub_setup.routes.dashboard.

Uses the Flask test client with docker_ops helpers mocked out so no real
Docker daemon is required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mediahub_setup import state
from mediahub_setup.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Flask test client with clean state and Docker stubs."""
    state.clear()
    app = create_app()
    with (
        patch("mediahub_setup.docker_ops.list_containers", return_value=[]),
        patch("mediahub_setup.docker_ops.docker_stats", return_value=[]),
        patch("mediahub_setup.docker_ops.docker_available", return_value=False),
    ):
        yield app.test_client()
    state.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dashboard_index_renders_without_state(client):
    """Dashboard index must render 200 even with empty wizard state."""
    r = client.get("/dashboard/")
    assert r.status_code == 200


def test_dashboard_status_returns_partial(client):
    """GET /dashboard/status must return a partial (no <html> shell)."""
    r = client.get("/dashboard/status")
    assert r.status_code == 200
    assert b"<html" not in r.data


def test_dashboard_restart_rejects_non_mediahub_name(client):
    """POST /dashboard/restart with a non-mediahub- name must return 500."""
    r = client.post("/dashboard/restart", data={"name": "unrelated-container"})
    assert r.status_code == 500
    data = r.get_json()
    assert data["ok"] is False


def test_dashboard_logs_returns_400_for_invalid_name(client):
    """GET /dashboard/logs with no name must return 400."""
    r = client.get("/dashboard/logs")
    assert r.status_code == 400


def test_dashboard_logs_returns_400_for_non_numeric_tail(client):
    """GET /dashboard/logs with tail=abc must return 400, not 500."""
    r = client.get("/dashboard/logs?name=mediahub-sonarr&tail=abc")
    assert r.status_code == 400


def test_dashboard_logs_clamps_extreme_tail(client):
    """Huge or negative tail values are clamped before reaching docker logs."""
    with patch("mediahub_setup.docker_ops.container_logs", return_value="ok") as logs:
        client.get("/dashboard/logs?name=mediahub-sonarr&tail=99999999")
        client.get("/dashboard/logs?name=mediahub-sonarr&tail=-5")
    tails = [call.kwargs.get("tail") for call in logs.call_args_list]
    assert tails == [2000, 1]


def test_dashboard_update_all_kicks_off_update(client):
    """POST /dashboard/update-all must return 200 and the update partial."""
    with patch("mediahub_setup.docker_ops.compose_update_all", return_value=True):
        r = client.post("/dashboard/update-all")
    assert r.status_code == 200
