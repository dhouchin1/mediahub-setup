"""Tests for mediahub_setup.state — the persisted wizard state file.

The state path is redirected into tmp_path so nothing touches the real
~/.mediahub-setup-state.json.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from mediahub_setup import state


@pytest.fixture(autouse=True)
def isolated_state_path(tmp_path, monkeypatch):
    path = tmp_path / ".mediahub-setup-state.json"
    monkeypatch.setattr(state, "_STATE_PATH", path)
    monkeypatch.setattr(state, "_state", {})
    yield path
    monkeypatch.setattr(state, "_state", {})


def test_set_persists_json_and_get_reads_it_back(isolated_state_path):
    state.set("role", "seedbox")
    state.update(drive={"mount_path": "/mnt/x"})
    assert state.get("role") == "seedbox"
    assert json.loads(isolated_state_path.read_text()) == {
        "role": "seedbox",
        "drive": {"mount_path": "/mnt/x"},
    }


def test_state_file_is_owner_only(isolated_state_path):
    """The file carries plaintext passwords and VPN keys."""
    state.set("settings", {"shared_password": "hunter2"})
    mode = stat.S_IMODE(os.stat(isolated_state_path).st_mode)
    assert mode == 0o600


def test_save_tightens_a_pre_existing_world_readable_file(isolated_state_path):
    isolated_state_path.write_text("{}")
    isolated_state_path.chmod(0o644)
    state.set("k", 1)
    assert stat.S_IMODE(os.stat(isolated_state_path).st_mode) == 0o600


def test_save_is_atomic_and_leaves_no_temp_file(isolated_state_path):
    state.set("k", 1)
    leftovers = [p.name for p in isolated_state_path.parent.iterdir()]
    assert leftovers == [isolated_state_path.name]


def test_save_failure_is_non_fatal_and_cleans_temp(isolated_state_path, monkeypatch):
    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(state.os, "replace", fail_replace)
    state.set("k", 1)  # must not raise
    assert state.get("k") == 1  # in-memory value survives
    assert not isolated_state_path.exists()
    assert not any(p.name.endswith(".tmp") for p in isolated_state_path.parent.iterdir())


@pytest.mark.parametrize("payload", ["null", "[]", '"just a string"', "42"])
def test_load_ignores_json_that_is_not_an_object(isolated_state_path, payload):
    """Regression: `null`/`[]` parsed fine and made every state.get() raise
    AttributeError on the first request — a 500 on every page with no
    in-app recovery."""
    isolated_state_path.write_text(payload)
    state._load()
    assert state.snapshot() == {}
    assert state.get("role") is None


def test_load_ignores_truncated_file(isolated_state_path):
    isolated_state_path.write_text('{"role": "seed')
    state._load()
    assert state.snapshot() == {}


def test_clear_empties_file(isolated_state_path):
    state.set("k", 1)
    state.clear()
    assert json.loads(isolated_state_path.read_text()) == {}
