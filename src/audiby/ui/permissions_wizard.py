"""First-run macOS permissions wizard.

Shown before the orchestrator boots whenever one of the macOS permissions
Audiby needs (Microphone, Input Monitoring, Accessibility) is missing. Apple
does not let an app grant these to itself, so the wizard does the three things
software *can* do: fire the system prompt that pre-registers the app in the
right list, open System Settings on the right pane, and show live status so
the user can see each toggle take effect.

All platform calls are injected so the window can be driven in tests with a
mocked tkinter and without touching real OS state.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from tkinter import ttk

from audiby.constants import APP_NAME
from audiby.platform.macos_permissions import (
    MAC_PERMISSIONS,
    MacPermission,
    can_relaunch_app,
    is_dev_host,
    is_mac_permission_granted,
    open_mac_privacy_pane,
    relaunch_app,
    request_mac_permission,
    resolve_host_hint,
)

logger = logging.getLogger(__name__)

STATUS_GRANTED = "Granted"
STATUS_MISSING = "Not granted"

WIZARD_TITLE = f"{APP_NAME} needs a few macOS permissions"
WIZARD_INTRO = (
    "macOS only lets you grant these yourself. For each one, click Allow to get "
    "the system prompt, then turn on the switch. The status below updates on its own."
)
WIZARD_DEV_HOST_NOTE = (
    "You are running from source, so macOS will list {host} instead of Audiby. "
    "Allow that app."
)
WIZARD_RELAUNCH_NOTE = (
    "macOS applies Input Monitoring and Accessibility to a freshly started app. "
    "After turning them on, click Relaunch so Audiby starts again with the new "
    "permissions. The status here may stay red until then."
)
WIZARD_DEV_RELAUNCH_NOTE = (
    "Running from source: after turning the switches on, fully quit and reopen "
    "{host}, then start Audiby again."
)
WIZARD_ALL_GRANTED = "All permissions granted. You are ready to go."
WIZARD_SOME_MISSING = "Audiby can start, but features tied to missing permissions will not work."


@dataclass(frozen=True)
class PermissionsWizardResult:
    """Outcome of one wizard session."""

    status: str  # "continue" or "quit"
    missing: list[str] = field(default_factory=list)


class PermissionsWizard:
    """Modal window that walks the user through granting macOS permissions."""

    _POLL_INTERVAL_MS = 1500

    def __init__(
        self,
        missing: list[str] | None = None,
        *,
        permissions: tuple[MacPermission, ...] = MAC_PERMISSIONS,
        is_granted: Callable[[str], bool] = is_mac_permission_granted,
        request: Callable[[str], bool] = request_mac_permission,
        open_pane: Callable[[str], None] = open_mac_privacy_pane,
        host_hint: Callable[[], str] = resolve_host_hint,
        dev_host: Callable[[], bool] = is_dev_host,
        can_relaunch: Callable[[], bool] = can_relaunch_app,
        relaunch: Callable[[], bool] = relaunch_app,
        parent: tk.Misc | None = None,
    ) -> None:
        self._permissions = permissions
        self._is_granted = is_granted
        self._request = request
        self._open_pane = open_pane
        self._host_hint = host_hint
        self._dev_host = dev_host
        self._can_relaunch = can_relaunch
        self._relaunch = relaunch
        self._parent = parent
        self._dialog: tk.Tk | tk.Toplevel | None = None
        self._status_labels: dict[str, ttk.Label] = {}
        self._allow_buttons: dict[str, ttk.Button] = {}
        self._summary_label: ttk.Label | None = None
        self._continue_button: ttk.Button | None = None
        self._poll_active = False
        self.result = PermissionsWizardResult(status="quit", missing=list(missing or []))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> PermissionsWizardResult:
        """Build the window and block until the user continues or quits."""
        if self._parent is not None:
            self._dialog = tk.Toplevel(self._parent)
        else:
            self._dialog = tk.Tk()
        dialog = self._dialog

        dialog.title(f"{APP_NAME} Permissions")
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", self._on_quit)

        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=WIZARD_TITLE, font=("", 14, "bold")).pack(anchor="w")
        ttk.Label(body, text=WIZARD_INTRO, wraplength=440, justify="left").pack(
            anchor="w", pady=(6, 0)
        )
        if self._dev_host():
            ttk.Label(
                body,
                text=WIZARD_DEV_HOST_NOTE.format(host=self._host_hint()),
                wraplength=440,
                justify="left",
            ).pack(anchor="w", pady=(6, 0))

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=12)

        for permission in self._permissions:
            self._build_row(body, permission)

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=12)
        relaunch_available = self._can_relaunch()
        if relaunch_available:
            relaunch_note = WIZARD_RELAUNCH_NOTE
        else:
            relaunch_note = WIZARD_DEV_RELAUNCH_NOTE.format(host=self._host_hint())
        ttk.Label(body, text=relaunch_note, wraplength=440, justify="left").pack(anchor="w")

        self._summary_label = ttk.Label(body, text="", wraplength=440, justify="left")
        self._summary_label.pack(anchor="w", pady=(10, 0))

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(14, 0))
        ttk.Button(footer, text="Quit", command=self._on_quit).pack(side="left")
        self._continue_button = ttk.Button(footer, text="Continue", command=self._on_continue)
        self._continue_button.pack(side="right")
        if relaunch_available:
            ttk.Button(footer, text="Relaunch", command=self._on_relaunch).pack(
                side="right", padx=(0, 8)
            )

        self._refresh_statuses()
        self._poll_active = True
        self._schedule_poll()

        dialog.update_idletasks()
        self._center(dialog)
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(200, lambda: dialog.attributes("-topmost", False))

        if self._parent is not None:
            dialog.grab_set()
            self._parent.wait_window(dialog)
        else:
            dialog.mainloop()
        return self.result

    def _build_row(self, body: ttk.Frame, permission: MacPermission) -> None:
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(0, 10))

        text = ttk.Frame(row)
        text.pack(side="left", fill="x", expand=True)
        ttk.Label(text, text=permission.name, font=("", 12, "bold")).pack(anchor="w")
        ttk.Label(text, text=permission.purpose, wraplength=260, justify="left").pack(anchor="w")
        status = ttk.Label(text, text="")
        status.pack(anchor="w", pady=(2, 0))
        self._status_labels[permission.key] = status

        actions = ttk.Frame(row)
        actions.pack(side="right")
        allow = ttk.Button(
            actions,
            text="Allow…",
            command=lambda key=permission.key: self._on_allow(key),
        )
        allow.pack(fill="x")
        self._allow_buttons[permission.key] = allow
        ttk.Button(
            actions,
            text="Open Settings",
            command=lambda key=permission.key: self._on_open_settings(key),
        ).pack(fill="x", pady=(4, 0))

    @staticmethod
    def _center(dialog: tk.Misc) -> None:
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() - width) // 2
        y = (dialog.winfo_screenheight() - height) // 3
        dialog.geometry(f"+{x}+{y}")

    def _close(self) -> None:
        self._poll_active = False
        if self._dialog is None:
            return
        if self._parent is None:
            self._dialog.quit()
        self._dialog.destroy()
        self._dialog = None

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------

    def _schedule_poll(self) -> None:
        if self._dialog is not None and self._poll_active:
            self._dialog.after(self._POLL_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        if not self._poll_active:
            return
        self._refresh_statuses()
        self._schedule_poll()

    def missing_permissions(self) -> list[str]:
        """Return keys of permissions still not granted, in display order."""
        return [p.key for p in self._permissions if not self._is_granted(p.key)]

    def _refresh_statuses(self) -> None:
        missing = self.missing_permissions()
        for permission in self._permissions:
            is_missing = permission.key in missing
            label = self._status_labels.get(permission.key)
            if label is not None:
                label.configure(
                    text=STATUS_MISSING if is_missing else STATUS_GRANTED,
                    foreground="#b00020" if is_missing else "#1b7f3b",
                )
            button = self._allow_buttons.get(permission.key)
            if button is not None:
                button.state(["!disabled"] if is_missing else ["disabled"])
        if self._summary_label is not None:
            self._summary_label.configure(
                text=WIZARD_SOME_MISSING if missing else WIZARD_ALL_GRANTED
            )
        if self._continue_button is not None:
            self._continue_button.configure(text="Continue anyway" if missing else "Continue")

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_allow(self, key: str) -> None:
        logger.info("Permissions wizard: requesting %s", key)
        try:
            granted = self._request(key)
        except Exception:
            logger.exception("Permission request failed for %s", key)
            granted = False
        logger.info("Permissions wizard: %s granted=%s", key, granted)
        self._refresh_statuses()

    def _on_open_settings(self, key: str) -> None:
        logger.info("Permissions wizard: opening settings pane for %s", key)
        try:
            self._open_pane(key)
        except Exception:
            logger.exception("Failed to open settings pane for %s", key)

    def _on_continue(self) -> None:
        missing = self.missing_permissions()
        self.result = PermissionsWizardResult(status="continue", missing=missing)
        self._close()

    def _on_quit(self) -> None:
        self.result = PermissionsWizardResult(status="quit", missing=self.missing_permissions())
        self._close()

    def _on_relaunch(self) -> None:
        """Schedule a fresh app instance and close so this one can exit."""
        logger.info("Permissions wizard: relaunch requested")
        try:
            scheduled = self._relaunch()
        except Exception:
            logger.exception("Relaunch failed")
            scheduled = False
        if not scheduled:
            self._refresh_statuses()
            return
        self.result = PermissionsWizardResult(status="relaunch", missing=self.missing_permissions())
        self._close()
