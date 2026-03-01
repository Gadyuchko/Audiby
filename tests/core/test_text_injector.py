"""Behavior-focused tests for TextInjector.

Tests validate queue-driven injection flow, clipboard backup/restore
guarantee, InjectionError handling, privacy guardrails, and sequential
injection independence. Clipboard and pynput are fully mocked.
"""
import logging
import queue
from unittest.mock import MagicMock, patch

import pytest

from audiby.exceptions import InjectionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_P = "audiby.core.text_injector"


class _InjectorContext:
    """Holds injector and mocks with patches kept active."""

    def __init__(self, patches):
        self._patches = patches

    def cleanup(self):
        for p in self._patches:
            p.stop()


@pytest.fixture
def make_injector():
    """Factory fixture that creates a TextInjector with mocked dependencies.

    Patches remain active until test teardown.
    """
    contexts = []

    def _factory(text_queue=None, clipboard_mod=None, controller=None):
        tq = text_queue or queue.Queue()
        mock_cb = clipboard_mod or MagicMock()
        mock_ctrl = controller or MagicMock()

        p_clip = patch(f"{_P}.clipboard", mock_cb)
        p_ctrl = patch(f"{_P}.Controller", return_value=mock_ctrl)
        p_clip.start()
        p_ctrl.start()

        from audiby.core.text_injector import TextInjector
        injector = TextInjector(text_queue=tq)

        contexts.append(_InjectorContext([p_clip, p_ctrl]))
        return injector, mock_cb, mock_ctrl

    yield _factory

    for ctx in contexts:
        ctx.cleanup()


# ---------------------------------------------------------------------------
# Task 5.1 — Happy-path: text from queue → backup → paste → restore
# ---------------------------------------------------------------------------

class TestTextInjectorHappyPath:
    """TextInjector processes queue items via clipboard backup → paste → restore."""

    def test_inject_pulls_text_from_queue_and_pastes(self, make_injector):
        """inject() must pull text from queue, set it on clipboard, and simulate Ctrl+V."""
        tq = queue.Queue()
        tq.put("hello world")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "original"

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)
        injector.inject()

        mock_cb.backup.assert_called_once()
        mock_cb.set_text.assert_called_once_with("hello world")
        mock_cb.restore.assert_called_once_with("original")

    def test_inject_simulates_ctrl_v(self, make_injector):
        """inject() must simulate Ctrl+V via pynput controller."""
        tq = queue.Queue()
        tq.put("test")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "old"

        injector, _, mock_ctrl = make_injector(text_queue=tq, clipboard_mod=mock_cb)
        injector.inject()

        # Controller must have used pressed(Key.ctrl) context manager
        mock_ctrl.pressed.assert_called_once()

    def test_inject_order_backup_set_paste_restore(self, make_injector):
        """Operations must occur in order: backup → set_text → Ctrl+V → restore."""
        tq = queue.Queue()
        tq.put("ordered")

        call_order = []
        mock_cb = MagicMock()
        mock_cb.backup.side_effect = lambda: (call_order.append("backup"), "orig")[1]
        mock_cb.set_text.side_effect = lambda t: call_order.append("set_text")
        mock_cb.restore.side_effect = lambda b: call_order.append("restore")

        mock_ctrl = MagicMock()
        # pressed() returns a context manager; entering it = "paste"
        ctx = MagicMock()
        ctx.__enter__ = lambda s: call_order.append("paste")
        ctx.__exit__ = MagicMock(return_value=False)
        mock_ctrl.pressed.return_value = ctx

        injector, _, _ = make_injector(
            text_queue=tq, clipboard_mod=mock_cb, controller=mock_ctrl,
        )
        injector.inject()

        assert call_order == ["backup", "set_text", "paste", "restore"]

    def test_inject_returns_without_error_on_success(self, make_injector):
        """inject() must complete without raising on happy path."""
        tq = queue.Queue()
        tq.put("success")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "old"

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)
        # Must not raise
        injector.inject()


# ---------------------------------------------------------------------------
# Task 5.2 — Clipboard always restored on injection failure
# ---------------------------------------------------------------------------

class TestClipboardRestoreGuarantee:
    """Clipboard must be restored even when injection fails."""

    def test_clipboard_restored_when_set_text_raises(self, make_injector):
        """restore() must be called even if set_text() throws InjectionError."""
        tq = queue.Queue()
        tq.put("will fail")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "saved"
        mock_cb.set_text.side_effect = InjectionError("clipboard write failed")

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        with pytest.raises(InjectionError):
            injector.inject()

        mock_cb.restore.assert_called_once_with("saved")

    def test_clipboard_restored_when_ctrl_v_raises(self, make_injector):
        """restore() must be called even if keyboard simulation throws."""
        tq = queue.Queue()
        tq.put("paste fail")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "saved"

        mock_ctrl = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=OSError("keyboard error"))
        ctx.__exit__ = MagicMock(return_value=False)
        mock_ctrl.pressed.return_value = ctx

        injector, _, _ = make_injector(
            text_queue=tq, clipboard_mod=mock_cb, controller=mock_ctrl,
        )

        with pytest.raises(InjectionError):
            injector.inject()

        mock_cb.restore.assert_called_once_with("saved")

    def test_clipboard_restored_with_none_backup(self, make_injector):
        """restore(None) must be called if backup was None (non-text clipboard)."""
        tq = queue.Queue()
        tq.put("inject")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = None
        mock_cb.set_text.side_effect = InjectionError("fail")

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        with pytest.raises(InjectionError):
            injector.inject()

        mock_cb.restore.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# Task 5.3 — InjectionError raised/logged without terminating processing
