"""macOS main-thread shim for pynput's keyboard-layout lookup.

pynput resolves the active keyboard layout through Carbon's Text Input Source
APIs (``TISCopyCurrentKeyboardInputSource`` and friends). Its keyboard
``Listener`` does so from its own background thread the moment it starts.

Once the process has shown a Tk window, macOS 26 requires those calls to run on
the main dispatch queue and aborts the process with ``EXC_BREAKPOINT`` in
``dispatch_assert_queue`` when they come from any other thread. Audiby shows
the permissions wizard (a Tk window) before the hotkey listener starts, which
is exactly that sequence.

The layout context pynput needs is a plain ``(keyboard_type, layout_bytes)``
tuple that never changes for the life of a listener, so this module computes
it once on the main thread and serves the cached value to every later caller.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading

logger = logging.getLogger(__name__)

_cached_context: tuple | None = None
_installed = False


def install_main_thread_keycode_context() -> bool:
    """Resolve pynput's keycode context on the main thread and cache it.

    Must be called from the main thread before any pynput keyboard listener
    starts. Returns True when the cache is installed, False when skipped
    (not macOS, already installed, or pynput's macOS backend unavailable).
    """
    global _cached_context, _installed

    if sys.platform != "darwin" or _installed:
        return False
    if threading.current_thread() is not threading.main_thread():
        logger.warning("Keycode context must be primed on the main thread; skipping")
        return False

    try:
        from pynput._util import darwin as pynput_darwin
        from pynput.keyboard import _darwin as pynput_keyboard
    except Exception as exc:  # pragma: no cover - depends on host packages
        logger.warning("pynput macOS backend unavailable; keycode cache not installed: %s", exc)
        return False

    original = pynput_darwin.keycode_context
    try:
        with original() as context:
            _cached_context = context
    except Exception:
        logger.exception("Failed to resolve keyboard layout on the main thread")
        return False

    @contextlib.contextmanager
    def cached_keycode_context():
        yield _cached_context

    # Both the util module (used by get_unicode_to_keycode_map) and the
    # keyboard backend (which imported the name directly) must see the cache.
    pynput_darwin.keycode_context = cached_keycode_context
    pynput_keyboard.keycode_context = cached_keycode_context
    _installed = True
    logger.debug("Installed main-thread keycode context cache for pynput")
    return True
