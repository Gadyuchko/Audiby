"""Clipboard adapter for copy and paste integration with previous clipboard state preservation.
The decision to use os clipboard as a text injection method resulted in the use of external libraries WinDLL user32 and kernel32,
because pyperclip only does copy()/paste() and we need backup and restore functionality to preserve user data on paste.

"""

import logging
import ctypes
from audiby.constants import CF_UNICODETEXT
from audiby.constants import GMEM_MOVEABLE

OpenClipboard = ctypes.windll.user32.OpenClipboard
EmptyClipboard = ctypes.windll.user32.EmptyClipboard
GetClipboardData = ctypes.windll.user32.GetClipboardData
SetClipboardData = ctypes.windll.user32.SetClipboardData
CloseClipboard = ctypes.windll.user32.CloseClipboard

GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
GlobalLock = ctypes.windll.kernel32.GlobalLock
GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
GlobalFree = ctypes.windll.kernel32.GlobalFree

from audiby.exceptions import InjectionError

logger = logging.getLogger(__name__)

def get_text() -> str | None:
    """Opens clipboard and returns its contents as a string or null if the clipboard is empty. Safely closes clipboard."""
    if not OpenClipboard(None):
        raise InjectionError("Failed to open clipboard")
    try:
        # get memory pointer to clipboard data
        handle = GetClipboardData(CF_UNICODETEXT)
        if not handle or handle == 0:
            return None
        pointer = GlobalLock(handle)
        if not pointer:
            raise InjectionError("Failed to lock clipboard data")
        try:
            # extract the actual text from the memory block
            text = ctypes.wstring_at(pointer)
            return text.rstrip("\0")
        finally:
            GlobalUnlock(handle)
    except Exception as e:
        logger.error(f"Error while reading clipboard: {e}")
        raise InjectionError("Error while reading clipboard") from e
    finally:
        CloseClipboard()

def set_text(text: str) -> None:
    """Opens clipboard and writes the given text to it. Safely closes clipboard."""
    if not OpenClipboard(None):
        raise InjectionError("Failed to open clipboard")
    try:
        EmptyClipboard()
        buffer_size = (len(text) +1 ) * ctypes.sizeof(ctypes.c_wchar)
        # id of mem block
        handle = GlobalAlloc(GMEM_MOVEABLE, buffer_size)

        if not handle:
            raise InjectionError("Failed to allocate memory")

        # pointer to mem block and pin it in place temporary
        pointer = GlobalLock(handle)
        if not pointer:
            raise InjectionError("Failed to lock memory")

        try:
            # copy text to mem block
            buffer = ctypes.create_unicode_buffer(text)
            ctypes.memmove(pointer, buffer, buffer_size)
        finally:
            # unpin mem block
            GlobalUnlock(handle)

        if not SetClipboardData(CF_UNICODETEXT, handle):
            GlobalFree(handle)
            raise InjectionError("Failed to set clipboard data")
    except InjectionError:
        raise
    except Exception as e:
        logger.error(f"Error while writing clipboard: {e}")
        raise InjectionError("Error while writing clipboard") from e
    finally:
        CloseClipboard()

def backup() -> str | None:
    return get_text()

def restore(backup: str | None) -> None:
    if backup is not None:
        set_text(backup)
    else:
        try:
            if not OpenClipboard(None):
                raise InjectionError("Failed to open clipboard")
            EmptyClipboard()
        except InjectionError:
            raise
        except Exception as e:
            logger.error(f"Error while restoring clipboard: {e}")
            raise InjectionError("Error while restoring clipboard") from e
        finally:
            CloseClipboard()


