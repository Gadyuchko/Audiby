import logging
import os
from pathlib import Path

from audiby.platform.shell import ShellBase

logger = logging.getLogger(__name__)
class WindowsShell(ShellBase):

    def open_folder(self, path: Path) -> None:
        logger.debug("Opening folder: %s", path)
        os.startfile(str(path))