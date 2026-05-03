"""macOS permission preflight for global input capture and synthetic key events.

This module does not grant any permissions.

Instead, it asks macOS whether the *current process* is already allowed to use
two protected capabilities that Audiby needs on macOS:

- Accessibility: required for synthetic key events used during text injection
- Input Monitoring: required for global hotkey listening

Why `ctypes` is used here:
- Python itself does not expose these permission-check APIs directly
- macOS provides them inside Apple's ``ApplicationServices`` framework
- ``ctypes.CDLL(...)`` loads that native framework so Python can call its C APIs

How "trusted" is derived:
- We call Apple's APIs, not our own heuristics
- ``AXIsProcessTrusted()`` returns whether macOS trusts the current process for
  Accessibility access
- ``CGPreflightListenEventAccess()`` returns whether macOS currently allows the
  current process to listen for global input events

The framework is already part of the operating system. Loading it here simply
gives this Python process access to those *check functions* so startup can fail
early with a clear message when permissions are missing.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from audiby.exceptions import HotkeyPermissionError

logger = logging.getLogger(__name__)

_APP_SERVICES_PATH = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"


def ensure_mac_input_permissions() -> None:
    """Fail fast when macOS has not granted the current process required permissions.

    This is a startup preflight only. It does not request, enable, or modify
    any OS permissions. It asks macOS whether the current process is already
    authorized and raises a ``HotkeyPermissionError`` with an actionable message if not.
    """
    if sys.platform != "darwin":
        return

    missing = get_missing_mac_input_permissions()
    if not missing:
        return

    host = _resolve_host_hint()
    missing_text = ", ".join(missing)
    raise HotkeyPermissionError(
        "macOS permissions missing: "
        f"{missing_text}. Enable them for {host} in System Settings > Privacy & Security, "
        "then fully restart that host app."
    )


def get_missing_mac_input_permissions() -> list[str]:
    """Return missing macOS permissions for the current process.

    The return value is derived from Apple's permission APIs inside the
    ``ApplicationServices`` framework:

    - ``AXIsProcessTrusted()`` for Accessibility
    - ``CGPreflightListenEventAccess()`` for Input Monitoring

    If this code is running inside ``Terminal`` or an IDE-hosted terminal, the
    answer reflects trust for that host app's process context. In a packaged
    app, the answer would instead reflect trust for ``Audiby.app``.
    """
    if sys.platform != "darwin":
        return []

    app_services = _load_application_services()
    if app_services is None:
        logger.warning("ApplicationServices unavailable; skipping macOS permission preflight")
        return []

    missing: list[str] = []
    if not _has_accessibility_access(app_services):
        missing.append("Accessibility")
    if not _has_input_monitoring_access(app_services):
        missing.append("Input Monitoring")
    return missing


def _load_application_services():
    """Load Apple's ApplicationServices framework and return a ctypes handle.

    ``ApplicationServices`` is a macOS system framework that exposes native C
    APIs for graphics, accessibility, event taps, and related services.

    In this module we use it only as a container for Apple-provided permission
    check functions. Loading the framework does not enable any permission by
    itself; it only lets Python look up and call those OS APIs.
    """
    try:
        return ctypes.CDLL(_APP_SERVICES_PATH)
    except OSError as exc:
        logger.warning("Failed to load ApplicationServices: %s", exc)
        return None


def _has_accessibility_access(app_services) -> bool:
    """Return whether macOS trusts the current process for Accessibility access.

    ``AXIsProcessTrusted`` is an Apple API. macOS evaluates the current process
    against its privacy/TCC permission state and returns ``True`` when that
    process is allowed to use Accessibility features.

    Important: this function does not inspect our code or infer trust. It asks
    macOS directly and returns Apple's answer.
    """
    is_trusted = getattr(app_services, "AXIsProcessTrusted", None)
    if is_trusted is None:
        logger.warning("AXIsProcessTrusted not available; assuming Accessibility is granted")
        return True

    is_trusted.restype = ctypes.c_bool
    return bool(is_trusted())


def _has_input_monitoring_access(app_services) -> bool:
    """Return whether macOS allows the current process to listen for input events.

    ``CGPreflightListenEventAccess`` is an Apple API that checks whether the
    current process has Input Monitoring permission. This is what Audiby needs
    for global hotkey capture on macOS.

    As with Accessibility, trust is not computed here. The operating system
    owns that decision; this function only returns the OS-provided result.
    """
    preflight = getattr(app_services, "CGPreflightListenEventAccess", None)
    if preflight is None:
        logger.warning(
            "CGPreflightListenEventAccess not available; falling back to Accessibility trust status"
        )
        return _has_accessibility_access(app_services)

    preflight.restype = ctypes.c_bool
    return bool(preflight())


def _resolve_host_hint() -> str:
    """Return a user-facing hint for which app likely needs macOS permission.

    During development, Audiby often runs under ``python`` launched by
    ``Terminal``, ``iTerm``, or an IDE. macOS permissions are effectively tied
    to that host app/process context, so the error message needs to point the
    user to the launcher rather than implying that this module can grant access.
    """
    executable = Path(sys.executable).name
    if "python" in executable.lower():
        return "the app that launched Audiby (for example Terminal, iTerm, VS Code, or PyCharm)"
    return executable
