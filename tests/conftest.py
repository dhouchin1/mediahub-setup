"""Shared test fixtures.

Redirect the persisted wizard state file to a per-test temp path so the
suite never reads or truncates the developer's real
~/.mediahub-setup-state.json (many tests call state.clear(), which
persists immediately).
"""

import pytest

from mediahub_setup import state


@pytest.fixture(autouse=True)
def _isolated_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state, "_state", {})
