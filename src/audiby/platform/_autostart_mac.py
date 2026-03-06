"""MacOS autostart stub implementation."""

from audiby.platform.autostart import AutostartBase


class MacAutostart(AutostartBase):
    """MacOS startup-on-boot implementation placeholder."""

    def enable(self, exe_path: str) -> None:
        raise NotImplementedError("MacOS autostart implementation is deferred to Epic 5.")

    def disable(self) -> None:
        raise NotImplementedError("MacOS autostart implementation is deferred to Epic 5.")

    def is_enabled(self) -> bool:
        raise NotImplementedError("MacOS autostart implementation is deferred to Epic 5.")
