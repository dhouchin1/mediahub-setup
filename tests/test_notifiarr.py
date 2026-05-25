"""Unit tests for mediahub_setup.notifiarr.

Tests the config renderer only — no filesystem writes or Docker calls.
"""

from __future__ import annotations

from mediahub_setup.notifiarr import render_notifiarr_config

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_BASE_PORTS = {"qbittorrent_web": 8080}
_BASE_KEYS = {"sonarr": "sonarrkey123", "radarr": "radarrkey456"}
_PASSWORD = "SharedPass1234"


# ---------------------------------------------------------------------------
# Sonarr / Radarr sections
# ---------------------------------------------------------------------------


def test_render_notifiarr_config_includes_sonarr_when_key_present():
    """Config must include [[apps.sonarr]] when sonarr key is provided."""
    cfg = render_notifiarr_config(
        ports=_BASE_PORTS,
        api_keys=_BASE_KEYS,
        shared_password=_PASSWORD,
    )
    assert "[[apps.sonarr]]" in cfg
    assert "sonarrkey123" in cfg


def test_render_notifiarr_config_omits_sonarr_when_key_blank():
    """Config must omit [[apps.sonarr]] when sonarr api_key is empty."""
    cfg = render_notifiarr_config(
        ports=_BASE_PORTS,
        api_keys={"sonarr": "", "radarr": "radarrkey456"},
        shared_password=_PASSWORD,
    )
    assert "[[apps.sonarr]]" not in cfg


def test_render_notifiarr_config_includes_telegram_when_both_creds_present():
    """Config must include Telegram endpoint block when token + chat_id are provided."""
    cfg = render_notifiarr_config(
        ports=_BASE_PORTS,
        api_keys=_BASE_KEYS,
        shared_password=_PASSWORD,
        telegram_bot_token="botTOKEN123",
        telegram_chat_id="-100987654321",
    )
    assert "telegram" in cfg.lower()
    assert "botTOKEN123" in cfg
    assert "-100987654321" in cfg


def test_render_notifiarr_config_omits_telegram_when_token_blank():
    """Config must omit the Telegram block when token is empty."""
    cfg = render_notifiarr_config(
        ports=_BASE_PORTS,
        api_keys=_BASE_KEYS,
        shared_password=_PASSWORD,
        telegram_bot_token="",
        telegram_chat_id="-100987654321",
    )
    assert "telegram" not in cfg.lower()


def test_render_notifiarr_config_omits_telegram_when_chat_id_blank():
    """Config must omit the Telegram block when chat_id is empty."""
    cfg = render_notifiarr_config(
        ports=_BASE_PORTS,
        api_keys=_BASE_KEYS,
        shared_password=_PASSWORD,
        telegram_bot_token="botTOKEN123",
        telegram_chat_id="",
    )
    assert "telegram" not in cfg.lower()


# ---------------------------------------------------------------------------
# UI password
# ---------------------------------------------------------------------------


def test_render_notifiarr_config_uses_shared_password_for_ui():
    """Config must contain ui_password = 'admin:<shared_password>'."""
    cfg = render_notifiarr_config(
        ports=_BASE_PORTS,
        api_keys=_BASE_KEYS,
        shared_password="MySecurePass99",
    )
    assert "admin:MySecurePass99" in cfg


# ---------------------------------------------------------------------------
# qBittorrent port
# ---------------------------------------------------------------------------


def test_render_notifiarr_config_uses_qb_port_from_settings():
    """Config must use the qbittorrent_web port from ports dict."""
    cfg = render_notifiarr_config(
        ports={"qbittorrent_web": 9999},
        api_keys=_BASE_KEYS,
        shared_password=_PASSWORD,
    )
    assert "9999" in cfg
