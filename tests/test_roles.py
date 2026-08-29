"""Unit tests for mediahub_setup.roles.

Covers role normalisation, the per-role capability helpers, and the
role-specific step flows.
"""

from __future__ import annotations

import pytest

from mediahub_setup import roles, state


@pytest.fixture(autouse=True)
def clean_state():
    """Isolate wizard state around every test."""
    state.clear()
    yield
    state.clear()


def test_default_role_is_all_in_one():
    assert roles.current() == roles.ALL_IN_ONE


def test_current_reads_role_from_state():
    state.set("role", "seedbox")
    assert roles.current() == roles.SEEDBOX


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, roles.ALL_IN_ONE),
        ("", roles.ALL_IN_ONE),
        ("all-in-one", roles.ALL_IN_ONE),
        ("ALL_IN_ONE", roles.ALL_IN_ONE),
        ("local", roles.ALL_IN_ONE),
        ("seedbox", roles.SEEDBOX),
        ("server", roles.SEEDBOX),
        ("vps", roles.SEEDBOX),
        ("receiver", roles.RECEIVER),
        ("home", roles.RECEIVER),
        ("nonsense", roles.ALL_IN_ONE),
    ],
)
def test_normalize(raw, expected):
    assert roles.normalize(raw) == expected


def test_installs_arr():
    assert roles.installs_arr(roles.ALL_IN_ONE) is True
    assert roles.installs_arr(roles.SEEDBOX) is True
    assert roles.installs_arr(roles.RECEIVER) is False


def test_is_server_only_seedbox():
    assert roles.is_server(roles.SEEDBOX) is True
    assert roles.is_server(roles.ALL_IN_ONE) is False
    assert roles.is_server(roles.RECEIVER) is False


def test_syncthing_folder_type():
    assert roles.syncthing_folder_type(roles.SEEDBOX) == "sendonly"
    assert roles.syncthing_folder_type(roles.RECEIVER) == "receiveonly"
    assert roles.syncthing_folder_type(roles.ALL_IN_ONE) is None


def test_forces_syncthing():
    assert roles.forces_syncthing(roles.SEEDBOX) is True
    assert roles.forces_syncthing(roles.RECEIVER) is True
    assert roles.forces_syncthing(roles.ALL_IN_ONE) is False


def test_receiver_flow_keeps_wiring_step():
    # The receiver's wiring plan carries the Syncthing tasks (receive-only
    # folder + forced versioning) — the wizard must run them, like headless.
    keys = [k for k, _ in roles.steps_for(roles.RECEIVER)]
    assert keys == ["welcome", "preflight", "drive", "settings", "install", "wiring", "done"]


def test_full_flows_have_seven_steps():
    assert len(roles.steps_for(roles.ALL_IN_ONE)) == 7
    assert len(roles.steps_for(roles.SEEDBOX)) == 7
    assert len(roles.steps_for(roles.RECEIVER)) == 7


def test_has_step():
    assert roles.has_step(roles.ALL_IN_ONE, "wiring") is True
    assert roles.has_step(roles.RECEIVER, "wiring") is True
    assert roles.has_step(roles.RECEIVER, "drive") is True
