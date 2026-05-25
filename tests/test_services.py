"""Unit tests for mediahub_setup.services.

Tests the declarative service catalog: core/optional keys, dependency
resolution, port map helpers, and required-field validation.
"""

from __future__ import annotations

from mediahub_setup import services


def test_core_keys_returns_four():
    """core_keys() must contain exactly prowlarr, sonarr, radarr, qbittorrent."""
    keys = services.core_keys()
    assert set(keys) == {"prowlarr", "sonarr", "radarr", "qbittorrent"}
    assert len(keys) == 4


def test_optional_keys_includes_expected():
    """optional_keys() must include jellyfin, jellyseerr, bazarr and others."""
    keys = services.optional_keys()
    for expected in ("jellyfin", "jellyseerr", "bazarr", "flaresolverr", "notifiarr", "recyclarr"):
        assert expected in keys, f"expected {expected!r} in optional_keys()"


def test_resolve_dependencies_adds_jellyfin_when_jellyseerr_chosen():
    """Choosing jellyseerr must auto-add jellyfin (it's a dependency)."""
    result = services.resolve_dependencies(["jellyseerr"])
    assert "jellyfin" in result
    assert "jellyseerr" in result


def test_resolve_dependencies_is_idempotent():
    """Running resolve_dependencies twice gives the same result."""
    first = services.resolve_dependencies(["jellyseerr", "bazarr"])
    second = services.resolve_dependencies(first)
    assert first == second


def test_resolve_dependencies_filters_unknown_keys():
    """Unknown service keys must be silently dropped."""
    result = services.resolve_dependencies(["jellyfin", "made_up_service"])
    assert "made_up_service" not in result
    assert "jellyfin" in result


def test_default_ports_for_includes_qbittorrent_bt_when_qbittorrent():
    """default_ports_for() adds qbittorrent_bt entry when qbittorrent is in keys."""
    ports = services.default_ports_for(services.core_keys())
    assert "qbittorrent_bt" in ports
    assert ports["qbittorrent_bt"] == 6881


def test_enabled_keys_preserves_catalog_order():
    """enabled_keys() must return core first, then optionals in catalog order."""
    enabled = services.enabled_keys(["bazarr", "jellyfin"])
    # Core must come first as a block
    core = services.core_keys()
    for i, k in enumerate(core):
        assert enabled[i] == k, f"position {i}: expected core key {k!r}"
    # Optional tail must appear in the order they appear in optional_keys()
    optional_in_result = [k for k in enabled if k not in core]
    catalog_order = [k for k in services.optional_keys() if k in optional_in_result]
    assert optional_in_result == catalog_order


def test_all_services_have_required_fields():
    """Every entry in services.ALL must define name, role, image, container_name, color."""
    required = ("name", "role", "image", "container_name", "color")
    for key, svc in services.ALL.items():
        for field in required:
            assert field in svc and svc[field], (
                f"services.ALL[{key!r}] missing or empty field {field!r}"
            )
