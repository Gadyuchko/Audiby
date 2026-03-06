"""Windows autostart stub implementation."""

from audiby.platform.autostart import AutostartBase


class WindowsAutostart(AutostartBase):
    """Windows startup-on-boot implementation placeholder."""

    def enable(self, exe_path: str) -> None:
        raise NotImplementedError("Windows autostart implementation is deferred to Epic 3.")

    def disable(self) -> None:
        raise NotImplementedError("Windows autostart implementation is deferred to Epic 3.")

    def is_enabled(self) -> bool:
        raise NotImplementedError("Windows autostart implementation is deferred to Epic 3.")
