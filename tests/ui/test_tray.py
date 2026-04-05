"""Behavior-focused tests for TrayController.

Tests validate menu wiring, callback dispatch, and graceful stop signaling
using mocked pystray. No real tray backend is started.
"""

import threading
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pystray(mocker):
    """Mock pystray module so no real system tray is created."""
    mock_icon_cls = mocker.patch("audiby.ui.tray.pystray.Icon")
    mock_menu_cls = mocker.patch("audiby.ui.tray.pystray.Menu")
    mock_item_cls = mocker.patch("audiby.ui.tray.pystray.MenuItem")
    return mock_icon_cls, mock_menu_cls, mock_item_cls


@pytest.fixture
def mock_image(mocker):
    """Mock PIL Image.open so no real file I/O occurs."""
    mock_open = mocker.patch("audiby.ui.tray.Image.open")
    mock_open.return_value = MagicMock(name="fake_icon_image")
    return mock_open


@pytest.fixture
def callbacks():
    """Provide mock callbacks for tray menu actions."""
    return {
        "on_settings": MagicMock(name="on_settings"),
        "on_open_log_folder": MagicMock(name="on_open_log_folder"),
        "on_quit": MagicMock(name="on_quit"),
    }


@pytest.fixture
def tray_controller(mock_pystray, mock_image, callbacks):
    """Create a TrayController with all dependencies mocked."""
    from audiby.ui.tray import TrayController
    return TrayController(
        on_settings=callbacks["on_settings"],
        on_open_log_folder=callbacks["on_open_log_folder"],
        on_quit=callbacks["on_quit"],
    )


# ---------------------------------------------------------------------------
# Menu construction and wiring (AC: #2)
# ---------------------------------------------------------------------------

class TestMenuConstruction:
    def test_icon_created_with_app_name(self, tray_controller, mock_pystray):
        """pystray.Icon must be created with the application name."""
        icon_cls, _, _ = mock_pystray
        assert icon_cls.called
        args, kwargs = icon_cls.call_args
        # First positional arg or 'name' kwarg should contain app name
        name = args[0] if args else kwargs.get("name", "")
        assert "audiby" in name.lower() or "Audiby" in name

    def test_icon_created_with_hover_title(self, tray_controller, mock_pystray):
        """pystray.Icon should expose the app name as the hover title."""
        icon_cls, _, _ = mock_pystray
        _, kwargs = icon_cls.call_args
        assert kwargs["title"] == "Audiby"

    def test_menu_has_settings_item(self, tray_controller, mock_pystray):
        """Context menu must include a 'Settings' item."""
        _, _, item_cls = mock_pystray
        item_labels = [
            c.args[0] for c in item_cls.call_args_list if c.args
        ]
        assert any("settings" in label.lower() for label in item_labels), \
            f"No 'Settings' item found in menu items: {item_labels}"

    def test_menu_has_open_log_folder_item(self, tray_controller, mock_pystray):
        """Context menu must include an 'Open Log Folder' item."""
        _, _, item_cls = mock_pystray
        item_labels = [
            c.args[0] for c in item_cls.call_args_list if c.args
        ]
        assert any("log" in label.lower() for label in item_labels), \
            f"No 'Open Log Folder' item found in menu items: {item_labels}"

    def test_menu_has_quit_item(self, tray_controller, mock_pystray):
        """Context menu must include a 'Quit' item."""
        _, _, item_cls = mock_pystray
        item_labels = [
            c.args[0] for c in item_cls.call_args_list if c.args
        ]
        assert any("quit" in label.lower() for label in item_labels), \
            f"No 'Quit' item found in menu items: {item_labels}"


# ---------------------------------------------------------------------------
# Callback dispatch (AC: #2, #3, #4)
# ---------------------------------------------------------------------------

class TestCallbackDispatch:
    def test_settings_callback_invokes_on_settings(self, tray_controller, callbacks):
        """Selecting 'Settings' must invoke the on_settings callback."""
        tray_controller._on_settings_clicked(None, None)
        callbacks["on_settings"].assert_called_once()

    def test_open_log_folder_callback_invokes_handler(self, tray_controller, callbacks):
        """Selecting 'Open Log Folder' must invoke the on_open_log_folder callback."""
        tray_controller._on_open_log_folder_clicked(None, None)
        callbacks["on_open_log_folder"].assert_called_once()

    def test_quit_callback_invokes_on_quit(self, tray_controller, callbacks):
        """Selecting 'Quit' must invoke the on_quit callback."""
        tray_controller._on_quit_clicked(None, None)
        callbacks["on_quit"].assert_called_once()

    def test_quit_callback_stops_icon(self, tray_controller, mock_pystray):
        """Selecting 'Quit' must stop the pystray icon loop."""
        icon_cls, _, _ = mock_pystray
        mock_icon = icon_cls.return_value
        tray_controller._on_quit_clicked(None, None)
        mock_icon.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Lifecycle — start and stop (AC: #1, #4)
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_start_calls_icon_run(self, tray_controller, mock_pystray):
        """start() must call pystray Icon.run() to begin the tray loop."""
        icon_cls, _, _ = mock_pystray
        mock_icon = icon_cls.return_value
        tray_controller.start()
        mock_icon.run.assert_called_once()

    def test_stop_calls_icon_stop(self, tray_controller, mock_pystray):
        """stop() must call pystray Icon.stop() to terminate the tray loop."""
        icon_cls, _, _ = mock_pystray
        mock_icon = icon_cls.return_value
        tray_controller.stop()
        mock_icon.stop.assert_called_once()

    def test_stop_is_idempotent(self, tray_controller, mock_pystray):
        """Calling stop() multiple times must not raise."""
        icon_cls, _, _ = mock_pystray
        mock_icon = icon_cls.return_value
        tray_controller.stop()
        tray_controller.stop()
        # Should not raise

    def test_icon_loaded_from_assets(self, mock_image, tray_controller):
        """Tray icon image must be loaded from assets/icon.png."""
        mock_image.assert_called_once()
        path_arg = str(mock_image.call_args[0][0])
        assert "icon.png" in path_arg


# ---------------------------------------------------------------------------
# Icon image loading failure (AC: #1)
# ---------------------------------------------------------------------------

class TestIconLoadFailure:
    def test_missing_icon_raises_with_clear_message(self, mock_pystray, mocker, callbacks):
        """If icon.png is missing, TrayController must raise with a clear error."""
        mock_open = mocker.patch("audiby.ui.tray.Image.open", side_effect=FileNotFoundError("icon.png not found"))
        from audiby.ui.tray import TrayController
        with pytest.raises(FileNotFoundError):
            TrayController(
                on_settings=callbacks["on_settings"],
                on_open_log_folder=callbacks["on_open_log_folder"],
                on_quit=callbacks["on_quit"],
            )
