"""Unit tests for mediahub_setup.caddy.

Tests Caddyfile rendering. HOME is redirected to tmp_path to avoid
touching ~/mediahub.
"""

from __future__ import annotations

import pytest

import mediahub_setup.caddy as caddy_mod
from mediahub_setup.caddy import render_caddyfile


@pytest.fixture(autouse=True)
def isolated_install_dir(tmp_path, monkeypatch):
    """Redirect INSTALL_DIR and CADDY_CONFIG_DIR into tmp_path."""
    fake_install = tmp_path / "mediahub"
    fake_config = fake_install / "config" / "caddy"
    monkeypatch.setattr(caddy_mod, "INSTALL_DIR", fake_install)
    monkeypatch.setattr(caddy_mod, "CADDY_CONFIG_DIR", fake_config)


def test_render_caddyfile_uses_http_prefix_for_local_domain(tmp_path):
    """A .local domain must use http:// prefix in the site address block."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={})
    text = path.read_text()
    assert "http://mediahub.local" in text
    # Must NOT have bare domain without http:// scheme
    assert text.count("mediahub.local {") == 0 or "http://mediahub.local {" in text


def test_render_caddyfile_uses_bare_domain_for_public(tmp_path):
    """A public domain must appear as a bare hostname (no http:// prefix)."""
    path = render_caddyfile(domain="media.example.com", enabled=[], ports={})
    text = path.read_text()
    assert "media.example.com {" in text
    assert "http://media.example.com" not in text


def test_render_caddyfile_includes_core_services_always(tmp_path):
    """Core services (sonarr, radarr, prowlarr, qbittorrent) must always be present."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={})
    text = path.read_text()
    for svc in ("sonarr", "radarr", "prowlarr", "qbittorrent"):
        assert svc in text, f"{svc!r} missing from Caddyfile"


def test_render_caddyfile_includes_jellyfin_when_enabled(tmp_path):
    """Jellyfin route block must appear when 'jellyfin' is in enabled."""
    path = render_caddyfile(domain="mediahub.local", enabled=["jellyfin"], ports={})
    text = path.read_text()
    assert "jellyfin" in text


def test_render_caddyfile_excludes_jellyfin_when_not_enabled(tmp_path):
    """Jellyfin route block must be absent when 'jellyfin' is not in enabled."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={})
    text = path.read_text()
    assert "/jellyfin/" not in text


def test_render_caddyfile_redirects_to_jellyseerr_when_enabled(tmp_path):
    """Root redirect must point to /jellyseerr/ when jellyseerr is enabled."""
    path = render_caddyfile(domain="mediahub.local", enabled=["jellyseerr"], ports={})
    text = path.read_text()
    assert "/jellyseerr/" in text


def test_render_caddyfile_redirects_to_sonarr_when_no_jellyseerr(tmp_path):
    """Root redirect must fall back to /sonarr/ when jellyseerr is not enabled."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={})
    text = path.read_text()
    assert "redir /sonarr/" in text
