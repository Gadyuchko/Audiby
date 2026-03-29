import logging
import threading
import tkinter as tk
from tkinter import ttk

from audiby.config import Config
from collections.abc import Callable
from audiby.constants import CONFIG_KEY_HOTKEY, CONFIG_KEY_AUTOSTART, DEFAULT_AUTOSTART, SUPPORTED_MODELS, \
    CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE
from audiby.core import model_manager
from audiby.ui.download_dialog import DownloadDialog
from pynput.keyboard import HotKey, Key, Listener as KeyboardListener

logger = logging.getLogger(__name__)

class SettingsWindow:
    """
    Represents a settings window interface for user interaction with application settings.

    This class provides methods to display and manage a settings window for an application.
    It ensures that the window is initialized and displayed appropriately and offers cleanup
    operations when the window is no longer needed. Always creates a new instance of the window.
    """

    _MODIFIER_KEYS = {Key.ctrl, Key.ctrl_l, Key.ctrl_r,
                       Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
                       Key.shift, Key.shift_l, Key.shift_r,
                       Key.cmd, Key.cmd_l, Key.cmd_r}
    _CMD_WIN_KEYS = {Key.cmd, Key.cmd_l, Key.cmd_r}

    def __init__(self, config: Config, on_save: Callable[[], str | None]):
        self._config = config
        self._on_save = on_save
        self._hotkey_label = None
        self._hotkey_value = None
        self._bind_hotkey = None

        self._autostart_label = None
        self._autostart_checkbox = None
        self._autostart_value = None

        self._model_label = None
        self._model_value = None
        self._model_dropdown = None

        self._capturing = False
        self._pressed_modifiers = set()
        self._key_listener = None
        self._save_button = None
        self._error_label = None
        self._pre_capture_value = None
        self._window = None
        self._gui_thread = None

    def show(self):
        # pystray menu callbacks run on a background thread, but tkinter requires
        # its own thread with mainloop() to process GUI events. We spawn a dedicated
        # GUI thread for each window lifecycle. If the window is already open,
        # we use after() to safely schedule lift() on the tkinter thread.
        if self._gui_thread is not None and self._gui_thread.is_alive():
            if self._window is not None:
                self._window.after(0, self._window.lift)
            return
        self._gui_thread = threading.Thread(target=self._build_and_run, daemon=True)
        self._gui_thread.start()

    def _build_and_run(self):
        """
        Constructs and runs the settings window for the application, providing the user with
        options to configure the hotkey and save settings.

        This method creates a graphical user interface (GUI) window using the Tkinter library.
        The window allows the user to view and modify a configurable hotkey setting. If a new
        hotkey is invalid, an error label will be displayed. The GUI window is positioned
        near the bottom-right corner of the screen for convenient access.

        Process runs on dedicated GUI thread precreated in show().
        :raises Exception: If any unexpected issues occur during the execution of this method

        :return: None
        """
        logger.debug("Building settings window")
        self._window = tk.Tk()
        self._window.title("Settings")
        self._window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._hotkey_label = tk.Label(self._window, text="Hotkey:")
        self._hotkey_label.grid(row=0, column=0, padx=5, pady=5)

        # read values from config and store in class variable
        self._bind_hotkey = tk.StringVar()
        self._bind_hotkey.set(self._config.get(CONFIG_KEY_HOTKEY, "ctrl+space"))

        self._autostart_value = tk.BooleanVar()
        self._autostart_value.set(self._config.get(CONFIG_KEY_AUTOSTART, DEFAULT_AUTOSTART))

        self._model_value = tk.StringVar()
        self._model_value.set(self._config.get(CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE))

        # hotkey display — click to start capturing a new combo
        self._hotkey_value = tk.Entry(self._window, textvariable=self._bind_hotkey, state="readonly")
        self._hotkey_value.grid(row=0, column=1, padx=5, pady=5)
        self._hotkey_value.bind('<Button-1>', self._start_capture)

        # error label for invalid hotkey
        self._error_label = tk.Label(self._window, text="", fg="red")

        # autostart checkbox
        self._autostart_label = tk.Label(self._window, text="Autostart:")
        self._autostart_label.grid(row=1, column=0, padx=5, pady=5)
        self._autostart_checkbox = tk.Checkbutton(self._window, variable=self._autostart_value)
        self._autostart_checkbox.grid(row=1, column=1, padx=5, pady=5)

        # model dropdown
        self._model_label = tk.Label(self._window, text="Model:")
        self._model_label.grid(row=2, column=0, padx=5, pady=5)
        self._model_dropdown = ttk.Combobox(
            self._window,
            textvariable=self._model_value,
            values=SUPPORTED_MODELS,
            state="readonly"
        )
        self._model_dropdown.grid(row=2, column=1, padx=5, pady=5)
        self._model_dropdown.bind('<<ComboboxSelected>>', self._on_model_selected)

        # save button
        self._save_button = tk.Button(self._window, text="Save", command=self._on_save_clicked)
        self._save_button.grid(row=4, column=0, columnspan=2, pady=10)

        # position window near bottom-right (near system tray)
        self._window.update_idletasks()
        width = self._window.winfo_width()
        height = self._window.winfo_height()
        x = self._window.winfo_screenwidth() - width - 50
        y = self._window.winfo_screenheight() - height - 80
        self._window.geometry(f"+{x}+{y}")

        self._hotkey_value.focus_set()
        self._window.mainloop()

    def _on_close(self):
        """Handle window close — stop capture listener, quit mainloop, destroy."""
        logger.debug("Settings window closed by user")
        self._stop_capture()
        if self._window is not None:
            # Clear tkinter variables before destroying to avoid cross-thread cleanup errors
            self._bind_hotkey = None
            self._hotkey_value = None
            self._hotkey_label = None
            self._error_label = None
            self._save_button = None
            self._autostart_label = None
            self._autostart_checkbox = None
            self._autostart_value = None
            self._model_label = None
            self._model_value = None
            self._model_dropdown = None
            # quit() exits mainloop(), destroy() releases the window.
            # Both are needed in this order — calling destroy() alone leaves
            # mainloop() running and the GUI thread hangs indefinitely.
            self._window.quit()
            self._window.destroy()
            self._window = None

    def destroy(self):
        self._stop_capture()
        if self._window is not None:
            try:
                self._window.quit()
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def _start_capture(self, _event=None):
        """Activate capture mode — start a pynput listener for global key capture.

        We use pynput instead of tkinter's bind('<Key>') because:
        1. Windows intercepts Alt+key for menu bar activation — tkinter never sees Alt combos.
        2. Tkinter modifier bitmask values differ per OS (e.g. Alt is 0x8 on Linux, 0x20000 on Windows).
        pynput captures at the OS level, consistent across platforms — same library the hotkey manager uses.
        """
        logger.debug("Hotkey capture mode started")
        self._capturing = True
        self._pre_capture_value = self._bind_hotkey.get()
        self._pressed_modifiers = set()
        self._hotkey_value.config(state="normal")
        self._bind_hotkey.set("Press a key combination...")
        self._hotkey_value.config(state="readonly", readonlybackground="#FFFFCC")
        self._save_button.config(state="disabled")
        self._key_listener = KeyboardListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._key_listener.start()

    def _stop_capture(self):
        """Deactivate capture mode — stop the pynput listener and reset field style."""
        self._capturing = False
        if self._hotkey_value is not None:
            self._hotkey_value.config(readonlybackground="SystemButtonFace")
        if self._save_button is not None:
            self._save_button.config(state="normal")
        if self._key_listener is not None:
            self._key_listener.stop()
            self._key_listener = None

    def _on_key_press(self, key):
        """
        Handles key press events, processing both modifier keys and non-modifier keys to construct a
        key combination string. The constructed key combination string is then passed to a callback
        function for further handling.

        This method is designed to function only when capturing mode is active.

        :param key: The key press event to process. It is expected to be an object with attributes
            such as ``char`` or ``name`` for name resolution.
        :type key: Any
        """
        if not self._capturing:
            return
        if key in self._MODIFIER_KEYS:
            self._pressed_modifiers.add(key)
            return

        # Reject OS-reserved modifiers (Cmd/Win) — OS intercepts these globally
        if any(k in self._pressed_modifiers for k in self._CMD_WIN_KEYS):
            if self._window is not None:
                self._window.after(0, self._on_reserved_modifier_rejected)
            return

        # Non-modifier key pressed — build the combo string
        parts = []
        if any(k in self._pressed_modifiers for k in (Key.ctrl, Key.ctrl_l, Key.ctrl_r)):
            parts.append("ctrl")
        if any(k in self._pressed_modifiers for k in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr)):
            parts.append("alt")
        if any(k in self._pressed_modifiers for k in (Key.shift, Key.shift_l, Key.shift_r)):
            parts.append("shift")

        # Get the key name
        if hasattr(key, 'char') and key.char is not None:
            parts.append(key.char.lower())
        elif hasattr(key, 'name'):
            parts.append(key.name.lower())
        else:
            parts.append(str(key).lower())

        key_combo = "+".join(parts)

        # Schedule the UI update on the tkinter thread
        if self._window is not None:
            # use after() to safely schedule lift() on the tkinter thread.
            self._window.after(0, lambda: self._on_hotkey_captured(key_combo))

    def _on_key_release(self, key):
        """pynput on_release callback — remove modifier from tracked set."""
        self._pressed_modifiers.discard(key)

    @staticmethod
    def _to_pynput_format(combo: str) -> str:
        """Convert 'ctrl+alt+z' to '<ctrl>+<alt>+z' for pynput validation."""
        parts = []
        for part in combo.split("+"):
            token = part.strip().lower()
            parts.append(f"<{token}>" if len(token) > 1 else token)
        return "+".join(parts)

    def _on_hotkey_captured(self, key_combo: str):
        """
        Handles the process of capturing and validating a hotkey combination
        entered by the user. Parses the hotkey, updates the relevant UI
        components, and manages state transitions for capturing input.

        :param key_combo: The hotkey combination entered by the user.
        :type key_combo: str
        :return: None
        """
        try:
            HotKey.parse(self._to_pynput_format(key_combo))
            logger.debug("Valid hotkey captured: %s", key_combo)
            self._error_label.grid_remove()
            self._hotkey_value.config(state="normal")
            self._bind_hotkey.set(key_combo)
            self._hotkey_value.config(state="readonly")
            self._stop_capture()
        except ValueError:
            logger.debug("Invalid hotkey rejected: %s", key_combo)
            self._show_error("Invalid key combination. Select another combination.")
            if self._pre_capture_value is not None:
                self._hotkey_value.config(state="normal")
                self._bind_hotkey.set(self._pre_capture_value)
                self._hotkey_value.config(state="readonly")
            self._stop_capture()

    def _show_error(self, message: str):
        """Set error label text and make it visible."""
        if self._error_label is None:
            return
        self._error_label.config(text=message)
        self._error_label.grid(row=3, column=0, columnspan=2)

    def _on_reserved_modifier_rejected(self):
        """Reject combo using OS-reserved modifier — show error and restore display."""
        self._show_error("OS-reserved modifier (Cmd/Win) cannot be used. Select another combination.")
        if self._hotkey_value is not None and self._pre_capture_value is not None:
            self._hotkey_value.config(state="normal")
            self._bind_hotkey.set(self._pre_capture_value)
            self._hotkey_value.config(state="readonly")
        self._stop_capture()

    def _on_model_selected(self, _event=None):
        """Handle model combobox selection — download if model not available locally."""
        selected = self._model_value.get()
        if model_manager.exists(selected):
            return

        dialog = DownloadDialog(selected, parent=self._window)
        dialog.run()

        if not dialog.success:
            self._show_error(f"Failed to download {selected} model.")
            # revert selection to the previously configured model
            previous = self._config.get(CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE)
            self._model_value.set(previous)

    def _on_save_clicked(self) -> str | None:
        new_hotkey = self._bind_hotkey.get()
        autostart = self._autostart_value.get()
        model = self._model_value.get()
        logger.info("Saving new configuration: hotkey -> %s | autostart -> %s | model -> %s", new_hotkey, autostart, model)
        error = self._on_save(new_hotkey, autostart, model)
        if error:
            self._show_error(error)
            return
        self._on_close()