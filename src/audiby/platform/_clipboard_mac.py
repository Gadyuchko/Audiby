"""MacOS implementation of clipboard functionality"""
import logging
import subprocess
from typing import Any

from audiby.exceptions import InjectionError
from audiby.platform.clipboard import ClipboardBase

logger = logging.getLogger(__name__)

class MacClipboard(ClipboardBase):

    def backup(self) -> Any:
        return self.get_text()

    def restore(self, state: Any) -> None:
        self.set_text(state if state is not None else "")

    def get_text(self) -> str | None:
        try:
            # Run the macOS clipboard command directly.
            # capture_output=True gives us stdout/stderr so we can read clipboard text and log failures.
            # text=True means Python gives us normal strings instead of byte data.
            # check=True makes Python raise an error if the command fails.
            # We leave other options at defaults because we do not need them here:
            # - timeout: these commands are expected to finish quickly.
            # - cwd/env: clipboard behavior does not depend on working directory or custom env vars.
            # - encoding/errors: text=True default handling is enough for this use case.
            # - shell: keep it off for safer and clearer command execution.
            text = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, check=True
            ).stdout
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error("Failed to read clipboard: %s", e)
            raise InjectionError("Failed to read clipboard") from e
        return text or None

    def set_text(self, text: str) -> None:
        try:
            # input=text: send new clipboard text to pbcopy via stdin.
            # text=True/check=True rationale is the same as get_text().
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error("Failed to write clipboard: %s", e)
            raise InjectionError("Failed to write clipboard") from e
