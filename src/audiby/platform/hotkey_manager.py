"""Global hotkey abstraction - wraps pynput Listener for push-to-talk combo detection.

Translates OS-level key events into press/release callbacks for a configured
key combination. Platform-only module - contains no pipeline or business logic.
"""

import sys
from abc import ABC, abstractmethod
from collections.abc import Callable


class HotkeyManagerBase(ABC):
    """Abstract base class for platform-specific hotkey manager implementations."""

    @abstractmethod
    def __init__(self, hotkey_combo: str, on_press: Callable, on_release: Callable) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


def get_hotkey_manager(
    hotkey_combo: str, on_press: Callable, on_release: Callable
) -> HotkeyManagerBase:
    """Return a platform-specific hotkey manager instance using lazy backend imports."""
    if sys.platform == "win32":
        from audiby.platform._hotkey_win import WindowsHotkeyManager

        return WindowsHotkeyManager(hotkey_combo, on_press, on_release)
    if sys.platform == "darwin":
        from audiby.platform._hotkey_mac import MacHotkeyManager

        return MacHotkeyManager(hotkey_combo, on_press, on_release)
    raise NotImplementedError(f"Unsupported platform: {sys.platform}")
