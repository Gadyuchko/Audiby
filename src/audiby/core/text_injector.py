"""Text injector for text manipulation from text queue and clipboard.

"""
import logging
import time
from queue import Empty, Queue

import audiby.platform.clipboard as clipboard
from audiby.constants import (
    ALT_NEUTRALIZATION_ESC,
    ALT_NEUTRALIZATION_NONE,
    ALT_NEUTRALIZATION_TAP_ALT,
    INJECTION_PASTE_DELAY,
)
from audiby.exceptions import InjectionError
from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)

class TextInjector:

    def __init__(
        self,
        text_queue: Queue,
        alt_neutralization_strategy: str = ALT_NEUTRALIZATION_TAP_ALT,
        hotkey_uses_alt: bool = False,
    ):
        self._text_queue = text_queue
        self._alt_neutralization_strategy = alt_neutralization_strategy
        self._hotkey_uses_alt = hotkey_uses_alt
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
            self._neutralize_modifiers_if_needed()
            with self._keyboard.pressed(Key.ctrl_l):
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

    def _neutralize_modifiers_if_needed(self) -> None:
        """Release held modifiers; optionally neutralize Alt menu-mode before paste."""
        for key in (Key.alt_l, Key.alt_r, Key.ctrl_l, Key.ctrl_r, Key.shift_l, Key.shift_r):
            try:
                self._keyboard.release(key)
            except Exception:
                # Best-effort release only; continue with remaining keys.
                continue

        if not self._hotkey_uses_alt:
            return

        if self._alt_neutralization_strategy == ALT_NEUTRALIZATION_NONE:
            logger.debug("Alt neutralization skipped (strategy: none)")
            return
        if self._alt_neutralization_strategy == ALT_NEUTRALIZATION_ESC:
            logger.debug("Alt neutralization applied (strategy: esc)")
            self._keyboard.press(Key.esc)
            self._keyboard.release(Key.esc)
            time.sleep(0.02)
            return
        if self._alt_neutralization_strategy == ALT_NEUTRALIZATION_TAP_ALT:
            logger.debug("Alt neutralization applied (strategy: tap_alt)")
            self._keyboard.press(Key.alt_l)
            self._keyboard.release(Key.alt_l)
            time.sleep(0.02)
