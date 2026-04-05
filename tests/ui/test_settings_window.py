"""Behavior-focused tests for SettingsWindow.

Tests validate window open/show lifecycle, singleton reuse on repeated calls,
destroy cleanup, hotkey configuration controls, autostart checkbox, model
selector, batch-save flow, error display, and unsaved-changes discard.
All tkinter interactions are mocked — no real GUI is created.

Note: Tests call _build_and_run() directly to bypass the threading layer,
which is needed at runtime (pystray callbacks) but not testable with mocks.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_var_mock():
    """Create a mock that behaves like a tkinter StringVar/BooleanVar."""
    _stored = [None]
    mock = MagicMock()
    mock.set.side_effect = lambda v: _stored.__setitem__(0, v)
    mock.get.side_effect = lambda: _stored[0]
    return mock


@pytest.fixture
def mock_tk(mocker):
    """Mock tkinter so no real GUI window is created."""
    mock_tk_cls = mocker.patch("audiby.ui.settings_window.tk.Tk")
    mock_toplevel_cls = mocker.patch("audiby.ui.settings_window.tk.Toplevel", create=True)
    mock_label_cls = mocker.patch("audiby.ui.settings_window.tk.Label", create=True)
    mock_button_cls = mocker.patch("audiby.ui.settings_window.tk.Button", create=True)
    mock_entry_cls = mocker.patch("audiby.ui.settings_window.tk.Entry", create=True)
    mock_frame_cls = mocker.patch("audiby.ui.settings_window.tk.Frame", create=True)
    mock_checkbutton_cls = mocker.patch("audiby.ui.settings_window.tk.Checkbutton", create=True)
    mock_combobox_cls = mocker.patch("audiby.ui.settings_window.ttk.Combobox", create=True)
    mock_stringvar_cls = mocker.patch("audiby.ui.settings_window.tk.StringVar", create=True)
    mock_booleanvar_cls = mocker.patch("audiby.ui.settings_window.tk.BooleanVar", create=True)

    # Each StringVar/BooleanVar call gets its own independent store
    mock_stringvar_cls.side_effect = lambda: _make_var_mock()
    mock_booleanvar_cls.side_effect = lambda: _make_var_mock()

    return {
        "Tk": mock_tk_cls,
        "Toplevel": mock_toplevel_cls,
        "Label": mock_label_cls,
        "Button": mock_button_cls,
        "Entry": mock_entry_cls,
        "Frame": mock_frame_cls,
        "Checkbutton": mock_checkbutton_cls,
        "Combobox": mock_combobox_cls,
        "StringVar": mock_stringvar_cls,
        "BooleanVar": mock_booleanvar_cls,
    }


@pytest.fixture
def mock_config():
    """Config mock returning per-key defaults."""
    cfg = MagicMock()
    _config_data = {
        "push_to_talk_key": "ctrl+space",
        "start_on_boot": False,
        "model_size": "base",
    }
    cfg.get.side_effect = lambda key, default=None: _config_data.get(key, default)
    return cfg


@pytest.fixture
def mock_on_save():
    """Callback mock for Save button — returns None (success) by default."""
    cb = MagicMock()
    cb.return_value = None
    return cb


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
        mocker.patch("audiby.ui.settings_window.threading.Thread")
        _open_window(settings_window)

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
        settings_window.destroy()

    def test_destroy_is_idempotent(self, settings_window, mock_tk):
        """Calling destroy() twice must not raise."""
        _open_window(settings_window)
        settings_window.destroy()
        settings_window.destroy()


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
        """The hotkey display must reflect the config value."""
        _open_window(settings_window)
        assert settings_window._bind_hotkey.get() == "ctrl+space"


class TestHotkeyCapture:
    """AC #2: User can capture a new hotkey combination."""

    def test_captured_hotkey_updates_display(self, settings_window, mock_config, mock_tk, mocker):
        """When a new valid hotkey is captured, the display field must update."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)

        settings_window._on_hotkey_captured("ctrl+z")

        assert settings_window._bind_hotkey.get() == "ctrl+z"

    def test_backtick_combo_is_normalized_for_validation(self, settings_window, mock_tk, mocker):
        """Ctrl+` should validate cleanly through the pynput formatter."""
        mock_parse = mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)

        settings_window._on_hotkey_captured("ctrl+`")

        mock_parse.assert_called_once_with("<ctrl>+`")

    def test_space_combo_uses_wrapped_special_key_format(self, settings_window, mock_tk, mocker):
        """Special keys like space should be wrapped for pynput validation."""
        mock_parse = mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)

        settings_window._on_hotkey_captured("ctrl+space")

        mock_parse.assert_called_once_with("<ctrl>+<space>")

    def test_control_character_letter_is_recovered_from_vk(self, settings_window):
        """Ctrl-held letters should resolve to printable tokens instead of control glyphs."""
        key = SimpleNamespace(char="\x18", name=None, vk=88)

        token = settings_window._resolve_key_token(key)

        assert token == "x"

    def test_backtick_is_recovered_from_windows_vk(self, settings_window):
        """OEM punctuation keys should resolve from vk when char is not usable."""
        key = SimpleNamespace(char=None, name=None, vk=192)

        token = settings_window._resolve_key_token(key)

        assert token == "`"


