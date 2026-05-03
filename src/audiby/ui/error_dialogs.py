"""Platform-aware blocking error dialogs for startup and device failures."""

import sys
from tkinter import messagebox


def show_mic_permission_error() -> None:
    """Show guidance for missing microphone permission."""
    title, message = _mic_permission_copy(sys.platform)
    messagebox.showerror(title, message)


def show_hotkey_permission_error() -> None:
    """Show guidance for missing global hotkey/input monitoring permission."""
    title, message = _hotkey_permission_copy(sys.platform)
    messagebox.showerror(title, message)


def show_device_disconnected_warning() -> None:
    """Show guidance for a disconnected or unavailable audio input device."""
    title, message = _device_disconnected_copy(sys.platform)
    messagebox.showwarning(title, message)


def _mic_permission_copy(platform: str) -> tuple[str, str]:
    if platform == "win32":
        return (
            "Microphone Access Needed",
            "Audiby cannot access your microphone. Open Settings > Privacy & Security > "
            "Microphone, allow microphone access, then restart Audiby.",
        )
    if platform == "darwin":
        return (
            "Microphone Access Needed",
            "Audiby cannot access your microphone. Open System Settings > Privacy & "
            "Security > Microphone, allow Audiby or the host app, then restart Audiby.",
        )
    return (
        "Microphone Access Needed",
        "Audiby cannot access your microphone. Check your system microphone permissions, "
        "then restart Audiby.",
    )


def _hotkey_permission_copy(platform: str) -> tuple[str, str]:
    if platform == "win32":
        return (
            "Hotkey Access Needed",
            "Audiby could not register the push-to-talk hotkey. Close apps that may be "
            "using the same shortcut, then restart Audiby.",
        )
    if platform == "darwin":
        return (
            "Hotkey Access Needed",
            "Audiby cannot monitor the push-to-talk hotkey. Open System Settings > "
            "Privacy & Security > Input Monitoring, allow Audiby or the host app, "
            "then restart Audiby.",
        )
    return (
        "Hotkey Access Needed",
        "Audiby could not register the push-to-talk hotkey. Check your system keyboard "
        "monitoring permissions, then restart Audiby.",
    )


def _device_disconnected_copy(platform: str) -> tuple[str, str]:
    if platform == "win32":
        return (
            "Audio Device Unavailable",
            "Audiby lost access to your microphone. Reconnect the device or choose a "
            "working default input in Windows sound settings, then try dictation again.",
        )
    if platform == "darwin":
        return (
            "Audio Device Unavailable",
            "Audiby lost access to your microphone. Reconnect the device or choose a "
            "working input in System Settings > Sound, then try dictation again.",
        )
    return (
        "Audio Device Unavailable",
        "Audiby lost access to your microphone. Reconnect the device or choose a "
        "working input device, then try dictation again.",
    )
