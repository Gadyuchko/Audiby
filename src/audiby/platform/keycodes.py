"""Layout-independent key identity helpers.

Windows names a key in two different ways, and only one of them is stable:

- by character - what the active keyboard layout prints on the key. Resolved
  through ``VkKeyScan`` when sending and ``MapVirtualKey`` when capturing, both
  of which read the *calling thread's* layout. The physical "D" key is "d" on
  en-US and "в" on uk-UA.
- by virtual key code - what the physical key is. Letters and digits occupy
  fixed ranges (``VK_A``..``VK_Z``, ``VK_0``..``VK_9``) on every layout, so the
  code is derivable by arithmetic with no layout lookup at all.

Everything that has to survive a layout switch - the paste chord, the captured
hotkey, and hotkey matching at runtime - identifies keys by virtual key code.
These helpers convert between the two forms for the ASCII range where the
mapping is guaranteed; callers fall back to character handling for anything
else (OEM punctuation), where no layout-independent answer exists.
"""

import ctypes
import logging
import sys
from ctypes import wintypes

from audiby.constants import (
    EN_US_LAYOUT_ID,
    KLF_NOTELLSHELL,
    MAPVK_VK_TO_CHAR,
    VK_0,
    VK_9,
    VK_A,
    VK_TOKEN_PREFIX,
    VK_Z,
)

logger = logging.getLogger(__name__)

# Cached US-English layout handle; None once a load has been tried and failed.
_en_us_layout_handle = None
_en_us_layout_loaded = False


def vk_for_token(token: str) -> int | None:
    """Return the virtual key code for a single ASCII letter or digit.

    Returns None for anything outside that range, where the caller must fall
    back to character handling.
    """
    if not token or len(token) != 1 or not token.isascii():
        return None
    if token.isalpha():
        return ord(token.upper())
    if token.isdigit():
        return ord(token)
    return None


def token_for_vk(vk: int) -> str | None:
    """Return the lowercase ASCII letter or digit a virtual key code names.

    Returns None for codes outside the letter and digit ranges.
    """
    if not isinstance(vk, int):
        return None
    if VK_0 <= vk <= VK_9 or VK_A <= vk <= VK_Z:
        return chr(vk).lower()
    return None


def token_from_vk(vk: int) -> str:
    """Render a virtual key code as a config token, e.g. 192 -> "vk192"."""
    return f"{VK_TOKEN_PREFIX}{vk}"


def vk_from_token(token: str) -> int | None:
    """Parse a "vk<code>" config token back into a virtual key code.

    Returns None for any other token, including plain letters and digits,
    which callers resolve through :func:`vk_for_token` instead.
    """
    if not token or not token.lower().startswith(VK_TOKEN_PREFIX):
        return None
    digits = token[len(VK_TOKEN_PREFIX):]
    if not digits.isdigit():
        return None
    return int(digits)


def _load_en_us_layout():
    """Return a cached US-English layout handle, or None if unavailable.

    KLF_NOTELLSHELL keeps the load from announcing a layout change, so reading
    a label never switches the layout the user is actually typing in.
    """
    global _en_us_layout_handle, _en_us_layout_loaded
    if _en_us_layout_loaded:
        return _en_us_layout_handle

    _en_us_layout_loaded = True
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # Handles are pointer-sized; the default c_int restype truncates them
        # on 64-bit Windows and yields an invalid handle.
        user32.LoadKeyboardLayoutW.argtypes = (wintypes.LPCWSTR, wintypes.UINT)
        user32.LoadKeyboardLayoutW.restype = ctypes.c_void_p
        _en_us_layout_handle = user32.LoadKeyboardLayoutW(
            EN_US_LAYOUT_ID, KLF_NOTELLSHELL
        )
    except Exception:
        logger.debug("US-English layout unavailable for hotkey labels", exc_info=True)
        _en_us_layout_handle = None
    return _en_us_layout_handle


def english_char_for_vk(vk: int) -> str | None:
    """Return the character the US-English layout prints on a virtual key.

    Used only to label a stored VK code in the settings window, so a hotkey
    captured on any layout still reads as "ctrl+`" rather than "ctrl+vk192".
    Returns None when the code has no printable US-English character.
    """
    if sys.platform != "win32":
        return None
    layout = _load_en_us_layout()
    if not layout:
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MapVirtualKeyExW.argtypes = (wintypes.UINT, wintypes.UINT, ctypes.c_void_p)
        user32.MapVirtualKeyExW.restype = wintypes.UINT
        mapped = user32.MapVirtualKeyExW(vk, MAPVK_VK_TO_CHAR, layout) & 0xFFFF
    except Exception:
        logger.debug("Virtual key %s has no US-English label", vk, exc_info=True)
        return None
    if not mapped:
        return None
    character = chr(mapped)
    if character.isprintable() and character not in {chr(9), chr(13), chr(10)}:
        return character.lower()
    return None
