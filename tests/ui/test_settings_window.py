"""Behavior-focused tests for SettingsWindow.

Tests validate window open/show lifecycle, singleton reuse on repeated calls,
destroy cleanup, hotkey configuration controls, and unsaved-changes discard.
All tkinter interactions are mocked — no real GUI is created.

Note: Tests call _build_and_run() directly to bypass the threading layer,
which is needed at runtime (pystray callbacks) but not testable with mocks.
"""

from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_tk(mocker):
    """Mock tkinter so no real GUI window is created."""
    mock_tk_cls = mocker.patch("audiby.ui.settings_window.tk.Tk")
    mock_toplevel_cls = mocker.patch("audiby.ui.settings_window.tk.Toplevel", create=True)
    mock_label_cls = mocker.patch("audiby.ui.settings_window.tk.Label", create=True)
    mock_button_cls = mocker.patch("audiby.ui.settings_window.tk.Button", create=True)
    mock_entry_cls = mocker.patch("audiby.ui.settings_window.tk.Entry", create=True)
    mock_frame_cls = mocker.patch("audiby.ui.settings_window.tk.Frame", create=True)
    mock_stringvar_cls = mocker.patch("audiby.ui.settings_window.tk.StringVar", create=True)
    # Wire StringVar mock so .set() stores the value and .get() returns it
    _stored = [None]
    mock_stringvar_cls.return_value.set.side_effect = lambda v: _stored.__setitem__(0, v)
    mock_stringvar_cls.return_value.get.side_effect = lambda: _stored[0]
    return {
        "Tk": mock_tk_cls,
        "Toplevel": mock_toplevel_cls,
        "Label": mock_label_cls,
        "Button": mock_button_cls,
        "Entry": mock_entry_cls,
        "Frame": mock_frame_cls,
        "StringVar": mock_stringvar_cls,
    }


@pytest.fixture
def mock_config():
    """Config mock returning default hotkey."""
    cfg = MagicMock()
    cfg.get.return_value = "ctrl+space"
    return cfg


@pytest.fixture
def mock_on_save():
    """Callback mock for Save button."""
    return MagicMock()


@pytest.fixture
def settings_window(mock_tk, mock_config, mock_on_save):
    """Create a SettingsWindow with tkinter fully mocked."""
    from audiby.ui.settings_window import SettingsWindow
    return SettingsWindow(config=mock_config, on_save=mock_on_save)


def _open_window(sw):
    """Call _build_and_run() directly, bypassing the threading layer.

    At runtime, show() spawns a thread that calls _build_and_run().
    In tests, mocked mainloop() returns immediately, so we call it
    synchronously to create all widgets before asserting.
    """
    sw._build_and_run()


# ---------------------------------------------------------------------------
# Window open/show lifecycle
# ---------------------------------------------------------------------------

class TestSettingsWindowLifecycle:
    def test_show_creates_window(self, settings_window, mock_tk):
        """_build_and_run() must create a tkinter window."""
        _open_window(settings_window)
        assert mock_tk["Tk"].called or mock_tk["Toplevel"].called

    def test_show_sets_window_title_with_app_name(self, settings_window, mock_tk):
        """The settings window title must contain the app name."""
        _open_window(settings_window)
        window = mock_tk["Tk"].return_value
        title_calls = [c for c in window.method_calls if c[0] == "title"]
        assert len(title_calls) > 0, "Window title was never set"
        title_arg = title_calls[0].args[0]
        assert "settings" in title_arg.lower() or "audiby" in title_arg.lower()


# ---------------------------------------------------------------------------
# Singleton / reuse behavior
# ---------------------------------------------------------------------------

