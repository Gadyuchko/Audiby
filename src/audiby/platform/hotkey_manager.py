"""Global hotkey abstraction - wraps pynput Listener for push-to-talk combo detection.

Translates OS-level key events into press/release callbacks for a configured
key combination. Platform-only module - contains no pipeline or business logic.
"""
import logging
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from pynput.keyboard import HotKey, Listener
from audiby.exceptions import HotkeyError

logger = logging.getLogger(__name__)

class HotkeyManagerBase(ABC):
    """Abstract base class for platform-specific hotkey manager implementations.
    Listens for a global key combo and forwards press/release signals."""

    def __init__(self, hotkey_combo: str, on_press: Callable, on_release: Callable) -> None:
        """Configure the hotkey combo and store callbacks."""
        if not hotkey_combo:
            raise ValueError("Hotkey must be specified")
        self._hotkey_set = {self._normalize_key(key) for key in self._parse_hotkey(hotkey_combo)}
        self._on_press = on_press
        self._on_release = on_release
        self._listener: Listener | None = None
        self._pressed: set = set()
        self._combo_active = False

    def start(self) -> None:
        """Create and start the OS-level key listener (non-blocking daemon thread)."""
        self._listener = Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        try:
            self._listener.start()
            logger.info("Hotkey listener started (combo: %s)", self._hotkey_set)
        except Exception as e:
            logger.error("Failed to start hotkey listener: %s", e)
            self._listener = None
            raise HotkeyError("Failed to start hotkey listener") from e

    def stop(self) -> None:
        """Stop the key listener if running. Safe to call when not started."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_key_press(self, key) -> None:
        """Track combo state and fire on_press when full combo is held."""
        key = self._normalize_key(key)
        if key in self._hotkey_set:
            self._pressed.add(key)
        if self._hotkey_set == self._pressed and not self._combo_active:
            self._combo_active = True
            logger.debug("Combo activated - firing press callback")
            self._on_press()

    def _on_key_release(self, key) -> None:
        """Track combo release and fire on_release when combo breaks."""
        key = self._normalize_key(key)
        if self._combo_active and key in self._hotkey_set:
            self._combo_active = False
            logger.debug("Combo deactivated - firing release callback")
            self._on_release()
        self._pressed.discard(key)

    @staticmethod
    def _parse_hotkey(hotkey: str) -> set:
        """Convert a hotkey string into a normalized set of pynput key objects."""
        normalized_parts = []
        for part in hotkey.split("+"):
            token = part.strip().lower().strip("<>")
            if not token:
                continue
            normalized_parts.append(f"<{token}>" if len(token) > 1 else token)
        if not normalized_parts:
            raise ValueError("Hotkey must contain at least one key")

        parsed = HotKey.parse("+".join(normalized_parts))
        return set(parsed)

    @abstractmethod
    def _normalize_key(self, key): ...  # platform-specific

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
