"""Custom exception types for Audiby components."""

__all__ = [
    "AudibyError",
    "AudioError",
    "TranscriptionError",
    "InjectionError",
    "HotkeyError",
    "ModelError",
]


class AudibyError(Exception):
    """Base exception for Audiby application errors."""


class AudioError(AudibyError):
    """Audio-related error."""


class TranscriptionError(AudibyError):
    """Speech transcription error."""


class InjectionError(AudibyError):
    """Text injection error."""


class HotkeyError(AudibyError):
    """Global hotkey backend error."""


class ModelError(AudibyError):
    """Model management error."""
