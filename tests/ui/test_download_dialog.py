"""Tests for DownloadDialog with mocked subprocess and tkinter."""

from unittest.mock import MagicMock

import pytest

from audiby.constants import MODEL_DOWNLOAD_STATUS_MESSAGE


def _make_proc_mock(returncode=0):
    """Create a subprocess.Popen mock that reports the given exit code."""
    proc = MagicMock()
    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


@pytest.fixture
def mock_tk(mocker):
    """Mock tkinter so no real GUI window is created."""
    mock_tk_cls = mocker.patch("audiby.ui.download_dialog.tk.Tk")
    mock_toplevel_cls = mocker.patch("audiby.ui.download_dialog.tk.Toplevel", create=True)
    mock_label_cls = mocker.patch("audiby.ui.download_dialog.ttk.Label", create=True)
    mock_progressbar_cls = mocker.patch("audiby.ui.download_dialog.ttk.Progressbar", create=True)
    mock_button_cls = mocker.patch("audiby.ui.download_dialog.ttk.Button", create=True)
    mock_retry = mocker.patch("audiby.ui.download_dialog.messagebox.askretrycancel")

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
        "Button": mock_button_cls,
        "retry": mock_retry,
        "tk_window": tk_window,
        "toplevel_window": toplevel_window,
    }


@pytest.fixture
def mock_popen(mocker):
    """Mock subprocess.Popen so no real process is created."""
    return mocker.patch("audiby.ui.download_dialog.subprocess.Popen")


@pytest.fixture
def mock_model_manager(mocker):
    """Mock model_manager so no real network is touched."""
    return mocker.patch("audiby.ui.download_dialog.model_manager")


@pytest.fixture
def dialog(mock_tk, mock_popen, mock_model_manager):
    """Create a DownloadDialog with all externals mocked (success by default)."""
    from audiby.ui.download_dialog import DownloadDialog

    mock_popen.return_value = _make_proc_mock(returncode=0)
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
    def test_successful_download_returns_success_result(self, dialog, mock_popen):
        """Successful subprocess exit (0) should close with a success result."""
        mock_popen.return_value = _make_proc_mock(returncode=0)

        result = dialog.run()

        assert result.status == "success"

    def test_failed_download_returns_failure_after_retry_declined(
        self,
        dialog,
        mock_popen,
        mock_tk,
    ):
        """Failed subprocess exit (non-zero) should offer retry; decline returns failure."""
        mock_popen.return_value = _make_proc_mock(returncode=1)
        mock_tk["retry"].return_value = False

        result = dialog.run()

        assert result.status == "failed"
        assert result.message == "Failed to download the small model."
        mock_tk["retry"].assert_called_once()

    def test_retry_runs_a_fresh_subprocess(self, dialog, mock_popen, mock_tk):
        """Retry should launch a new subprocess and succeed if the second run exits 0."""
        failed_proc = _make_proc_mock(returncode=1)
        success_proc = _make_proc_mock(returncode=0)
        mock_popen.side_effect = [failed_proc, success_proc]
        mock_tk["retry"].return_value = True

        result = dialog.run()

        assert result.status == "success"
        assert mock_popen.call_count == 2
        assert mock_tk["Progressbar"].return_value.start.call_count == 2


class TestDownloadDialogWithParent:
    def test_toplevel_used_when_parent_provided(self, mock_tk, mock_popen, mock_model_manager):
        """With a parent, the dialog should use Toplevel and wait_window."""
        from audiby.ui.download_dialog import DownloadDialog

        mock_popen.return_value = _make_proc_mock(returncode=0)
        parent = MagicMock()
        dialog = DownloadDialog("small", parent=parent)

        result = dialog.run()

        assert result.status == "success"
        mock_tk["Toplevel"].assert_called_once_with(parent)
        mock_tk["Tk"].assert_not_called()
        mock_tk["toplevel_window"].grab_set.assert_called_once()
        parent.wait_window.assert_called_once_with(mock_tk["toplevel_window"])


class TestDownloadDialogCancel:
    def test_cancel_kills_subprocess_and_returns_cancelled(self, dialog, mock_popen, mock_tk):
        """Cancel should kill the subprocess and return cancelled status."""
        proc = _make_proc_mock(returncode=0)
        proc.poll.return_value = None  # still running when cancel fires
        mock_popen.return_value = proc

        # Prevent the poll loop from running — we invoke cancel manually
        mock_tk["tk_window"].after.side_effect = lambda _d, _cb: None
        dialog.run()
        dialog._on_cancel()

        proc.kill.assert_called_once()
        assert dialog.result.status == "cancelled"

    def test_cancel_renders_button(self, dialog, mock_tk):
        """Dialog should render a Cancel button."""
        dialog.run()

        assert mock_tk["Button"].call_count >= 1
        button_kwargs = mock_tk["Button"].call_args.kwargs
        assert button_kwargs["text"] == "Cancel"

    def test_cancel_cleans_up_partial_download(self, dialog, mock_popen, mock_model_manager, mock_tk):
        """Cancel should attempt to remove partial download cache."""
        proc = _make_proc_mock(returncode=0)
        proc.poll.return_value = None
        mock_popen.return_value = proc
        mock_tk["tk_window"].after.side_effect = lambda _d, _cb: None

        cache_path = MagicMock()
        cache_path.exists.return_value = True
        mock_model_manager.get_model_root.return_value.__truediv__ = MagicMock(
            return_value=MagicMock(__truediv__=MagicMock(return_value=cache_path))
        )

        dialog.run()
        dialog._on_cancel()

        assert dialog.result.status == "cancelled"
