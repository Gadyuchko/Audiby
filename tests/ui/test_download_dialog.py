"""Tests for DownloadDialog with mocked model_manager and tkinter.

No real network calls or GUI windows.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_tk(mocker):
    """Mock tkinter so no real GUI window is created."""
    mock_tk_cls = mocker.patch("audiby.ui.download_dialog.tk.Tk")
    mock_toplevel_cls = mocker.patch("audiby.ui.download_dialog.tk.Toplevel", create=True)
    mock_label_cls = mocker.patch("audiby.ui.download_dialog.ttk.Label", create=True)
    mock_progressbar_cls = mocker.patch("audiby.ui.download_dialog.ttk.Progressbar", create=True)
    return {
        "Tk": mock_tk_cls,
        "Toplevel": mock_toplevel_cls,
        "Label": mock_label_cls,
        "Progressbar": mock_progressbar_cls,
    }


@pytest.fixture
def mock_model_manager(mocker):
    """Mock model_manager.download() — no real network."""
    return mocker.patch("audiby.ui.download_dialog.model_manager")


@pytest.fixture
def dialog(mock_tk, mock_model_manager):
    """Create a DownloadDialog with all externals mocked."""
    from audiby.ui.download_dialog import DownloadDialog
    return DownloadDialog("small")


class TestDownloadDialogSuccess:
    """Subtask 4.1: dialog runs download on worker thread and reports success."""

    def test_success_flag_true_on_successful_download(self, dialog, mock_model_manager, mock_tk):
        """After a successful download, dialog.success must be True."""
        # mainloop will call destroy scheduled by worker, simulate immediate return
        mock_tk["Tk"].return_value.mainloop.side_effect = lambda: None
        mock_tk["Tk"].return_value.after.side_effect = lambda _, fn: fn()

        # download succeeds
        mock_model_manager.download.return_value = None

        dialog.run()

        # Give worker thread a moment — but since mainloop is mocked, the flow is:
        # run() → starts worker → mainloop() returns immediately
        # Worker runs in background, so we need to wait briefly
        import time
        time.sleep(0.2)

        assert dialog.success is True
        mock_model_manager.download.assert_called_once_with("small")

    def test_dialog_creates_window(self, dialog, mock_tk, mock_model_manager):
        """run() must create a tkinter window."""
        mock_tk["Tk"].return_value.mainloop.side_effect = lambda: None
        dialog.run()
        mock_tk["Tk"].assert_called_once()


class TestDownloadDialogFailure:
    """Subtask 4.3: dialog returns failure when download raises."""

    def test_success_flag_false_on_download_failure(self, dialog, mock_model_manager, mock_tk):
        """After a failed download, dialog.success must be False."""
        mock_tk["Tk"].return_value.mainloop.side_effect = lambda: None
        mock_tk["Tk"].return_value.after.side_effect = lambda _, fn: fn()
        mock_model_manager.download.side_effect = Exception("network error")

        dialog.run()

        import time
        time.sleep(0.2)

        assert dialog.success is False


class TestDownloadDialogProgressBar:
    """Subtask 4.2: indeterminate progress bar while download runs."""

    def test_progress_bar_uses_indeterminate_mode(self, dialog, mock_tk, mock_model_manager):
        """Progress bar must use indeterminate mode (no progress callback available)."""
        mock_tk["Tk"].return_value.mainloop.side_effect = lambda: None
        dialog.run()

        mock_tk["Progressbar"].assert_called_once()
        call_kwargs = mock_tk["Progressbar"].call_args
        # Check mode is indeterminate — could be in args or kwargs
        all_args = str(call_kwargs)
        assert "indeterminate" in all_args

    def test_progress_bar_started(self, dialog, mock_tk, mock_model_manager):
        """Progress bar animation must be started before download begins."""
        mock_tk["Tk"].return_value.mainloop.side_effect = lambda: None
        dialog.run()

        mock_tk["Progressbar"].return_value.start.assert_called_once()


class TestDownloadDialogWithParent:
    """L2: Toplevel branch — dialog created as child of an existing window."""

    def test_toplevel_used_when_parent_provided(self, mock_tk, mock_model_manager):
        """With a parent, dialog must use Toplevel instead of Tk."""
        from audiby.ui.download_dialog import DownloadDialog
        parent = MagicMock()
        parent.wait_window.side_effect = lambda _: None
        dialog = DownloadDialog("small", parent=parent)

        dialog.run()

        mock_tk["Toplevel"].assert_called_once_with(parent)
        mock_tk["Tk"].assert_not_called()

    def test_toplevel_grabs_focus(self, mock_tk, mock_model_manager):
        """Toplevel dialog must call grab_set() to block parent interaction."""
        from audiby.ui.download_dialog import DownloadDialog
        parent = MagicMock()
        parent.wait_window.side_effect = lambda _: None
        dialog = DownloadDialog("small", parent=parent)

        dialog.run()

        mock_tk["Toplevel"].return_value.grab_set.assert_called_once()

    def test_toplevel_success_on_download(self, mock_tk, mock_model_manager):
        """Toplevel dialog must set success=True after successful download."""
        from audiby.ui.download_dialog import DownloadDialog
        parent = MagicMock()
        parent.wait_window.side_effect = lambda _: None
        mock_tk["Toplevel"].return_value.after.side_effect = lambda _, fn: fn()
        mock_model_manager.download.return_value = None
        dialog = DownloadDialog("small", parent=parent)

        dialog.run()

        import time
        time.sleep(0.2)

        assert dialog.success is True
