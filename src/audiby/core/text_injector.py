"""Text injector for text manipulation from text queue and clipboard.

"""
import logging
import time
from queue import Empty, Queue

import audiby.platform.clipboard as clipboard
from audiby.constants import INJECTION_PASTE_DELAY
from audiby.exceptions import InjectionError
from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)

class TextInjector:

    def __init__(self, text_queue: Queue):
        self._text_queue = text_queue
        try:
            self._keyboard = Controller()
        except Exception as exc:
            logger.error("Keyboard controller initialization failed")
            raise InjectionError("Failed to initialize keyboard controller") from exc

    def inject(self) -> None:
        """Inject text from queue into active window."""
        backup_text = None
        backup_captured = False
        try:
            text = self._text_queue.get_nowait()
        except Empty:
            return

        logger.debug("Injection attempt started (text length: %d)", len(text))
        try:
            backup_text = clipboard.backup()
            backup_captured = True
            clipboard.set_text(text)
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press("v")
                self._keyboard.release("v")
            time.sleep(INJECTION_PASTE_DELAY)
            logger.info("Injection key sequence sent (text length: %d)", len(text))

        except InjectionError:
            logger.error("Text injection failed")
            raise
        except Exception as exc:
            logger.error("Text injection failed with unexpected error")
            raise InjectionError("Failed to inject text") from exc
        finally:
            if backup_captured:
                clipboard.restore(backup_text)
