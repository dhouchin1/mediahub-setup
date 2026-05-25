"""Unit tests for mediahub_setup.recyclarr.

Tests config rendering and file-system write. HOME is redirected to
tmp_path to avoid touching ~/mediahub.
"""

from __future__ import annotations

import pytest

import mediahub_setup.recyclarr as recyclarr_mod
from mediahub_setup.recyclarr import render_recyclarr_config


@pytest.fixture(autouse=True)
def isolated_install_dir(tmp_path, monkeypatch):
    """Redirect INSTALL_DIR and RECYCLARR_CONFIG_DIR into tmp_path."""
    fake_install = tmp_path / "mediahub"
    fake_config = fake_install / "config" / "recyclarr"
    monkeypatch.setattr(recyclarr_mod, "INSTALL_DIR", fake_install)
    monkeypatch.setattr(recyclarr_mod, "RECYCLARR_CONFIG_DIR", fake_config)


def test_render_recyclarr_config_writes_yml_to_install_dir(tmp_path):
    """render_recyclarr_config() must write recyclarr.yml under config/recyclarr/."""
    path = render_recyclarr_config(
        sonarr_internal_url="http://sonarr:8989",
        sonarr_api_key="sonarr_key_abc",
        radarr_internal_url="http://radarr:7878",
        radarr_api_key="radarr_key_def",
    )
    assert path.exists()
    assert path.name == "recyclarr.yml"


def test_render_recyclarr_config_substitutes_api_keys_and_urls(tmp_path):
    """Written file must contain the supplied URLs and API keys."""
    path = render_recyclarr_config(
        sonarr_internal_url="http://sonarr:8989",
        sonarr_api_key="sonarr_key_abc",
        radarr_internal_url="http://radarr:7878",
        radarr_api_key="radarr_key_def",
    )
    text = path.read_text()
    assert "http://sonarr:8989" in text
    assert "sonarr_key_abc" in text
    assert "http://radarr:7878" in text
    assert "radarr_key_def" in text


def test_render_recyclarr_config_returns_path_to_written_file(tmp_path):
    """render_recyclarr_config() must return a Path pointing to the written file."""
    from pathlib import Path

    result = render_recyclarr_config(
        sonarr_internal_url="http://sonarr:8989",
        sonarr_api_key="k1",
        radarr_internal_url="http://radarr:7878",
        radarr_api_key="k2",
    )
    assert isinstance(result, Path)
    assert result.suffix == ".yml"
