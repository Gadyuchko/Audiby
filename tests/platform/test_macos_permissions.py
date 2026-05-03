"""Tests for macOS permission preflight messaging and detection."""

import pytest

from audiby.exceptions import HotkeyPermissionError
from audiby.platform.macos_permissions import ensure_mac_input_permissions


def test_non_mac_preflight_is_noop(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    ensure_mac_input_permissions()


def test_mac_preflight_raises_with_clear_message(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "darwin")
    mocker.patch(
        "audiby.platform.macos_permissions.get_missing_mac_input_permissions",
        return_value=["Accessibility", "Input Monitoring"],
    )

    with pytest.raises(HotkeyPermissionError) as exc:
        ensure_mac_input_permissions()

    message = str(exc.value)
    assert "Accessibility" in message
    assert "Input Monitoring" in message
    assert "System Settings > Privacy & Security" in message


def test_mac_preflight_passes_when_permissions_granted(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "darwin")
    mocker.patch(
        "audiby.platform.macos_permissions.get_missing_mac_input_permissions",
        return_value=[],
    )

    ensure_mac_input_permissions()
