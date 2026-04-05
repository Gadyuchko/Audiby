"""Windows autostart registry update implementation."""
import logging
import sys

import winreg

from audiby.constants import APP_NAME
from audiby.platform.autostart import AutostartBase

logger = logging.getLogger(__name__)

KEY_NAME = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"


class WindowsAutostart(AutostartBase):

    def enable(self, exe_path: str) -> None:
        logger.debug("Enabling autostart for %s", exe_path)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_NAME, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')

    def disable(self) -> None:
        logger.debug("Disabling autostart")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_NAME, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass  # already disabled — not an error

    def is_enabled(self) -> bool:
        expected = f'"{sys.executable}"'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_NAME, 0, winreg.KEY_READ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return value == expected
            except FileNotFoundError:
                return False

