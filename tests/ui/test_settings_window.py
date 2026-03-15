"""Behavior-focused tests for SettingsWindow.

Tests validate window open/show lifecycle, singleton reuse on repeated calls,
and destroy cleanup. All tkinter interactions are mocked — no real GUI is created.
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
    return mock_tk_cls, mock_toplevel_cls


@pytest.fixture
def settings_window(mock_tk):
    """Create a SettingsWindow with tkinter fully mocked."""
    from audiby.ui.settings_window import SettingsWindow
    return SettingsWindow()


# ---------------------------------------------------------------------------
# Window open/show lifecycle (AC: #3 — Story 3.1 scope)
# ---------------------------------------------------------------------------

class TestSettingsWindowLifecycle:
    def test_show_creates_window(self, settings_window, mock_tk):
        """show() must create a tkinter window."""
        settings_window.show()
        # At least one tkinter window creation call should have happened
        mock_tk_cls, mock_toplevel_cls = mock_tk
        assert mock_tk_cls.called or mock_toplevel_cls.called

    def test_show_sets_window_title_with_app_name(self, settings_window, mock_tk):
        """The settings window title must contain the app name."""
        settings_window.show()
        mock_tk_cls, _ = mock_tk
        window = mock_tk_cls.return_value
        # title() should be called with something containing "Audiby" or "Settings"
        title_calls = [c for c in window.method_calls if c[0] == "title"]
        assert len(title_calls) > 0, "Window title was never set"
        title_arg = title_calls[0].args[0]
        assert "settings" in title_arg.lower() or "audiby" in title_arg.lower()


# ---------------------------------------------------------------------------
# Singleton / reuse behavior (AC: #3 — repeated clicks)
# ---------------------------------------------------------------------------

class TestSettingsWindowReuse:
    def test_repeated_show_does_not_create_new_window(self, settings_window, mock_tk):
        """Calling show() twice must reuse the existing window, not create a second one."""
        mock_tk_cls, _ = mock_tk
        mock_window = mock_tk_cls.return_value
        # Simulate window still exists (winfo_exists returns True)
        mock_window.winfo_exists.return_value = True

        settings_window.show()
        settings_window.show()

        # Tk() should only be called once
        assert mock_tk_cls.call_count == 1

    def test_show_after_destroy_creates_new_window(self, settings_window, mock_tk):
        """If the window was destroyed, show() must create a fresh one."""
        mock_tk_cls, _ = mock_tk
        mock_window = mock_tk_cls.return_value

        settings_window.show()

        # Simulate window destroyed
        mock_window.winfo_exists.return_value = False

        settings_window.show()
        assert mock_tk_cls.call_count == 2

    def test_show_refocuses_existing_window(self, settings_window, mock_tk):
        """Calling show() on an existing window must bring it to the front."""
        mock_tk_cls, _ = mock_tk
        mock_window = mock_tk_cls.return_value
        mock_window.winfo_exists.return_value = True

        settings_window.show()
        settings_window.show()

        # Should attempt to raise/focus the window
        focus_calls = [c for c in mock_window.method_calls
                       if any(keyword in c[0] for keyword in ("lift", "focus", "deiconify"))]
        assert len(focus_calls) > 0, "Window was not refocused on second show()"


# ---------------------------------------------------------------------------
# Destroy / cleanup
# ---------------------------------------------------------------------------

class TestSettingsWindowDestroy:
    def test_destroy_calls_window_destroy(self, settings_window, mock_tk):
        """destroy() must call destroy on the tkinter window."""
        mock_tk_cls, _ = mock_tk
        mock_window = mock_tk_cls.return_value
        mock_window.winfo_exists.return_value = True

        settings_window.show()
        settings_window.destroy()

        mock_window.destroy.assert_called()

    def test_destroy_is_safe_when_no_window(self, settings_window):
        """destroy() must not raise if no window was ever created."""
        settings_window.destroy()  # should not raise

    def test_destroy_is_idempotent(self, settings_window, mock_tk):
        """Calling destroy() twice must not raise."""
        settings_window.show()
        settings_window.destroy()
        settings_window.destroy()  # second call — no error