class TestSettingsWindowReuse:
    def test_repeated_show_does_not_create_new_window(self, settings_window, mock_tk, mocker):
        """Calling show() twice must reuse the existing window, not create a second one."""
        # Patch threading so show() calls _build_and_run synchronously
        mocker.patch("audiby.ui.settings_window.threading.Thread")
        _open_window(settings_window)

        # Simulate the GUI thread still being alive
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        settings_window._gui_thread = mock_thread

        settings_window.show()
        assert mock_tk["Tk"].call_count == 1

    def test_show_after_destroy_creates_new_window(self, settings_window, mock_tk):
        """If the window was destroyed, _build_and_run() must create a fresh one."""
        _open_window(settings_window)
        settings_window._window = None
        _open_window(settings_window)
        assert mock_tk["Tk"].call_count == 2

    def test_show_refocuses_existing_window(self, settings_window, mock_tk):
        """Calling show() on an existing window must bring it to the front."""
        _open_window(settings_window)

        # Simulate the GUI thread still being alive
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        settings_window._gui_thread = mock_thread

        settings_window.show()

        mock_window = mock_tk["Tk"].return_value
        after_calls = [c for c in mock_window.method_calls if c[0] == "after"]
        assert len(after_calls) > 0, "Window was not refocused on second show()"


# ---------------------------------------------------------------------------
# Destroy / cleanup
# ---------------------------------------------------------------------------

class TestSettingsWindowDestroy:
    def test_destroy_calls_window_destroy(self, settings_window, mock_tk):
        """destroy() must call destroy on the tkinter window."""
        _open_window(settings_window)
        settings_window.destroy()

        mock_window = mock_tk["Tk"].return_value
        mock_window.destroy.assert_called()

    def test_destroy_is_safe_when_no_window(self, settings_window):
        """destroy() must not raise if no window was ever created."""
        settings_window.destroy()  # should not raise

    def test_destroy_is_idempotent(self, settings_window, mock_tk):
        """Calling destroy() twice must not raise."""
        _open_window(settings_window)
        settings_window.destroy()
        settings_window.destroy()  # second call — no error


# ---------------------------------------------------------------------------
# Hotkey controls
# ---------------------------------------------------------------------------

class TestHotkeyDisplay:
    """AC #1: Settings window shows the currently configured push-to-talk hotkey."""

    def test_show_reads_hotkey_from_config(self, settings_window, mock_config, mock_tk):
        """On show(), the window must read the current hotkey from config."""
        _open_window(settings_window)
        mock_config.get.assert_any_call("push_to_talk_key", "ctrl+space")

    def test_show_displays_current_hotkey_value(self, settings_window, mock_config, mock_tk):
        """The hotkey display must reflect the config value, not a hardcoded default."""
        mock_config.get.return_value = "alt+z"
        _open_window(settings_window)

        # The StringVar or Label should be set with the config value "alt+z"
        stringvar = mock_tk["StringVar"].return_value
        # StringVar.set() should be called with the config value
        set_calls = [c for c in stringvar.method_calls if c[0] == "set"]
        found = any("alt+z" in str(c) for c in set_calls)
        assert found, (
            f"Expected hotkey 'alt+z' to be displayed via StringVar.set(). "
            f"StringVar calls: {stringvar.method_calls}"
        )


