"""Tests for platform-aware user-facing error dialogs."""

import sys

from audiby.ui import error_dialogs


def test_mic_permission_dialog_uses_windows_copy(monkeypatch, mocker) -> None:
    """Windows microphone guidance should point to the Windows settings path."""
    monkeypatch.setattr(sys, "platform", "win32")
    showerror = mocker.patch("tkinter.messagebox.showerror")

    error_dialogs.show_mic_permission_error()

    title, message = showerror.call_args.args
    assert "Microphone" in title
    assert "Settings > Privacy & Security > Microphone" in message


def test_hotkey_permission_dialog_uses_mac_copy(monkeypatch, mocker) -> None:
    """macOS hotkey guidance should point to Input Monitoring."""
    monkeypatch.setattr(sys, "platform", "darwin")
    showerror = mocker.patch("tkinter.messagebox.showerror")

    error_dialogs.show_hotkey_permission_error()

    title, message = showerror.call_args.args
    assert "Hotkey" in title
    assert "System Settings > Privacy & Security" in message
    assert "Input Monitoring" in message


def test_device_disconnect_dialog_uses_warning_with_generic_copy(monkeypatch, mocker) -> None:
    """Generic fallback copy should avoid platform-specific settings paths."""
    monkeypatch.setattr(sys, "platform", "linux")
    showwarning = mocker.patch("tkinter.messagebox.showwarning")

    error_dialogs.show_device_disconnected_warning()

    title, message = showwarning.call_args.args
    assert "Audio Device" in title
    assert "Reconnect" in message
    assert "Privacy & Security" not in message
