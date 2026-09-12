"""Windows implementation of hotkey manager."""

import logging
from pynput.keyboard import Key, KeyCode
from audiby.constants import CONTROL_CHAR_TO_VK_OFFSET
from audiby.platform.hotkey_manager import HotkeyManagerBase
from audiby.platform.keycodes import vk_for_token

logger = logging.getLogger(__name__)

class WindowsHotkeyManager(HotkeyManagerBase):
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

        # Prefer the virtual key code: it names the physical key, while `char`
        # is only what the active layout prints on it. Matching by character
        # makes a combo stop firing the moment the user switches layout - the
        # physical "D" key reports "d" on en-US but a Cyrillic letter on uk-UA.
        # VK codes for modifiers can also show up here, so collapse those to
        # generic ctrl/alt/shift as well.
        if isinstance(key, KeyCode) and key.vk is not None:
            if key.vk in (162, 163):
                return Key.ctrl
            if key.vk in (164, 165):
                return Key.alt
            if key.vk in (160, 161):
                return Key.shift
            return KeyCode.from_vk(key.vk)

        # No virtual key code available - fall back to the character.
        # Ctrl+letter arrives as a control char, which maps onto the letter's
        # virtual key so it still matches a combo parsed from config.
        if isinstance(key, KeyCode) and key.char:
            codepoint = ord(key.char)
            if 1 <= codepoint <= 26:
                return KeyCode.from_vk(codepoint + CONTROL_CHAR_TO_VK_OFFSET)
            vk = vk_for_token(key.char)
            if vk is not None:
                return KeyCode.from_vk(vk)
            # Punctuation has no layout-independent code - keep the character.
            return KeyCode.from_char(key.char.lower())
        return key

