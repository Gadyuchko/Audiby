import sys
from abc import ABC, abstractmethod
from pathlib import Path


class ShellBase(ABC):

    @abstractmethod
    def open_folder(self, path: Path) -> None : ...


def get_shell() -> ShellBase:
    """Return a platform-specific shell implementation."""
    if sys.platform == "win32":
        from audiby.platform._shell_win import WindowsShell

        return WindowsShell()
    if sys.platform == "darwin":
        from audiby.platform._shell_mac import MacShell

        return MacShell()
    raise NotImplementedError(f"Unsupported platform: {sys.platform}")