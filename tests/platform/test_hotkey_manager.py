"""Behavior-focused tests for platform hotkey manager factory and backends."""

from unittest.mock import MagicMock

import pytest

from audiby.exceptions import HotkeyError
from audiby.platform._hotkey_mac import MacHotkeyManager
from audiby.platform._hotkey_win import WindowsHotkeyManager
from audiby.platform.hotkey_manager import get_hotkey_manager


@pytest.fixture
def callbacks():
    return MagicMock(name="on_press"), MagicMock(name="on_release")


def test_factory_returns_windows_backend_on_win32(monkeypatch, callbacks):
    on_press, on_release = callbacks
    monkeypatch.setattr("sys.platform", "win32")

    manager = get_hotkey_manager("alt+z", on_press, on_release)

    assert isinstance(manager, WindowsHotkeyManager)


def test_factory_returns_mac_backend_on_darwin(monkeypatch, callbacks):
    on_press, on_release = callbacks
    monkeypatch.setattr("sys.platform", "darwin")

    manager = get_hotkey_manager("cmd+z", on_press, on_release)

    assert isinstance(manager, MacHotkeyManager)


def test_factory_raises_on_unsupported_platform(monkeypatch, callbacks):
    on_press, on_release = callbacks
    monkeypatch.setattr("sys.platform", "linux")

    with pytest.raises(NotImplementedError):
        get_hotkey_manager("ctrl+z", on_press, on_release)


def test_windows_start_creates_listener(mocker, callbacks):
    listener_cls = mocker.patch("audiby.platform._hotkey_win.Listener")
    listener_instance = listener_cls.return_value
    on_press, on_release = callbacks
    manager = WindowsHotkeyManager("alt+z", on_press, on_release)

    manager.start()

    listener_cls.assert_called_once()
    listener_instance.start.assert_called_once()


def test_windows_start_wraps_listener_failure(mocker, callbacks):
    listener_cls = mocker.patch("audiby.platform._hotkey_win.Listener")
    listener_cls.return_value.start.side_effect = RuntimeError("boom")
    on_press, on_release = callbacks
    manager = WindowsHotkeyManager("alt+z", on_press, on_release)

    with pytest.raises(HotkeyError):
        manager.start()


def test_windows_combo_press_release_invokes_callbacks(callbacks):
    from pynput.keyboard import Key, KeyCode

    on_press, on_release = callbacks
    manager = WindowsHotkeyManager("alt+z", on_press, on_release)

    manager._on_key_press(Key.alt_l)
    manager._on_key_press(KeyCode.from_char("z"))
    manager._on_key_release(KeyCode.from_char("z"))

    on_press.assert_called_once()
    on_release.assert_called_once()


def test_windows_vk_normalization_kept():
    from pynput.keyboard import Key, KeyCode

    manager = WindowsHotkeyManager("ctrl+z", lambda: None, lambda: None)
    assert manager._normalize_key(KeyCode.from_vk(162)) == Key.ctrl
    assert manager._normalize_key(KeyCode.from_vk(164)) == Key.alt
    assert manager._normalize_key(KeyCode.from_vk(160)) == Key.shift


def test_mac_combo_press_release_invokes_callbacks(callbacks):
    from pynput.keyboard import Key, KeyCode

    on_press, on_release = callbacks
    manager = MacHotkeyManager("alt+z", on_press, on_release)

    manager._on_key_press(Key.alt_l)
    manager._on_key_press(KeyCode.from_char("z"))
    manager._on_key_release(KeyCode.from_char("z"))

    on_press.assert_called_once()
    on_release.assert_called_once()


def test_mac_start_wraps_listener_failure(mocker, callbacks):
    listener_cls = mocker.patch("audiby.platform._hotkey_mac.Listener")
    listener_cls.return_value.start.side_effect = RuntimeError("boom")
    on_press, on_release = callbacks
    manager = MacHotkeyManager("cmd+z", on_press, on_release)

    with pytest.raises(HotkeyError):
        manager.start()
