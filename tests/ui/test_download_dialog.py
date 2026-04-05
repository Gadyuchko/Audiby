"""Tests for DownloadDialog with mocked model_manager and tkinter."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from audiby.constants import MODEL_DOWNLOAD_STATUS_MESSAGE


class _ImmediateThread:
    """Thread test double that executes work synchronously on start()."""

    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args
        self.daemon = daemon

    def start(self):
        if self._target is not None:
            self._target(*self._args)


@pytest.fixture
def mock_tk(mocker):
    """Mock tkinter so no real GUI window is created."""
    mock_tk_cls = mocker.patch("audiby.ui.download_dialog.tk.Tk")
    mock_toplevel_cls = mocker.patch("audiby.ui.download_dialog.tk.Toplevel", create=True)
    mock_label_cls = mocker.patch("audiby.ui.download_dialog.ttk.Label", create=True)
    mock_progressbar_cls = mocker.patch("audiby.ui.download_dialog.ttk.Progressbar", create=True)
    mock_retry = mocker.patch("audiby.ui.download_dialog.messagebox.askretrycancel")
    mock_thread = mocker.patch(
        "audiby.ui.download_dialog.threading.Thread",
        side_effect=lambda target=None, args=(), daemon=None: _ImmediateThread(target, args, daemon),
    )

    tk_window = MagicMock()
    tk_window.after.side_effect = lambda _delay, callback: callback()
    tk_window.mainloop.side_effect = lambda: None
    mock_tk_cls.return_value = tk_window

    toplevel_window = MagicMock()
    toplevel_window.after.side_effect = lambda _delay, callback: callback()
    mock_toplevel_cls.return_value = toplevel_window

    return {
        "Tk": mock_tk_cls,
        "Toplevel": mock_toplevel_cls,
        "Label": mock_label_cls,
        "Progressbar": mock_progressbar_cls,
        "retry": mock_retry,
        "Thread": mock_thread,
        "tk_window": tk_window,
        "toplevel_window": toplevel_window,
    }


@pytest.fixture
def mock_model_manager(mocker):
    """Mock model_manager.download() so no real network is touched."""
    return mocker.patch("audiby.ui.download_dialog.model_manager")


@pytest.fixture
def dialog(mock_tk, mock_model_manager):
    """Create a DownloadDialog with all externals mocked."""
    from audiby.ui.download_dialog import DownloadDialog

    return DownloadDialog("small")


class TestDownloadDialogDisplay:
    def test_dialog_renders_model_name_size_and_status(self, dialog, mock_tk):
        """Dialog should render model name, display size, and status copy."""
        dialog.run()

        label_texts = [call.kwargs["text"] for call in mock_tk["Label"].call_args_list]
        assert "Downloading Whisper model: small" in label_texts
        assert "Download size: 466 MB" in label_texts
        assert MODEL_DOWNLOAD_STATUS_MESSAGE in label_texts

    def test_progress_bar_uses_indeterminate_mode(self, dialog, mock_tk):
        """Dialog must keep the progress bar indeterminate."""
        dialog.run()

        assert mock_tk["Progressbar"].call_args.kwargs["mode"] == "indeterminate"
        assert mock_tk["Progressbar"].return_value.start.call_count >= 1


class TestDownloadDialogResults:
    def test_successful_download_returns_success_result(self, dialog, mock_model_manager):
        """Successful download should close with a success result."""
        mock_model_manager.download.return_value = None

        result = dialog.run()

        assert result.status == "success"
        assert dialog.success is True
        mock_model_manager.download.assert_called_once_with("small")

    def test_failed_download_returns_failure_after_retry_declined(
        self,
        dialog,
        mock_model_manager,
        mock_tk,
    ):
        """Failed download should return a generic failure message if user declines retry."""
        mock_model_manager.download.side_effect = RuntimeError("network down")
        mock_tk["retry"].return_value = False

        result = dialog.run()

        assert result.status == "failed"
        assert result.message == "Failed to download the small model."
        assert "network down" not in result.message
        assert dialog.success is False
        mock_tk["retry"].assert_called_once()

    def test_retry_runs_a_fresh_worker_attempt(self, dialog, mock_model_manager, mock_tk):
        """Retry should start a new worker attempt and succeed if the second try works."""
        mock_model_manager.download.side_effect = [RuntimeError("temporary"), None]
        mock_tk["retry"].return_value = True

        result = dialog.run()

        assert result.status == "success"
        assert mock_model_manager.download.call_count == 2
        assert mock_tk["Thread"].call_count == 2
        assert mock_tk["Progressbar"].return_value.start.call_count == 2


class TestDownloadDialogWithParent:
    def test_toplevel_used_when_parent_provided(self, mock_tk, mock_model_manager):
        """With a parent, the dialog should use Toplevel and wait_window."""
        from audiby.ui.download_dialog import DownloadDialog

        parent = MagicMock()
        dialog = DownloadDialog("small", parent=parent)

        result = dialog.run()

        assert result.status == "success"
        mock_tk["Toplevel"].assert_called_once_with(parent)
        mock_tk["Tk"].assert_not_called()
        mock_tk["toplevel_window"].grab_set.assert_called_once()
        parent.wait_window.assert_called_once_with(mock_tk["toplevel_window"])
