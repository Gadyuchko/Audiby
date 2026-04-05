"""Download dialog for model download progress UI."""

import logging
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from audiby.constants import (
    LOG_DIRNAME,
    LOG_FILENAME,
    LOG_FORMAT,
    MODEL_DISPLAY_SIZES,
    MODEL_DOWNLOAD_STATUS_MESSAGE,
)
from audiby.config import get_appdata_path
from audiby.core import model_manager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadDialogResult:
    """Structured result for interactive model download attempts."""

    status: str
    message: str | None = None


class DownloadDialog:
    """Modal download dialog reused by settings and startup fallback."""

    _POLL_INTERVAL_MS = 200

    def __init__(self, model_name: str, parent: tk.Misc | None = None):
        self._model_name = model_name
        self._parent = parent
        self._dialog: tk.Tk | tk.Toplevel | None = None
        self._progress_bar = None
        self._status_label = None
        self._cancel_button = None
        self._proc: subprocess.Popen | None = None
        self._active_attempt = 0
        self._is_running = False
        self.result = DownloadDialogResult(status="cancelled")

    def run(self) -> DownloadDialogResult:
        """Show download dialog and block until download completes or fails."""
        if self._parent is not None:
            self._dialog = tk.Toplevel(self._parent)
        else:
            self._dialog = tk.Tk()

        self._dialog.title("Downloading Model")
        self._dialog.protocol("WM_DELETE_WINDOW", self._on_cancel)
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
        self._status_label.pack(pady=(0, 8), padx=12)
        self._cancel_button = ttk.Button(
            self._dialog,
            text="Cancel",
            command=self._on_cancel,
        )
        self._cancel_button.pack(pady=(0, 12), padx=12)

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

        # Capture reference before _close_dialog can null self._dialog.
        dialog = self._dialog
        self._start_download_attempt()

        if self._parent is not None:
            dialog.grab_set()
            self._parent.wait_window(dialog)
        else:
            dialog.mainloop()
        return self.result

    def _close_dialog(self) -> None:
        """Stop progress animation and destroy the dialog on the tkinter thread."""
        if self._progress_bar is not None:
            self._progress_bar.stop()
        if self._dialog is not None:
            if self._parent is None:
                self._dialog.quit()
            self._dialog.destroy()
            self._dialog = None

    def _start_download_attempt(self) -> None:
        """Launch a download in a child process that can be killed on cancel."""
        self._active_attempt += 1
        self._is_running = True
        if self._status_label is not None:
            self._status_label.configure(text=MODEL_DOWNLOAD_STATUS_MESSAGE)
        if self._progress_bar is not None:
            self._progress_bar.configure(mode="indeterminate")
            self._progress_bar.start()
        log_file = str(get_appdata_path() / LOG_DIRNAME / LOG_FILENAME)
        self._proc = subprocess.Popen(
            [
                sys.executable, "-c",
                "import logging, sys;"
                "fmt=logging.Formatter(sys.argv[2]);"
                "fh=logging.FileHandler(sys.argv[3],encoding='utf-8');"
                "fh.setFormatter(fmt);"
                "sh=logging.StreamHandler();"
                "sh.setFormatter(fmt);"
                "logging.basicConfig(level=logging.DEBUG,handlers=[fh,sh]);"
                "from audiby.core.model_manager import download;"
                "download(sys.argv[1])",
                self._model_name,
                LOG_FORMAT,
                log_file,
            ],
        )
        self._poll_download(self._active_attempt)

    def _poll_download(self, attempt_id: int) -> None:
        """Check subprocess status; reschedule or handle completion."""
        if attempt_id != self._active_attempt or not self._is_running:
            return
        if self._proc is None:
            return
        returncode = self._proc.poll()
        if returncode is None:
            dialog = self._dialog
            if dialog is not None:
                dialog.after(
                    self._POLL_INTERVAL_MS,
                    lambda: self._poll_download(attempt_id),
                )
            return
        if returncode == 0:
            self._handle_download_success(attempt_id)
        else:
            self._handle_download_failure(attempt_id)

    def _on_cancel(self) -> None:
        """Kill the download subprocess and close the dialog."""
        self._is_running = False
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                logger.warning("Failed to kill download process", exc_info=True)
            self._proc = None
        self._cleanup_partial_download()
        self.result = DownloadDialogResult(status="cancelled")
        self._close_dialog()

    def _handle_download_success(self, attempt_id: int) -> None:
        """Finish a successful download attempt on the tkinter thread."""
        if attempt_id != self._active_attempt or not self._is_running:
            return
        self._is_running = False
        self.result = DownloadDialogResult(status="success")
        self._close_dialog()

    def _handle_download_failure(self, attempt_id: int) -> None:
        """Handle a failed attempt and optionally start a retry."""
        if attempt_id != self._active_attempt or not self._is_running:
            return
        self._is_running = False
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

    _CLEANUP_RETRIES = 5
    _CLEANUP_RETRY_DELAY = 1.0

    def _cleanup_partial_download(self) -> None:
        """Schedule cache cleanup on a background thread so retries don't freeze the UI."""
        threading.Thread(
            target=self._do_cleanup,
            args=(self._model_name,),
            daemon=True,
        ).start()

    @classmethod
    def _do_cleanup(cls, model_name: str) -> None:
        """Remove HuggingFace download cache, retrying while Windows releases handles."""
        cache_dir = model_manager.get_model_root() / model_name / ".cache"
        for attempt in range(cls._CLEANUP_RETRIES):
            if not cache_dir.exists():
                return
            try:
                shutil.rmtree(cache_dir)
                logger.info("Cleaned up partial download cache for %s", model_name)
                return
            except Exception:
                if attempt < cls._CLEANUP_RETRIES - 1:
                    time.sleep(cls._CLEANUP_RETRY_DELAY)
                else:
                    logger.warning(
                        "Failed to clean up partial download for %s after %d attempts",
                        model_name,
                        cls._CLEANUP_RETRIES,
                        exc_info=True,
                    )
