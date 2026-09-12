"""Behavior-focused tests for platform hotkey manager factory and backends."""

from unittest.mock import MagicMock

import pytest

from audiby.exceptions import HotkeyError, HotkeyPermissionError
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
    listener_cls = mocker.patch("audiby.platform.hotkey_manager.Listener")
    listener_instance = listener_cls.return_value
    on_press, on_release = callbacks
    manager = WindowsHotkeyManager("alt+z", on_press, on_release)

    manager.start()

    listener_cls.assert_called_once()
    listener_instance.start.assert_called_once()


def test_windows_start_wraps_listener_failure(mocker, callbacks):
    listener_cls = mocker.patch("audiby.platform.hotkey_manager.Listener")
    original = RuntimeError("boom")
    listener_cls.return_value.start.side_effect = original
    on_press, on_release = callbacks
    manager = WindowsHotkeyManager("alt+z", on_press, on_release)

    with pytest.raises(HotkeyPermissionError) as exc_info:
        manager.start()
    assert exc_info.value.__cause__ is original


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


def test_mac_start_creates_listener(mocker, callbacks):
    listener_cls = mocker.patch("audiby.platform.hotkey_manager.Listener")
    listener_instance = listener_cls.return_value
    on_press, on_release = callbacks
    manager = MacHotkeyManager("cmd+z", on_press, on_release)

    manager.start()

    listener_cls.assert_called_once()
    listener_instance.start.assert_called_once()


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
    listener_cls = mocker.patch("audiby.platform.hotkey_manager.Listener")
    original = RuntimeError("boom")
    listener_cls.return_value.start.side_effect = original
    on_press, on_release = callbacks
    manager = MacHotkeyManager("cmd+z", on_press, on_release)

    with pytest.raises(HotkeyPermissionError) as exc_info:
        manager.start()
    assert exc_info.value.__cause__ is original


def test_hotkey_permission_error_remains_hotkey_error() -> None:
    """Settings fallback code can keep catching HotkeyError."""
    assert issubclass(HotkeyPermissionError, HotkeyError)


# ---------------------------------------------------------------------------
# Hotkey identity must survive a keyboard layout switch
# ---------------------------------------------------------------------------

class TestHotkeyIsLayoutIndependent:
    """A combo must match the physical key, not the character a layout prints.

    Regression guard: pynput resolves an incoming key's `char` through the
    active Windows layout. The physical "D" key reports "d" on en-US and "в" on
    uk-UA/ru-RU, so a combo stored and matched by character silently stops
    firing the moment the user switches layout. Virtual key codes are the
    layout-independent identity - VK_A..VK_Z are 0x41..0x5A regardless of
    layout, so they are derivable by arithmetic with no VkKeyScan lookup.
    """

    # What pynput reports for the physical "D" key on each layout.
    VK_D = 0x44
    LATIN_D = "d"
    CYRILLIC_D = "в"

    def test_parsed_combo_uses_virtual_key_not_character(self):
        """"ctrl+d" must parse to a VK-addressed key so no layout is consulted."""
        manager = WindowsHotkeyManager("ctrl+d", lambda: None, lambda: None)

        letter_keys = [k for k in manager._hotkey_set if getattr(k, "vk", None) == self.VK_D]
        assert letter_keys, (
            f"no VK_D key in parsed combo {manager._hotkey_set} - "
            "the letter is still stored by character"
        )
        assert getattr(letter_keys[0], "char", None) is None

    def test_same_physical_key_normalizes_alike_across_layouts(self):
        """The physical "D" key must normalize identically on en-US and uk-UA."""
        from pynput.keyboard import KeyCode

        manager = WindowsHotkeyManager("ctrl+d", lambda: None, lambda: None)

        as_latin = manager._normalize_key(KeyCode(vk=self.VK_D, char=self.LATIN_D))
        as_cyrillic = manager._normalize_key(KeyCode(vk=self.VK_D, char=self.CYRILLIC_D))

        assert as_latin == as_cyrillic

    def test_combo_fires_when_layout_reports_cyrillic_char(self, callbacks):
        """A combo captured on en-US must still fire while typing on uk-UA."""
        from pynput.keyboard import Key, KeyCode

        on_press, on_release = callbacks
        manager = WindowsHotkeyManager("ctrl+d", on_press, on_release)

        # Same physical key, but the Cyrillic layout labels it "в".
        cyrillic_d = KeyCode(vk=self.VK_D, char=self.CYRILLIC_D)
        manager._on_key_press(Key.ctrl_l)
        manager._on_key_press(cyrillic_d)
        manager._on_key_release(cyrillic_d)

        on_press.assert_called_once()
        on_release.assert_called_once()

    def test_special_keys_still_match(self, callbacks):
        """Named keys are already VK-based - the change must not regress them."""
        from pynput.keyboard import Key

        on_press, on_release = callbacks
        manager = WindowsHotkeyManager("ctrl+space", on_press, on_release)

        manager._on_key_press(Key.ctrl_l)
        manager._on_key_press(Key.space)
        manager._on_key_release(Key.space)

        on_press.assert_called_once()
        on_release.assert_called_once()

    def test_digit_combo_uses_virtual_key(self):
        """Digits share the arithmetic VK mapping (VK_0..VK_9 = 0x30..0x39)."""
        manager = WindowsHotkeyManager("ctrl+5", lambda: None, lambda: None)

        digit_keys = [k for k in manager._hotkey_set if getattr(k, "vk", None) == 0x35]
        assert digit_keys, f"no VK_5 key in parsed combo {manager._hotkey_set}"
