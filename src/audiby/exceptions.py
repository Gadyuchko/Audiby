"""Custom exception types for Audiby components."""

__all__ = [
    "AudibyError",
    "AudioError",
    "TranscriptionError",
    "InjectionError",
    "HotkeyError",
    "MicPermissionError",
    "AudioDeviceError",
    "HotkeyPermissionError",
    "ModelError",
]


class AudibyError(Exception):
    """Base exception for Audiby application errors."""


class AudioError(AudibyError):
    """Audio-related error."""


class MicPermissionError(AudioError):
    """Microphone permission is missing or denied by the OS."""


class AudioDeviceError(AudioError):
    """Audio device is unavailable, disconnected, or otherwise unusable."""


class TranscriptionError(AudibyError):
    """Speech transcription error."""


class InjectionError(AudibyError):
    """Text injection error."""


class HotkeyError(AudibyError):
    """Global hotkey backend error."""


class HotkeyPermissionError(HotkeyError):
    """Global hotkey permissions are missing or denied by the OS."""


class ModelError(AudibyError):
    """Model management error."""