class TestHotkeyValidation:
    """AC #4: Invalid hotkey shows error and retains previous hotkey."""

    def test_invalid_hotkey_shows_error_label(self, settings_window, mock_config, mock_tk, mocker):
        """When an invalid hotkey is entered, an error message must be displayed."""
        mock_parse = mocker.patch("audiby.ui.settings_window.HotKey.parse",
                                  side_effect=ValueError("invalid combo"))
        _open_window(settings_window)
        settings_window._on_hotkey_captured("not_a_key+++")
        mock_parse.assert_called_once()

    def test_valid_hotkey_hides_error_label(self, settings_window, mock_config, mock_tk, mocker):
        """When a valid hotkey is entered, any error message must be hidden."""
        mock_parse = mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)
        settings_window._on_hotkey_captured("ctrl+shift+d")
        mock_parse.assert_called_once()

    def test_invalid_hotkey_does_not_stage_for_save(self, settings_window, mock_config, mock_tk, mocker):
        """An invalid hotkey must NOT be staged — display must restore previous value."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse",
                     side_effect=ValueError("bad"))
        _open_window(settings_window)

        settings_window._pre_capture_value = "ctrl+space"
        settings_window._on_hotkey_captured("bad+++key")

        assert settings_window._bind_hotkey.get() == "ctrl+space"

    def test_quoted_key_repr_is_unwrapped_before_validation(self, settings_window, mock_tk, mocker):
        """Quoted key repr tokens should be normalized before parse."""
        _open_window(settings_window)

        formatted = settings_window._to_pynput_format("ctrl+'`'")

        assert formatted == "<ctrl>+`"


# ---------------------------------------------------------------------------
# Autostart checkbox
# ---------------------------------------------------------------------------

class TestAutostartCheckbox:
    """Story 3.4 AC #1: Start on boot checkbox bound to config state."""

    def test_show_reads_autostart_from_config(self, settings_window, mock_config, mock_tk):
        """On show(), the autostart checkbox must read from config."""
        _open_window(settings_window)
        mock_config.get.assert_any_call("start_on_boot", False)

    def test_autostart_default_is_false(self, settings_window, mock_config, mock_tk):
        """Autostart defaults to unchecked when config returns False."""
        _open_window(settings_window)
        assert settings_window._autostart_value.get() is False

    def test_autostart_reflects_config_true(self, mock_tk, mock_on_save):
        """If config says autostart=True, the checkbox must be checked on open."""
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {
            "push_to_talk_key": "ctrl+space",
            "start_on_boot": True,
            "model_size": "base",
        }.get(key, default)

        from audiby.ui.settings_window import SettingsWindow
        sw = SettingsWindow(config=cfg, on_save=mock_on_save)
        _open_window(sw)
        assert sw._autostart_value.get() is True


# ---------------------------------------------------------------------------
# Model selector
# ---------------------------------------------------------------------------

