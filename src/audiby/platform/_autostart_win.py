"""Windows autostart registry update implementation."""
from audiby.constants import APP_NAME
from audiby.platform.autostart import AutostartBase
import winreg
KEY_NAME = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"
class WindowsAutostart(AutostartBase):

    def enable(self, exe_path: str) -> None:

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_NAME, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')

    def disable(self) -> None:

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_NAME, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass  # already disabled — not an error

    def is_enabled(self) -> bool:

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_NAME, 0, winreg.KEY_READ) as key:
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False

