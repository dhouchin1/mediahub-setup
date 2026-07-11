"""Unit tests for mediahub_setup.caddy.

Tests Caddyfile rendering in both ``local`` (default, per-port + IP
allowlist) and ``public`` (path-routed + auto-HTTPS) modes. ``HOME`` is
redirected to ``tmp_path`` to avoid touching ``~/mediahub``.
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


# ---------------------------------------------------------------------------
# Local mode (the new default)
# ---------------------------------------------------------------------------


def test_local_mode_emits_per_port_site_blocks(tmp_path):
    """Each core service gets its own :port block in local mode."""
    path = render_caddyfile(enabled=[], ports={}, mode="local")
    text = path.read_text()
    # Each core service should have a site block on its default container port.
    assert ":8989 {" in text  # sonarr
    assert ":7878 {" in text  # radarr
    assert ":9696 {" in text  # prowlarr
    assert ":8090 {" in text  # qbittorrent (new default)


def test_local_mode_emits_ip_allowlist_snippet(tmp_path):
    """Local mode must include the (local_only) IP allowlist snippet."""
    path = render_caddyfile(enabled=[], ports={}, mode="local")
    text = path.read_text()
    assert "(local_only)" in text
    assert "import local_only" in text
    assert "100.64.0.0/10" in text  # Tailscale CGNAT range
    assert "192.168.0.0/16" in text  # RFC1918
    assert "10.0.0.0/8" in text


def test_local_mode_includes_web_when_enabled(tmp_path):
    """The custom MediaHub web UI gets its own :3000 site block."""
    path = render_caddyfile(enabled=["web"], ports={}, mode="local")
    text = path.read_text()
    assert ":3000 {" in text
    assert "reverse_proxy web:3000" in text


def test_local_mode_includes_syncthing_when_enabled(tmp_path):
    """Syncthing gets its own :8384 site block fronted by Caddy."""
    path = render_caddyfile(enabled=["syncthing"], ports={}, mode="local")
    text = path.read_text()
    assert ":8384 {" in text
    assert "reverse_proxy syncthing:8384" in text


def test_qbittorrent_upstream_overridden_for_gluetun(tmp_path):
    """When qBittorrent egresses through Gluetun, Caddy proxies to gluetun."""
    path = render_caddyfile(enabled=[], ports={}, mode="local", qbittorrent_host="gluetun")
    text = path.read_text()
    assert "reverse_proxy gluetun:8090" in text
    assert "reverse_proxy qbittorrent:8090" not in text


def test_local_mode_honors_host_port_overrides(tmp_path):
    """Custom ports override the default host-side port."""
    path = render_caddyfile(enabled=[], ports={"sonarr": 18989}, mode="local")
    text = path.read_text()
    # Site block (column-anchored) is on the overridden port.
    assert "\n:18989 {" in text
    # The default sonarr site block must not be emitted.
    assert "\n:8989 {" not in text
    # The internal reverse-proxy target still points at the container's 8989.
    assert "reverse_proxy sonarr:8989" in text


# ---------------------------------------------------------------------------
# Public mode (legacy single-host path-routed)
# ---------------------------------------------------------------------------


def test_public_mode_uses_http_prefix_for_local_domain(tmp_path):
    """A .local domain must use http:// prefix in the site address block."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={}, mode="public")
    text = path.read_text()
    assert "http://mediahub.local" in text


def test_public_mode_uses_bare_domain_for_public(tmp_path):
    """A public domain must appear as a bare hostname (no http:// prefix)."""
    path = render_caddyfile(domain="media.example.com", enabled=[], ports={}, mode="public")
    text = path.read_text()
    assert "media.example.com {" in text
    assert "http://media.example.com" not in text


def test_public_mode_includes_core_services_always(tmp_path):
    """Core services must always be present."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={}, mode="public")
    text = path.read_text()
    for svc in ("sonarr", "radarr", "prowlarr", "qbittorrent"):
        assert svc in text, f"{svc!r} missing from Caddyfile"


def test_public_mode_includes_jellyfin_when_enabled(tmp_path):
    """Jellyfin route block must appear when 'jellyfin' is in enabled."""
    path = render_caddyfile(domain="mediahub.local", enabled=["jellyfin"], ports={}, mode="public")
    text = path.read_text()
    assert "/jellyfin" in text


def test_public_mode_excludes_jellyfin_when_not_enabled(tmp_path):
    """Jellyfin route block must be absent when 'jellyfin' is not in enabled."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={}, mode="public")
    text = path.read_text()
    assert "/jellyfin/" not in text


def test_public_mode_landing_prefers_overseerr(tmp_path):
    """When Overseerr is enabled it wins the bare-path landing."""
    path = render_caddyfile(domain="mediahub.local", enabled=["overseerr"], ports={}, mode="public")
    text = path.read_text()
    assert "redir /overseerr/" in text


def test_public_mode_landing_falls_back_to_jellyseerr(tmp_path):
    """Jellyseerr is used as the landing if Overseerr is not enabled."""
    path = render_caddyfile(
        domain="mediahub.local", enabled=["jellyseerr"], ports={}, mode="public"
    )
    text = path.read_text()
    assert "redir /jellyseerr/" in text


def test_public_mode_landing_falls_back_to_sonarr(tmp_path):
    """Sonarr is the final fallback when no request app is enabled."""
    path = render_caddyfile(domain="mediahub.local", enabled=[], ports={}, mode="public")
    text = path.read_text()
    assert "redir /sonarr/" in text


def test_public_mode_web_handles_root(tmp_path):
    """When the MediaHub web UI is enabled it serves the bare path in public mode."""
    path = render_caddyfile(domain="mediahub.local", enabled=["web"], ports={}, mode="public")
    text = path.read_text()
    assert "reverse_proxy web:3000" in text


def test_qbittorrent_upstream_port_follows_webui_port_override(tmp_path):
    """qBittorrent's container listens on WEBUI_PORT (user-driven), so a port
    override must change the reverse-proxy upstream, not just the site port."""
    out = render_caddyfile(
        enabled=[],
        ports={"qbittorrent_web": 9090},
        mode="local",
    )
    text = out.read_text()
    assert "reverse_proxy qbittorrent:9090" in text
    assert ":8090" not in text
