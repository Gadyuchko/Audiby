"""Global hotkey abstraction — wraps pynput Listener for push-to-talk combo detection.

Translates OS-level key events into press/release callbacks for a configured
key combination. Platform-only module — contains no pipeline or business logic.

@author Roman Hadiuchko
"""

import logging
from collections.abc import Callable

from pynput.keyboard import Key, KeyCode, Listener

logger = logging.getLogger(__name__)

# Mapping from human-readable modifier names to pynput Key enums.
_MODIFIER_MAP: dict[str, Key] = {
    "alt": Key.alt_l,
    "ctrl": Key.ctrl_l,
    "shift": Key.shift_l,
}


class HotkeyManager:
    """Listens for a global key combo and forwards press/release signals.

    Uses pynput keyboard Listener to listen to combined presses and calls
    the specified callback on press and release.
    The combo is detected by tracking currently held keys against a parsed
    hotkey set. No business logic — only signal forwarding.

    @author Roman Hadiuchko
    """

    def __init__(self, hotkey: str, on_press: Callable, on_release: Callable) -> None:
        """Configure the hotkey combo and store callbacks.

        Args:
            hotkey: Key combination string, e.g. ``"alt+z"`` or ``"<ctrl>+a"``.
            on_press: Called once when the full combo is held down.
            on_release: Called once when any combo key is released.
        """
        if not hotkey:
            raise ValueError("Hotkey must be specified")
        self._hotkey_set = self._parse_hotkey(hotkey)
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
        except Exception as e:
            logger.error("Failed to start hotkey listener: %s", e)
            self._listener = None
            raise

    def stop(self) -> None:
        """Stop the key listener if running. Safe to call when not started."""
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_key_press(self, key) -> None:
        """We check if pressed key in configured combo, add it to pressed set and fire on_press callback in case set is equal to combo.
        """
        if key in self._hotkey_set:
            self._pressed.add(key)
        if self._hotkey_set == self._pressed and not self._combo_active:
            self._combo_active = True
            self._on_press()

    def _on_key_release(self, key) -> None:
        """We check if released key is part of configured combo, remove it from pressed set and fire on_release callback in this case"""
        if self._combo_active and key in self._hotkey_set:
            self._combo_active = False
            self._on_release()
        self._pressed.discard(key)

    @staticmethod
    def _parse_hotkey(hotkey: str) -> set:
        """Convert a hotkey string into a set of pynput key objects.

        Supports modifier names (alt, ctrl, shift) with optional angle brackets
        and single-character keys joined by ``+``.

        Examples::

            "alt+z"     → {Key.alt_l, KeyCode(char='z')}
            "<ctrl>+a"  → {Key.ctrl_l, KeyCode(char='a')}
        """
        keys: set = set()
        for part in hotkey.split("+"):
            part = part.strip().lower().strip("<>")  # "alt+z" → "alt", "<alt>+z" → "alt"
            if part in _MODIFIER_MAP:
                keys.add(_MODIFIER_MAP[part])
            elif len(part) == 1:
                keys.add(KeyCode.from_char(part))
            else:
                raise ValueError(f"Unknown hotkey component: '{part}'")
        return keys
