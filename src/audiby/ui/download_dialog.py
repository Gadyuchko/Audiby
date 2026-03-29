"""Download dialog for model download progress UI."""
import threading
import tkinter as tk
import logging
from tkinter import ttk

from audiby.core import model_manager

logger = logging.getLogger(__name__)

class DownloadDialog:
    """
    Handles the creation and management of a download dialog widget.

    This class is responsible for displaying a dialog during a model download process.
    It creates a graphical interface to inform the user about the ongoing download and
    blocks execution until the process has either completed or failed. The success status
    of the download is available as an attribute of the instance after the dialog closes.

    :ivar success: Indicates whether the model download was successful.
    :type success: bool
    """
    def __init__(self, model_name: str, parent: tk.Tk | None = None):
        self._model_name = model_name
        self._parent = parent
        self._dialog = None
        self._progress_bar = None
        self.success = False

    def run(self):
        """Show download dialog and block until download completes or fails."""
        if self._parent is not None:
            self._dialog = tk.Toplevel(self._parent)
        else:
            self._dialog = tk.Tk()

        self._dialog.title("Downloading Model")
        self._dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        ttk.Label(self._dialog, text=f"Downloading {self._model_name}...").pack(pady=10)
        self._progress_bar = ttk.Progressbar(self._dialog, orient="horizontal", length=200, mode="indeterminate")
        self._progress_bar.pack(pady=10)
        self._progress_bar.start()

        # position above the parent window if available, otherwise bottom-right
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

        # download on worker thread
        worker = threading.Thread(target=self._download_worker, daemon=True)
        worker.start()

        if self._parent is not None:
            # Toplevel — use wait_window to block until dialog is destroyed
            self._dialog.grab_set()
            self._parent.wait_window(self._dialog)
        else:
            # standalone — use mainloop
            self._dialog.mainloop()

    def _close_dialog(self):
        """Stop progress bar animation and destroy dialog — must run on tkinter thread."""
        # Stop the progress bar before destroying — its internal after() timer
        # would fire on a destroyed widget and raise a TclError otherwise.
        self._progress_bar.stop()
        self._dialog.destroy()

    def _download_worker(self):
        try:
            model_manager.download(self._model_name)
            self.success = True
        except Exception as e:
            logger.error("Failed to download model: %s", e)
            self.success = False
        # close dialog from tkinter thread
        self._dialog.after(0, self._close_dialog)
