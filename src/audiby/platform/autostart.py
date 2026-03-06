"""Platform autostart abstraction and factory."""

import sys
from abc import ABC, abstractmethod


class AutostartBase(ABC):
    """Contract for platform-specific startup-on-boot integrations."""

    @abstractmethod
    def enable(self, exe_path: str) -> None: ...

    @abstractmethod
    def disable(self) -> None: ...

    @abstractmethod
    def is_enabled(self) -> bool: ...


def get_autostart() -> AutostartBase:
    """Return a platform-specific autostart implementation."""
    if sys.platform == "win32":
        from audiby.platform._autostart_win import WindowsAutostart

        return WindowsAutostart()
    if sys.platform == "darwin":
        from audiby.platform._autostart_mac import MacAutostart

        return MacAutostart()
    raise NotImplementedError(f"Unsupported platform: {sys.platform}")
