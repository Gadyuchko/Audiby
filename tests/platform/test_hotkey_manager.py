"""Behavior-focused tests for HotkeyManager.

Tests validate registration lifecycle (start/stop), callback wiring for
press/release signals via pynput Listener, and error wrapping/logging
for backend failures. All pynput dependencies are fully mocked.
"""

import logging
from unittest.mock import MagicMock

import pytest

from audiby.exceptions import HotkeyError
from audiby.platform.hotkey_manager import HotkeyManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_listener(mocker):
    """Patch pynput keyboard.Listener so no real OS listener is created."""
    mock_cls = mocker.patch("audiby.platform.hotkey_manager.Listener")
    mock_instance = MagicMock()
    mock_instance.daemon = True
    mock_cls.return_value = mock_instance
    return mock_cls, mock_instance


@pytest.fixture
def callbacks():
    """Simple press/release callback mocks."""
    return MagicMock(name="on_press"), MagicMock(name="on_release")


# ---------------------------------------------------------------------------
# Task 2.1 — Registration lifecycle (start, stop) around global listener
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_start_creates_and_starts_listener(self, mock_listener, callbacks):
        """start() must create a Listener and call its start()."""
        mock_cls, mock_instance = mock_listener
        on_press, on_release = callbacks

        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)
        manager.start()

        mock_cls.assert_called_once()
        mock_instance.start.assert_called_once()

    def test_stop_stops_listener(self, mock_listener, callbacks):
        """stop() must call the listener's stop()."""
        _, mock_instance = mock_listener
        on_press, on_release = callbacks

        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)
        manager.start()
        manager.stop()

        mock_instance.stop.assert_called_once()

    def test_stop_without_start_is_safe(self, mock_listener, callbacks):
        """Calling stop() before start() must not raise."""
        _, _ = mock_listener
        on_press, on_release = callbacks

        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)
        manager.stop()  # no error

    def test_listener_receives_internal_callbacks(self, mock_listener, callbacks):
        """Listener must be created with on_press and on_release keyword args."""
        mock_cls, _ = mock_listener
        on_press, on_release = callbacks

        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)
        manager.start()

        _, kwargs = mock_cls.call_args
        assert "on_press" in kwargs
        assert "on_release" in kwargs


# ---------------------------------------------------------------------------
# Task 2.2 — Callback wiring for press/release signals only
# ---------------------------------------------------------------------------

class TestCallbackWiring:
    def test_combo_press_fires_on_press_callback(self, mock_listener, callbacks):
        """Pressing all combo keys must fire the on_press callback."""
        from pynput.keyboard import Key, KeyCode

        on_press, on_release = callbacks
        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)

        # Simulate pressing alt then z
        manager._on_key_press(Key.alt_l)
        manager._on_key_press(KeyCode.from_char('z'))

        on_press.assert_called_once()

    def test_partial_combo_does_not_fire(self, mock_listener, callbacks):
        """Pressing only part of the combo must not fire on_press."""
        from pynput.keyboard import Key

        on_press, on_release = callbacks
        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)

        manager._on_key_press(Key.alt_l)

        on_press.assert_not_called()

    def test_combo_release_fires_on_release_callback(self, mock_listener, callbacks):
        """Releasing a combo key while combo was active must fire on_release."""
        from pynput.keyboard import Key, KeyCode

        on_press, on_release = callbacks
        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)

        # Press combo
        manager._on_key_press(Key.alt_l)
        manager._on_key_press(KeyCode.from_char('z'))

        # Release one combo key
        manager._on_key_release(KeyCode.from_char('z'))

        on_release.assert_called_once()

    def test_non_combo_key_ignored(self, mock_listener, callbacks):
        """Keys not part of the combo must not trigger any callback."""
        from pynput.keyboard import KeyCode

        on_press, on_release = callbacks
        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)

        manager._on_key_press(KeyCode.from_char('x'))
        manager._on_key_release(KeyCode.from_char('x'))

        on_press.assert_not_called()
        on_release.assert_not_called()

    def test_no_business_logic_in_manager(self, mock_listener, callbacks):
        """HotkeyManager must only forward signals — no queue/event manipulation."""
        on_press, on_release = callbacks
        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)

        assert not hasattr(manager, "audio_queue")
        assert not hasattr(manager, "text_queue")
        assert not hasattr(manager, "recording_event")


# ---------------------------------------------------------------------------
# Task 2.3 — Backend failures are wrapped and logged as metadata-only errors
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_start_failure_is_logged(self, mock_listener, callbacks, caplog):
        """If Listener raises on start(), error must be logged."""
        _, mock_instance = mock_listener
        mock_instance.start.side_effect = Exception("backend init failed")
        on_press, on_release = callbacks

        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)

        with caplog.at_level(logging.ERROR, logger="audiby.platform.hotkey_manager"):
            with pytest.raises(HotkeyError):
                manager.start()

        assert caplog.records

    def test_release_of_untracked_key_does_not_crash(self, mock_listener, callbacks):
        """Releasing a key that was never pressed must not raise."""
        from pynput.keyboard import KeyCode

        on_press, on_release = callbacks
        manager = HotkeyManager(hotkey="alt+z", on_press=on_press, on_release=on_release)

        # Release without prior press — must not crash
        manager._on_key_release(KeyCode.from_char('q'))
