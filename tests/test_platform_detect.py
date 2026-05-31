"""Unit tests for mediahub_setup.platform_detect.

Verifies that is_macos/is_linux dispatch through the module-level
``system()`` so a single monkeypatch flips every platform branch.
"""

from __future__ import annotations

from mediahub_setup import platform_detect


def test_system_delegates_to_stdlib(monkeypatch):
    monkeypatch.setattr(platform_detect._platform, "system", lambda: "Linux")
    assert platform_detect.system() == "Linux"


def test_is_macos_true_on_darwin(monkeypatch):
    monkeypatch.setattr(platform_detect, "system", lambda: "Darwin")
    assert platform_detect.is_macos() is True
    assert platform_detect.is_linux() is False


def test_is_linux_true_on_linux(monkeypatch):
    monkeypatch.setattr(platform_detect, "system", lambda: "Linux")
    assert platform_detect.is_linux() is True
    assert platform_detect.is_macos() is False


def test_neither_on_windows(monkeypatch):
    monkeypatch.setattr(platform_detect, "system", lambda: "Windows")
    assert platform_detect.is_macos() is False
    assert platform_detect.is_linux() is False
