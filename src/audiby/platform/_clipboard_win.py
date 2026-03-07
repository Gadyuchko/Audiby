"""Windows implementation of clipboard functionality"""
import ctypes
import logging
import time
from ctypes import wintypes
from typing import Any

from audiby.exceptions import InjectionError
from audiby.platform.clipboard import ClipboardBase

_CF_UNICODETEXT = 13  # The clipboard format identifier for UTF-16 text (Win).
_GMEM_MOVEABLE = 0x0002  # Memory block pointer flag defined by Win32 API.
_CLIPBOARD_OPEN_RETRIES = 10
_CLIPBOARD_OPEN_DELAY_SEC = 0.01

# Configure explicit Win32 signatures to avoid 64-bit handle/pointer truncation.
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

OpenClipboard = _user32.OpenClipboard
OpenClipboard.argtypes = [wintypes.HWND]
OpenClipboard.restype = wintypes.BOOL

EmptyClipboard = _user32.EmptyClipboard
EmptyClipboard.argtypes = []
EmptyClipboard.restype = wintypes.BOOL

GetClipboardData = _user32.GetClipboardData
GetClipboardData.argtypes = [wintypes.UINT]
GetClipboardData.restype = wintypes.HANDLE

SetClipboardData = _user32.SetClipboardData
SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
SetClipboardData.restype = wintypes.HANDLE

CloseClipboard = _user32.CloseClipboard
CloseClipboard.argtypes = []
CloseClipboard.restype = wintypes.BOOL

GlobalAlloc = _kernel32.GlobalAlloc
GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
GlobalAlloc.restype = wintypes.HGLOBAL

GlobalLock = _kernel32.GlobalLock
GlobalLock.argtypes = [wintypes.HGLOBAL]
GlobalLock.restype = wintypes.LPVOID

GlobalUnlock = _kernel32.GlobalUnlock
GlobalUnlock.argtypes = [wintypes.HGLOBAL]
GlobalUnlock.restype = wintypes.BOOL

GlobalFree = _kernel32.GlobalFree
GlobalFree.argtypes = [wintypes.HGLOBAL]
GlobalFree.restype = wintypes.HGLOBAL


logger = logging.getLogger(__name__)


def _open_clipboard_with_retry() -> None:
    """Open clipboard with short retries to tolerate transient lock contention."""
    for _ in range(_CLIPBOARD_OPEN_RETRIES):
        if OpenClipboard(None):
            return
        time.sleep(_CLIPBOARD_OPEN_DELAY_SEC)
    raise InjectionError("Failed to open clipboard")


class WindowsClipboard(ClipboardBase):

    def get_text(self) -> str | None:
        """Opens the clipboard and returns its contents as a string or null if the clipboard is empty. Safely closes clipboard."""
        _open_clipboard_with_retry()
        try:
            # get memory pointer to clipboard data
            handle = GetClipboardData(_CF_UNICODETEXT)
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
        except InjectionError:
            raise
        except Exception as e:
            logger.error("Error while reading clipboard: %s", e)
            raise InjectionError("Error while reading clipboard") from e
        finally:
            CloseClipboard()

    def set_text(self, text: str) -> None:
        """Opens clipboard and writes the given text to it. Safely closes clipboard."""
        _open_clipboard_with_retry()
        try:
            if not EmptyClipboard():
                raise InjectionError("Failed to empty clipboard")
            buffer_size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
            # id of mem block
            handle = GlobalAlloc(_GMEM_MOVEABLE, buffer_size)

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

            if not SetClipboardData(_CF_UNICODETEXT, handle):
                GlobalFree(handle)
                raise InjectionError("Failed to set clipboard data")
            logger.debug("Clipboard set successfully (text length: %d)", len(text))
        except InjectionError:
            raise
        except Exception as e:
            logger.error("Error while writing clipboard: %s", e)
            raise InjectionError("Error while writing clipboard") from e
        finally:
            CloseClipboard()

    def backup(self) -> str | None:
        return self.get_text()

    def restore(self, state: Any) -> None:
        if state is not None:
            self.set_text(state)
        else:
            try:
                _open_clipboard_with_retry()
                if not EmptyClipboard():
                    raise InjectionError("Failed to empty clipboard")
                logger.debug("Clipboard restored to empty state")
            except InjectionError:
                raise
            except Exception as e:
                logger.error("Error while restoring clipboard: %s", e)
                raise InjectionError("Error while restoring clipboard") from e
            finally:
                CloseClipboard()