# ---------------------------------------------------------------------------

class TestInjectionErrorHandling:
    """InjectionError is raised but does not kill the injector's ability to process."""

    def test_injection_error_raised_on_clipboard_failure(self, make_injector):
        """Clipboard failures must surface as InjectionError."""
        tq = queue.Queue()
        tq.put("fail")

        mock_cb = MagicMock()
        mock_cb.backup.side_effect = InjectionError("open failed")

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        with pytest.raises(InjectionError):
            injector.inject()

    def test_keyboard_error_wrapped_as_injection_error(self, make_injector):
        """pynput errors must be wrapped as InjectionError, not leaked raw."""
        tq = queue.Queue()
        tq.put("type fail")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "old"

        mock_ctrl = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=RuntimeError("pynput crash"))
        ctx.__exit__ = MagicMock(return_value=False)
        mock_ctrl.pressed.return_value = ctx

        injector, _, _ = make_injector(
            text_queue=tq, clipboard_mod=mock_cb, controller=mock_ctrl,
        )

        with pytest.raises(InjectionError) as exc_info:
            injector.inject()

        # Original exception must be chained
        assert exc_info.value.__cause__ is not None

    def test_injector_recovers_after_failed_injection(self, make_injector):
        """After a failed inject(), the next valid call must succeed."""
        tq = queue.Queue()
        tq.put("will fail")
        tq.put("will succeed")

        mock_cb = MagicMock()
        # First backup fails, second succeeds
        mock_cb.backup.side_effect = [
            InjectionError("transient"),
            "saved",
        ]

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        # First call fails
        with pytest.raises(InjectionError):
            injector.inject()

        # Second call recovers
        injector.inject()
        mock_cb.set_text.assert_called_once_with("will succeed")
        # restore called twice: once for failed inject (None backup), once for success
        assert mock_cb.restore.call_args_list[-1] == (("saved",),)


# ---------------------------------------------------------------------------
# Task 5.4 — No transcribed text content in log messages (privacy)
# ---------------------------------------------------------------------------

class TestPrivacyGuardrail:
    """Injected text content must never appear in log output."""

    def test_no_text_content_in_success_log(self, make_injector, caplog):
        """Successful injection must not log the actual injected text."""
        tq = queue.Queue()
        secret_text = "super secret dictation content XYZ123"
        tq.put(secret_text)

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "old"

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        with caplog.at_level(logging.DEBUG, logger="audiby.core.text_injector"):
            injector.inject()

        for record in caplog.records:
            assert secret_text not in record.getMessage(), \
                f"Injected text leaked into log: {record.getMessage()}"

    def test_no_text_content_in_error_log(self, make_injector, caplog):
        """Failed injection must not log the text that was being injected."""
        tq = queue.Queue()
        secret_text = "private dictation ABC789"
        tq.put(secret_text)

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "old"
        mock_cb.set_text.side_effect = InjectionError("write failed")

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        with caplog.at_level(logging.DEBUG, logger="audiby.core.text_injector"):
            with pytest.raises(InjectionError):
                injector.inject()

        for record in caplog.records:
            assert secret_text not in record.getMessage(), \
                f"Injected text leaked into error log: {record.getMessage()}"

    def test_text_length_may_appear_in_log(self, make_injector, caplog):
        """Operational metadata like text length is acceptable in logs."""
        tq = queue.Queue()
        tq.put("five!")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "old"

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        with caplog.at_level(logging.DEBUG, logger="audiby.core.text_injector"):
            injector.inject()

        # This test simply confirms no crash — length logging is optional metadata


# ---------------------------------------------------------------------------
# Task 5.5 — Multiple sequential injections handled independently
# ---------------------------------------------------------------------------

class TestSequentialInjections:
    """Each injection from the queue is independent."""

    def test_multiple_texts_processed_independently(self, make_injector):
        """Each queue item must get its own backup/set/paste/restore cycle."""
        tq = queue.Queue()
        tq.put("first")
        tq.put("second")
        tq.put("third")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "saved"

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        injector.inject()
        injector.inject()
        injector.inject()

        assert mock_cb.backup.call_count == 3
        assert mock_cb.set_text.call_count == 3
        assert mock_cb.restore.call_count == 3

        set_calls = [c.args[0] for c in mock_cb.set_text.call_args_list]
        assert set_calls == ["first", "second", "third"]

    def test_failed_injection_does_not_affect_next(self, make_injector):
        """A failed injection must not corrupt the next injection's state."""
        tq = queue.Queue()
        tq.put("fail this")
        tq.put("succeed this")

        mock_cb = MagicMock()
        mock_cb.backup.return_value = "saved"
        # First set_text fails, second succeeds
        mock_cb.set_text.side_effect = [
            InjectionError("transient write error"),
            None,
        ]

        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        with pytest.raises(InjectionError):
            injector.inject()

        # Second injection must succeed independently
        injector.inject()

        assert mock_cb.restore.call_count == 2
        assert mock_cb.set_text.call_args_list[1].args[0] == "succeed this"

    def test_empty_queue_skips_injection(self, make_injector):
        """inject() on empty queue must return without touching clipboard."""
        tq = queue.Queue()

        mock_cb = MagicMock()
        injector, _, _ = make_injector(text_queue=tq, clipboard_mod=mock_cb)

        # Must not raise
        injector.inject()

        # Clipboard should not have been touched
        mock_cb.backup.assert_not_called()
