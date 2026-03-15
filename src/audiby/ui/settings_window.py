"""Settings window placeholder for configuration UI."""
import tkinter as tk
class SettingsWindow:
    """Settings window placeholder."""
    def __init__(self):
        self._window = None

    def show(self):
        if self._window is None or not self._window.winfo_exists():
            self._window = tk.Tk()
            self._window.title("Settings")

        self._window.lift()

    def destroy(self):
        if self._window is not None:
            self._window.destroy()