class TestModelSelector:
    """Story 3.4 AC #2: Model selector populated from SUPPORTED_MODELS."""

    def test_show_reads_model_from_config(self, settings_window, mock_config, mock_tk):
        """On show(), the model selector must read from config."""
        _open_window(settings_window)
        mock_config.get.assert_any_call("model_size", "base")

    def test_model_default_is_base(self, settings_window, mock_config, mock_tk):
        """Model selector defaults to 'base' from config."""
        _open_window(settings_window)
        assert settings_window._model_value.get() == "base"

    def test_model_reflects_config_value(self, mock_tk, mock_on_save):
        """If config says model=medium, the selector must show medium on open."""
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {
            "push_to_talk_key": "ctrl+space",
            "start_on_boot": False,
            "model_size": "medium",
        }.get(key, default)

        from audiby.ui.settings_window import SettingsWindow
        sw = SettingsWindow(config=cfg, on_save=mock_on_save)
        _open_window(sw)
        assert sw._model_value.get() == "medium"

    def test_failed_download_reverts_selected_model(self, settings_window, mock_tk, mocker):
        """Failed interactive download should revert the staged model selection."""
        mocker.patch("audiby.ui.settings_window.model_manager.exists", return_value=False)
        dialog_cls = mocker.patch("audiby.ui.settings_window.DownloadDialog")
        dialog_cls.return_value.run.return_value = SimpleNamespace(
            status="failed",
            message="Failed to download the medium model.",
        )
        _open_window(settings_window)
        settings_window._model_value.set("medium")

        settings_window._on_model_selected()

        assert settings_window._model_value.get() == "base"
        settings_window._error_label.config.assert_called_with(
            text="Failed to download the medium model."
        )

    def test_successful_download_keeps_selected_model(self, settings_window, mock_tk, mocker):
        """Successful interactive download should keep the staged model selection."""
        mocker.patch("audiby.ui.settings_window.model_manager.exists", return_value=False)
        dialog_cls = mocker.patch("audiby.ui.settings_window.DownloadDialog")
        dialog_cls.return_value.run.return_value = SimpleNamespace(status="success", message=None)
        _open_window(settings_window)
        settings_window._model_value.set("medium")

        settings_window._on_model_selected()

        assert settings_window._model_value.get() == "medium"


# ---------------------------------------------------------------------------
# Save button — batch save flow
# ---------------------------------------------------------------------------

class TestSaveButton:
    """AC #3: Save passes all staged values to callback."""

    def test_save_passes_all_values_to_callback(self, settings_window, mock_config, mock_on_save, mock_tk, mocker):
        """Clicking Save must pass hotkey, autostart, and model to the on_save callback."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)

        settings_window._on_hotkey_captured("alt+z")
        settings_window._on_save_clicked()

        mock_on_save.assert_called_once_with("alt+z", False, "base")

    def test_save_closes_window_on_success(self, settings_window, mock_config, mock_on_save, mock_tk):
        """Window must close after successful save (callback returns None)."""
        _open_window(settings_window)
        settings_window._on_save_clicked()
        assert settings_window._window is None

    def test_save_shows_error_on_failure(self, settings_window, mock_config, mock_on_save, mock_tk):
        """Window must stay open and show error when callback returns error string."""
        mock_on_save.return_value = "Autostart failed"
        _open_window(settings_window)
        settings_window._on_save_clicked()
        # Window should still be open
        assert settings_window._window is not None

    def test_save_does_not_persist_config_directly(self, settings_window, mock_config, mock_on_save, mock_tk):
        """Settings window must NOT call config.set() or config.save() — orchestrator owns that."""
        _open_window(settings_window)
        settings_window._on_save_clicked()
        mock_config.set.assert_not_called()
        mock_config.save.assert_not_called()

    def test_save_without_changes_still_calls_callback(self, settings_window, mock_config, mock_on_save, mock_tk):
        """Save with no changes should still invoke the callback with current values."""
        _open_window(settings_window)
        settings_window._on_save_clicked()
        mock_on_save.assert_called_once_with("ctrl+space", False, "base")

    def test_error_label_wraps_and_repositions_window(self, settings_window, mock_tk):
        """Showing an error should wrap text and recompute anchored geometry."""
        _open_window(settings_window)

        settings_window._show_error(
            "This is a long validation error that should wrap instead of pushing the window wider."
        )

        settings_window._error_label.grid.assert_called_with(
            row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 5)
        )
        assert mock_tk["Tk"].return_value.geometry.call_count >= 2


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

        assert settings_window._bind_hotkey.get() == "ctrl+space"


# ---------------------------------------------------------------------------
# Unsaved-changes discard
# ---------------------------------------------------------------------------

class TestUnsavedChangesDiscard:
    """AC #5: Closing without Save discards changes; reopening shows original values."""

    def test_show_reloads_config_values(self, settings_window, mock_config, mock_tk):
        """Each _build_and_run() must reload all values from config."""
        _open_window(settings_window)
        settings_window._window = None
        _open_window(settings_window)

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
        _open_window(settings_window)

        settings_window._on_hotkey_captured("alt+z")
        settings_window._window = None
        _open_window(settings_window)

        assert settings_window._bind_hotkey.get() == "ctrl+space"

    def test_config_not_modified_without_save(self, settings_window, mock_config, mock_tk, mocker):
        """Closing without Save must not call config.set() or config.save()."""
        mocker.patch("audiby.ui.settings_window.HotKey.parse")
        _open_window(settings_window)
        settings_window._on_hotkey_captured("alt+z")
        mock_config.set.assert_not_called()
        mock_config.save.assert_not_called()
