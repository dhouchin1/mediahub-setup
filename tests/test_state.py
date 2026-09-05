"""Tests for state persistence.

The state file carries the shared password, VPN credentials, and service
API keys, so its on-disk permissions matter as much as its contents.
"""

from mediahub_setup import state


def test_state_file_is_owner_only():
    state.set("settings", {"shared_password": "hunter2"})
    assert (state._STATE_PATH.stat().st_mode & 0o777) == 0o600


def test_state_round_trip():
    state.set("role", "seedbox")
    assert state.get("role") == "seedbox"
    state.clear()
    assert state.get("role") is None
