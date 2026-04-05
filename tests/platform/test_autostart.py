"""Tests for WindowsAutostart using mocked winreg calls.

No real registry access — all winreg operations are mocked.
"""

from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture
def mock_winreg(mocker):
    """Mock winreg module inside _autostart_win."""
    return mocker.patch("audiby.platform._autostart_win.winreg")


@pytest.fixture
def autostart(mock_winreg):
    """Create a WindowsAutostart instance with winreg mocked."""
    from audiby.platform._autostart_win import WindowsAutostart
    return WindowsAutostart()


class TestWindowsAutostartEnable:
    """enable() writes to the Run registry key."""

    def test_enable_opens_run_key_with_write_access(self, autostart, mock_winreg):
        autostart.enable("/path/to/audiby.exe")
        mock_winreg.OpenKey.assert_called_once_with(
            mock_winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
            0,
            mock_winreg.KEY_SET_VALUE,
        )

    def test_enable_sets_registry_value_with_app_name(self, autostart, mock_winreg):
        autostart.enable("/path/to/audiby.exe")
        mock_winreg.SetValueEx.assert_called_once()
        args = mock_winreg.SetValueEx.call_args.args
        # value name is APP_NAME ("Audiby")
        assert args[1] == "Audiby"

    def test_enable_quotes_exe_path(self, autostart, mock_winreg):
        """Stored command line must be quoted for paths with spaces."""
        autostart.enable(r"C:\Program Files\Audiby\audiby.exe")
        args = mock_winreg.SetValueEx.call_args.args
        stored_path = args[4]
        assert stored_path.startswith('"') and stored_path.endswith('"')
        assert r"C:\Program Files\Audiby\audiby.exe" in stored_path

    def test_enable_propagates_registry_error(self, autostart, mock_winreg):
        """Registry write failure must propagate to caller for orchestrator rollback."""
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.SetValueEx.side_effect = OSError("Access denied")
        with pytest.raises(OSError):
            autostart.enable("/path/to/audiby.exe")


class TestWindowsAutostartDisable:
    """disable() removes the Run registry value."""

    def test_disable_deletes_registry_value(self, autostart, mock_winreg):
        autostart.disable()
        mock_winreg.DeleteValue.assert_called_once()
        args = mock_winreg.DeleteValue.call_args.args
        assert args[1] == "Audiby"

    def test_disable_handles_missing_value_gracefully(self, autostart, mock_winreg):
        """If value doesn't exist (already disabled), disable() must not raise."""
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.DeleteValue.side_effect = FileNotFoundError
        # Should not raise
        autostart.disable()


class TestWindowsAutostartIsEnabled:
    """is_enabled() checks the Run registry value against current exe."""

    def test_is_enabled_returns_true_when_value_matches_exe(self, autostart, mock_winreg, mocker):
        import sys
        exe = sys.executable
        mock_winreg.QueryValueEx.return_value = (f'"{exe}"', 1)
        assert autostart.is_enabled() is True

    def test_is_enabled_returns_false_when_value_is_stale_path(self, autostart, mock_winreg):
        mock_winreg.QueryValueEx.return_value = (r'"C:\old\path\audiby.exe"', 1)
        assert autostart.is_enabled() is False

    def test_is_enabled_returns_false_when_value_missing(self, autostart, mock_winreg):
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError
        assert autostart.is_enabled() is False

    def test_is_enabled_opens_key_with_read_access(self, autostart, mock_winreg):
        mock_winreg.QueryValueEx.return_value = (r'"C:\some\path"', 1)
        autostart.is_enabled()
        mock_winreg.OpenKey.assert_called_once_with(
            mock_winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
            0,
            mock_winreg.KEY_READ,
        )
