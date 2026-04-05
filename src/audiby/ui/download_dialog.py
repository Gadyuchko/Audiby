"""Download dialog for model download progress UI."""

import logging
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from audiby.constants import MODEL_DISPLAY_SIZES, MODEL_DOWNLOAD_STATUS_MESSAGE
from audiby.core import model_manager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadDialogResult:
    """Structured result for interactive model download attempts."""

    status: str
    message: str | None = None


class DownloadDialog:
    """Modal download dialog reused by settings and startup fallback."""

    def __init__(self, model_name: str, parent: tk.Misc | None = None):
        self._model_name = model_name
        self._parent = parent
        self._dialog: tk.Misc | None = None
        self._progress_bar = None
        self._status_label = None
        self._worker = None
        self._active_attempt = 0
        self._is_running = False
        self.success = False
        self.result = DownloadDialogResult(status="cancelled")

    def run(self) -> DownloadDialogResult:
        """Show download dialog and block until download completes or fails."""
        if self._parent is not None:
            self._dialog = tk.Toplevel(self._parent)
        else:
            self._dialog = tk.Tk()

        self._dialog.title("Downloading Model")
        self._dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        ttk.Label(
            self._dialog,
            text=f"Downloading Whisper model: {self._model_name}",
        ).pack(pady=(12, 4), padx=12)
        ttk.Label(
            self._dialog,
            text=f"Download size: {MODEL_DISPLAY_SIZES.get(self._model_name, 'Unknown size')}",
        ).pack(pady=4, padx=12)
        self._progress_bar = ttk.Progressbar(
            self._dialog,
            orient="horizontal",
            length=200,
            mode="indeterminate",
        )
        self._progress_bar.pack(pady=8, padx=12)
        self._status_label = ttk.Label(
            self._dialog,
            text=MODEL_DOWNLOAD_STATUS_MESSAGE,
            wraplength=280,
            justify="left",
        )
        self._status_label.pack(pady=(0, 12), padx=12)

        self._dialog.update_idletasks()
        if self._parent is not None:
            parent_x = self._parent.winfo_x()
            parent_y = self._parent.winfo_y()
            dialog_height = self._dialog.winfo_height()
            self._dialog.geometry(f"+{parent_x}+{parent_y - dialog_height - 50}")
        else:
            width = self._dialog.winfo_width()
            x = self._dialog.winfo_screenwidth() - width - 50
            y = self._dialog.winfo_screenheight() - 200
            self._dialog.geometry(f"+{x}+{y}")

        self._start_download_attempt()

        if self._parent is not None:
            self._dialog.grab_set()
            self._parent.wait_window(self._dialog)
        else:
            self._dialog.mainloop()
        return self.result

    def _close_dialog(self) -> None:
        """Stop progress animation and destroy the dialog on the tkinter thread."""
        if self._progress_bar is not None:
            self._progress_bar.stop()
        if self._dialog is not None:
            self._dialog.destroy()

    def _start_download_attempt(self) -> None:
        """Launch a fresh background download attempt."""
        self._active_attempt += 1
        self._is_running = True
        if self._status_label is not None:
            self._status_label.configure(text=MODEL_DOWNLOAD_STATUS_MESSAGE)
        if self._progress_bar is not None:
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start()
        self._worker = threading.Thread(
            target=self._download_worker,
            args=(self._active_attempt,),
            daemon=True,
        )
        self._worker.start()

    def _download_worker(self, attempt_id: int) -> None:
        try:
            model_manager.download(self._model_name)
        except Exception:
            logger.exception("Failed to download model %s", self._model_name)
            if self._dialog is not None:
                self._dialog.after(0, lambda: self._handle_download_failure(attempt_id))
            return

        if self._dialog is not None:
            self._dialog.after(0, lambda: self._handle_download_success(attempt_id))

    def _handle_download_success(self, attempt_id: int) -> None:
        """Finish a successful download attempt on the tkinter thread."""
        if attempt_id != self._active_attempt or not self._is_running:
            return
        self._is_running = False
        self.success = True
        self.result = DownloadDialogResult(status="success")
        self._close_dialog()

    def _handle_download_failure(self, attempt_id: int) -> None:
        """Handle a failed attempt and optionally start a retry."""
        if attempt_id != self._active_attempt or not self._is_running:
            return
        self._is_running = False
        self.success = False
        failure_message = f"Failed to download the {self._model_name} model."
        if self._progress_bar is not None:
            self._progress_bar.stop()
        if self._status_label is not None:
            self._status_label.configure(text=failure_message)

        retry = messagebox.askretrycancel(
            "Model Download Failed",
            f"{failure_message}\n\nRetry the download?",
            parent=self._dialog,
        )
        if retry:
            self._start_download_attempt()
            return

        self.result = DownloadDialogResult(status="failed", message=failure_message)
        self._close_dialog()