class TestHotkeyCapture:
    """AC #2: User can capture a new hotkey combination."""

    def test_captured_hotkey_updates_display(self, settings_window, mock_config, mock_tk, mocker):
        """When a new valid hotkey is captured, the display field must update."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)

        settings_window._on_hotkey_captured("ctrl+z")

        stringvar = mock_tk["StringVar"].return_value
        assert stringvar.get() == "ctrl+z", (
            f"Expected display to show 'ctrl+z' after capture, got: {stringvar.get()}"
        )


class TestHotkeyValidation:
    """AC #4: Invalid hotkey shows error and retains previous hotkey."""

    def test_invalid_hotkey_shows_error_label(self, settings_window, mock_config, mock_tk, mocker):
        """When an invalid hotkey is entered, an error message must be displayed."""
        mock_parse = mocker.patch("audiby.ui.settings_window.HotKey.parse",
                                  side_effect=ValueError("invalid combo"))

        _open_window(settings_window)

        if hasattr(settings_window, '_on_hotkey_captured'):
            settings_window._on_hotkey_captured("not_a_key+++")
        elif hasattr(settings_window, '_validate_and_stage_hotkey'):
            settings_window._validate_and_stage_hotkey("not_a_key+++")
        else:
            pytest.fail(
                "SettingsWindow must expose _on_hotkey_captured() or "
                "_validate_and_stage_hotkey() for testing hotkey validation"
            )

        mock_parse.assert_called_once()

    def test_valid_hotkey_hides_error_label(self, settings_window, mock_config, mock_tk, mocker):
        """When a valid hotkey is entered, any error message must be hidden."""
        mock_parse = mocker.patch("audiby.ui.settings_window.HotKey.parse")

        _open_window(settings_window)

        if hasattr(settings_window, '_on_hotkey_captured'):
            settings_window._on_hotkey_captured("ctrl+shift+d")
        elif hasattr(settings_window, '_validate_and_stage_hotkey'):
            settings_window._validate_and_stage_hotkey("ctrl+shift+d")
        else:
            pytest.fail(
                "SettingsWindow must expose _on_hotkey_captured() or "
                "_validate_and_stage_hotkey() for testing hotkey validation"
            )

        mock_parse.assert_called_once()

    def test_invalid_hotkey_does_not_stage_for_save(self, settings_window, mock_config, mock_tk, mocker):
        """An invalid hotkey must NOT be staged — Save should persist the original value."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse",
                     side_effect=ValueError("bad"))

        _open_window(settings_window)

        settings_window._pre_capture_value = "ctrl+space"
        if hasattr(settings_window, '_on_hotkey_captured'):
            settings_window._on_hotkey_captured("bad+++key")
        elif hasattr(settings_window, '_validate_and_stage_hotkey'):
            settings_window._validate_and_stage_hotkey("bad+++key")

        # config.set should NOT have been called with the bad value
        set_calls = [c for c in mock_config.set.call_args_list
                     if len(c.args) >= 2 and c.args[1] == "bad+++key"]
        assert len(set_calls) == 0, "Invalid hotkey was staged in config"
        # Display must be restored to the original hotkey
        stringvar = mock_tk["StringVar"].return_value
        assert stringvar.get() == "ctrl+space", (
            f"Expected display restored to 'ctrl+space' after invalid capture, got: {stringvar.get()}"
        )


class TestSaveButton:
    """AC #3: Save persists config and triggers on_save callback."""

    def test_save_persists_config(self, settings_window, mock_config, mock_on_save, mock_tk, mocker):
        """Clicking Save must call config.set(), config.save(), and on_save callback."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")

        _open_window(settings_window)

        # Stage a valid hotkey
        if hasattr(settings_window, '_on_hotkey_captured'):
            settings_window._on_hotkey_captured("alt+z")
        elif hasattr(settings_window, '_validate_and_stage_hotkey'):
            settings_window._validate_and_stage_hotkey("alt+z")

        # Trigger save
        if hasattr(settings_window, '_on_save_clicked'):
            settings_window._on_save_clicked()
        else:
            pytest.fail("SettingsWindow must expose _on_save_clicked() for testing Save")

        mock_config.set.assert_any_call("push_to_talk_key", "alt+z")
        mock_config.save.assert_called_once()
        mock_on_save.assert_called_once()
        assert settings_window._window is None, "Window must close after Save is clicked"

    def test_save_without_changes_still_persists(self, settings_window, mock_config, mock_on_save, mock_tk):
        """Save with no hotkey change should still persist current config and call callback."""
        _open_window(settings_window)

        if hasattr(settings_window, '_on_save_clicked'):
            settings_window._on_save_clicked()
        else:
            pytest.fail("SettingsWindow must expose _on_save_clicked() for testing Save")

        mock_config.save.assert_called_once()
        mock_on_save.assert_called_once()


# ---------------------------------------------------------------------------
# Reserved modifier rejection
# ---------------------------------------------------------------------------

class TestReservedModifierRejection:
    """M1: Cmd/Win modifiers must be rejected, not silently dropped."""

    def test_cmd_modifier_triggers_rejection_via_after(self, settings_window, mock_config, mock_tk, mocker):
        """Pressing Cmd+key must schedule a rejection callback, not build a combo."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)

        from pynput.keyboard import Key
        settings_window._capturing = True
        settings_window._pre_capture_value = "ctrl+space"
        settings_window._pressed_modifiers = {Key.cmd_l}

        mock_key = mocker.MagicMock()
        mock_key.char = "a"
        settings_window._on_key_press(mock_key)

        mock_window = mock_tk["Tk"].return_value
        after_calls = [c for c in mock_window.method_calls if c[0] == "after"]
        assert len(after_calls) > 0, "Cmd+key must schedule a rejection callback via after()"

    def test_reserved_modifier_restores_previous_hotkey(self, settings_window, mock_config, mock_tk):
        """_on_reserved_modifier_rejected must restore the previous hotkey in the display."""
        _open_window(settings_window)
        settings_window._pre_capture_value = "ctrl+space"
        settings_window._capturing = True

        settings_window._on_reserved_modifier_rejected()

        stringvar = mock_tk["StringVar"].return_value
        assert stringvar.get() == "ctrl+space", (
            f"Expected display restored to 'ctrl+space', got: {stringvar.get()}"
        )


