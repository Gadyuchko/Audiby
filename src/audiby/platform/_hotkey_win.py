"""Windows implementation of hotkey manager."""

import logging
from collections.abc import Callable

from pynput.keyboard import HotKey, Key, KeyCode, Listener

from audiby.exceptions import HotkeyError
from audiby.platform.hotkey_manager import HotkeyManagerBase

logger = logging.getLogger(__name__)

class WindowsHotkeyManager(HotkeyManagerBase):
    """Listens for a global key combo and forwards press/release signals."""

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

    def _normalize_key(self, key):
        """Convert different key representations into one consistent form.

        Why this exists:
        - Windows/pynput can report the same physical key in different ways
          (for example ctrl vs ctrl_l vs ctrl_r, or VK codes).
        - We want hotkey matching to be stable and predictable.
        """
        # Treat left/right modifier variants as the same key.
        if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
            return Key.ctrl
        if key in (Key.alt, Key.alt_l, Key.alt_r):
            return Key.alt
        if key in (Key.shift, Key.shift_l, Key.shift_r):
            return Key.shift

        # Some special keys come as enum values with a Windows VK code.
        if isinstance(key, Key):
            vk = getattr(key.value, "vk", None)
            if vk is not None:
                return KeyCode.from_vk(vk)
            return key

        # Letter keys may come as chars. Normalize to lowercase.
        # Ctrl+letter can come as control chars (\x01..\x1a), so map them back to a..z.
        if isinstance(key, KeyCode) and key.char:
            codepoint = ord(key.char)
            if 1 <= codepoint <= 26:
                # 1->a, 2->b, ..., 26->z
                return KeyCode.from_char(chr(codepoint + 96))
            return KeyCode.from_char(key.char.lower())

        # VK codes for modifiers can also show up as KeyCode values.
        # Collapse those to generic ctrl/alt/shift as well.
        if isinstance(key, KeyCode) and key.vk is not None:
            if key.vk in (162, 163):
                return Key.ctrl
            if key.vk in (164, 165):
                return Key.alt
            if key.vk in (160, 161):
                return Key.shift
            return KeyCode.from_vk(key.vk)
        return key

