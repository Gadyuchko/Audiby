"""Text injector for text manipulation from text queue and clipboard.

@author Roman Hadiuchko
"""
import logging
import time
from queue import Queue, Empty
from pynput.keyboard import Controller, Key
import audiby.platform.clipboard as clipboard
from audiby.constants import INJECTION_PASTE_DELAY
from audiby.exceptions import InjectionError

logger = logging.getLogger(__name__)

class TextInjector:

    def __init__(self, text_queue: Queue):
        self._text_queue = text_queue
        try:
            self._keyboard = Controller()
        except Exception as e:
            logger.error(f"Failed to initialize keyboard controller: {e}")
            raise RuntimeError("Failed to initialize keyboard controller") from e

    def inject(self) -> None:
        """Inject text from queue into active window."""
        backup_text = None
        try:
            text = self._text_queue.get_nowait()
        except Empty:
            logger.debug("Text queue is empty, skipping injection")
            return

        try:
            backup_text = clipboard.backup()
            clipboard.set_text(text)
            with self._keyboard.pressed(Key.ctrl):
                self._keyboard.press('v')
                self._keyboard.release('v')
            time.sleep(INJECTION_PASTE_DELAY)

        except InjectionError:
            raise
        except Exception as e:
            logger.error(f"Failed to inject text: {e}")
            raise InjectionError("Failed to inject text") from e
        finally:
            clipboard.restore(backup_text)