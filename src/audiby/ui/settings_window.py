import tkinter as tk
class SettingsWindow:
    """
    Represents a settings window interface for user interaction with application settings.

    This class provides methods to display and manage a settings window for an application.
    It ensures that the window is initialized and displayed appropriately and offers cleanup
    operations when the window is no longer needed. Always creates a new instance of the window.
    """
    def __init__(self):
        # we create a new window every time
        self._window = None

    def show(self):
        if self._window is None or not self._window.winfo_exists():
            self._window = tk.Tk()
            self._window.title("Settings")
        # bring the window to the front
        self._window.lift()

    def destroy(self):
        if self._window is not None:
            self._window.destroy()
