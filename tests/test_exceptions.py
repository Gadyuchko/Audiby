"""Tests for Audiby exception hierarchy contracts."""

import audiby.exceptions as exceptions
from audiby.exceptions import AudioError, HotkeyError


def test_permission_exceptions_are_exported() -> None:
    """Permission/device exceptions must be part of the public exception module API."""
    assert "MicPermissionError" in exceptions.__all__
    assert "AudioDeviceError" in exceptions.__all__
    assert "HotkeyPermissionError" in exceptions.__all__


def test_audio_permission_exceptions_inherit_audio_error() -> None:
    """Microphone and device failures must remain catchable as audio errors."""
    assert issubclass(exceptions.MicPermissionError, AudioError)
    assert issubclass(exceptions.AudioDeviceError, AudioError)


def test_hotkey_permission_exception_inherits_hotkey_error() -> None:
    """Hotkey permission failures must remain catchable as hotkey errors."""
    assert issubclass(exceptions.HotkeyPermissionError, HotkeyError)
