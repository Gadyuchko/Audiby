import logging
import subprocess

from audiby.platform.shell import ShellBase

logger = logging.getLogger(__name__)
class MacShell(ShellBase):

    def open_folder(self, path):
        logger.debug("Opening folder: %s", path)
        subprocess.Popen(["open", str(path)])