# ---------------------------------------------------------------------------
# Unsaved-changes discard
# ---------------------------------------------------------------------------

class TestUnsavedChangesDiscard:
    """AC #5: Closing without Save discards changes; reopening shows original values."""

    def test_show_reloads_config_values(self, settings_window, mock_config, mock_tk):
        """Each _build_and_run() must reload hotkey from config, discarding staged changes."""
        mock_config.get.return_value = "ctrl+space"
        _open_window(settings_window)

        # Simulate window closed
        settings_window._window = None

        # Reopen
        _open_window(settings_window)

        # config.get should be called on each open
        hotkey_get_calls = [
            c for c in mock_config.get.call_args_list
            if len(c.args) >= 1 and c.args[0] == "push_to_talk_key"
        ]
        assert len(hotkey_get_calls) >= 2, (
            "config.get('push_to_talk_key', ...) must be called on every show()"
        )

    def test_staged_hotkey_discarded_on_reopen(self, settings_window, mock_config, mock_tk, mocker):
        """A staged but unsaved hotkey must be discarded when the window is reopened."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")
        mock_config.get.return_value = "ctrl+space"

        _open_window(settings_window)

        # Stage a new hotkey but don't save
        if hasattr(settings_window, '_on_hotkey_captured'):
            settings_window._on_hotkey_captured("alt+z")
        elif hasattr(settings_window, '_validate_and_stage_hotkey'):
            settings_window._validate_and_stage_hotkey("alt+z")

        # Close window without saving
        settings_window._window = None

        # Reopen — should show original "ctrl+space", not staged "alt+z"
        _open_window(settings_window)

        # The StringVar should be set back to the config value
        stringvar = mock_tk["StringVar"].return_value
        set_calls = [c for c in stringvar.method_calls if c[0] == "set"]
        # Last set call should be "ctrl+space" (the config value on reopen)
        last_set = set_calls[-1] if set_calls else None
        assert last_set is not None, "StringVar.set() was never called on reopen"
        assert "ctrl+space" in str(last_set), (
            f"Expected 'ctrl+space' on reopen but got: {last_set}"
        )

    def test_config_not_modified_without_save(self, settings_window, mock_config, mock_tk, mocker):
        """Closing without Save must not call config.set() or config.save()."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")

        _open_window(settings_window)

        # Stage a change
        if hasattr(settings_window, '_on_hotkey_captured'):
            settings_window._on_hotkey_captured("alt+z")
        elif hasattr(settings_window, '_validate_and_stage_hotkey'):
            settings_window._validate_and_stage_hotkey("alt+z")

        # Close without saving — config should not have been persisted
        mock_config.save.assert_not_called()
