"""MacOS implementation of hotkey manager."""
import logging
from pynput.keyboard import Key, KeyCode
from audiby.platform.hotkey_manager import HotkeyManagerBase

logger = logging.getLogger(__name__)

class MacHotkeyManager(HotkeyManagerBase):

    def _normalize_key(self, key):
        """Convert different key representations into one consistent form.

        Why this exists:
        - MacOS/pynput can report the same physical key in different ways
          (for example ctrl vs ctrl_l vs ctrl_r).
        - We want hotkey matching to be stable and predictable.
        """
        # Treat left/right modifier variants as the same key.
        if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
            return Key.ctrl
        if key in (Key.alt, Key.alt_l, Key.alt_r):
            return Key.alt
        if key in (Key.shift, Key.shift_l, Key.shift_r):
            return Key.shift

        # Letter keys may come as chars. Normalize to lowercase.
        # Ctrl+letter can come as control chars (\x01..\x1a), so map them back to a..z.
        if isinstance(key, KeyCode) and key.char:
            codepoint = ord(key.char)
            if 1 <= codepoint <= 26:
                # 1->a, 2->b, ..., 26->z
                return KeyCode.from_char(chr(codepoint + 96))
            return KeyCode.from_char(key.char.lower())
        return key

