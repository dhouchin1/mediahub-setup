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


def test_render_recyclarr_config_uses_default_profiles_when_unspecified(tmp_path):
    """When no profiles are passed, the safe defaults (web-1080p + hd-bluray-web) appear."""
    path = render_recyclarr_config(
        sonarr_internal_url="http://sonarr:8989",
        sonarr_api_key="k1",
        radarr_internal_url="http://radarr:7878",
        radarr_api_key="k2",
    )
    text = path.read_text()
    assert "sonarr-v4-quality-profile-web-1080p" in text
    assert "radarr-quality-profile-hd-bluray-web" in text


def test_render_recyclarr_config_includes_selected_profile_templates(tmp_path):
    """Each selected profile contributes both its quality-profile and custom-formats templates."""
    path = render_recyclarr_config(
        sonarr_internal_url="http://sonarr:8989",
        sonarr_api_key="k1",
        radarr_internal_url="http://radarr:7878",
        radarr_api_key="k2",
        selected_profiles={"sonarr": ["anime"], "radarr": ["uhd-bluray-web"]},
    )
    text = path.read_text()
    assert "sonarr-v4-quality-profile-anime" in text
    assert "sonarr-v4-custom-formats-anime" in text
    assert "radarr-quality-profile-uhd-bluray-web" in text
    assert "radarr-custom-formats-uhd-bluray-web" in text
    # Unselected defaults should NOT leak in
    assert "sonarr-v4-quality-profile-web-1080p" not in text
    assert "radarr-quality-profile-hd-bluray-web" not in text


def test_render_recyclarr_config_ignores_unknown_profile_keys(tmp_path):
    """Unknown keys silently drop instead of crashing the wiring step."""
    path = render_recyclarr_config(
        sonarr_internal_url="http://sonarr:8989",
        sonarr_api_key="k1",
        radarr_internal_url="http://radarr:7878",
        radarr_api_key="k2",
        selected_profiles={"sonarr": ["does-not-exist", "anime"], "radarr": []},
    )
    text = path.read_text()
    assert "sonarr-v4-quality-profile-anime" in text
    assert "does-not-exist" not in text


def test_default_recyclarr_profiles_returns_known_keys():
    """Default selection only references keys that actually exist in the catalog."""
    from mediahub_setup.recyclarr import (
        RADARR_PROFILES,
        SONARR_PROFILES,
        default_recyclarr_profiles,
    )

    defaults = default_recyclarr_profiles()
    assert all(k in SONARR_PROFILES for k in defaults["sonarr"])
    assert all(k in RADARR_PROFILES for k in defaults["radarr"])
