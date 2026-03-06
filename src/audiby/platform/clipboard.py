"""Clipboard abstraction for adapter for copy/paste with backup/restore, platform-agnostic"""
import sys
from abc import ABC, abstractmethod
from typing import Any

class ClipboardBase(ABC):
    @abstractmethod
    def backup(self) -> Any: ...
    @abstractmethod
    def restore(self, state: Any) -> None: ...
    @abstractmethod
    def get_text(self) -> str | None: ...
    @abstractmethod
    def set_text(self, text: str) -> None: ...


def get_clipboard() -> ClipboardBase:
    """Return a ClipboardBase instance for the current platform.
    Will be called to determine implementation based on a platform.
    """
    if sys.platform == "win32":
        from audiby.platform._clipboard_win import WindowsClipboard
        return WindowsClipboard()
    elif sys.platform == "darwin":
        from audiby.platform._clipboard_mac import MacClipboard
        return MacClipboard()
    else:
        raise NotImplementedError("Unsupported platform")
