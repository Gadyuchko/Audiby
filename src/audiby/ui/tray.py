import logging
from collections.abc import Callable
from pathlib import Path

import pystray
import PIL.Image as Image

logger = logging.getLogger(__name__)
_ROOT_PATH = Path(__file__).resolve().parent.parent.parent.parent

class TrayController:
    """
    Handles the creation and management of the system tray icon for an application.

    This class provides functionality to initialize and manage a system tray icon
    with associated menu options for user interaction. It integrates with the
    `pystray` library to display and handle user commands such as opening settings,
    accessing the log folder, and quitting the application.

    :ivar _tray_icon: Instance of `pystray.Icon` used to manage the tray icon
                     and its menu.
    :type _tray_icon: pystray.Icon
    """
    def __init__(self, on_settings: Callable, on_open_log_folder: Callable, on_quit: Callable) -> None:

        self._on_settings = on_settings
        self._on_open_log = on_open_log_folder
        self._on_quit = on_quit
        _icon_path = _ROOT_PATH / "assets" / "audiby_tray_icon.png"
        try:

            self._tray_icon = pystray.Icon("Audiby", Image.open(_icon_path), menu=pystray.Menu(
                pystray.MenuItem("Settings", self._on_settings_clicked),
                pystray.MenuItem("Open Log Folder", self._on_open_log_folder_clicked),
                pystray.MenuItem("Quit", self._on_quit_clicked),
            ))

        except FileNotFoundError:
            logger.error("Could not find audiby_tray_icon.png in path %s", _icon_path)
            raise

    def start(self) -> None:
        self._tray_icon.run()

    def stop(self) -> None:
        self._tray_icon.stop()

    def _on_quit_clicked(self, _menu_item, _event):
        self._on_quit()
        self.stop()

    def _on_settings_clicked(self, _menu_item, _event):
        self._on_settings()

    def _on_open_log_folder_clicked(self, _menu_item, _event):
        self._on_open_log()