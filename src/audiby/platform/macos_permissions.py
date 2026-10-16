"""macOS permission preflight, prompting, and settings deep links.

Audiby needs three protected capabilities on macOS:

- Accessibility: required for synthetic key events used during text injection
- Input Monitoring: required for global hotkey listening
- Microphone: required to capture speech

This module asks macOS about the *current process* and, on request, triggers
the operating system's own permission prompts. It never grants anything by
itself: Apple requires the user to flip each toggle, so the most this code can
do is fire the system dialog, pre-register the app in the right list, and open
System Settings on the right pane.

Why ``ctypes`` is used here:
- Python itself does not expose these permission APIs directly
- macOS provides them inside Apple's ``ApplicationServices``, ``CoreFoundation``
  and ``AVFoundation`` frameworks
- ``ctypes.CDLL(...)`` loads those native frameworks so Python can call them

How "trusted" is derived:
- We call Apple's APIs, not our own heuristics
- ``AXIsProcessTrusted()`` reports Accessibility trust
- ``CGPreflightListenEventAccess()`` reports Input Monitoring access
- ``AVCaptureDevice.authorizationStatusForMediaType:`` reports Microphone access

Permission state is tied to the launching app bundle. Under ``uv run`` that is
the terminal or IDE hosting Python; in the packaged release it is ``Audiby.app``.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_APP_SERVICES_PATH = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_CORE_FOUNDATION_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_AV_FOUNDATION_PATH = "/System/Library/Frameworks/AVFoundation.framework/AVFoundation"
_OBJC_PATH = "/usr/lib/libobjc.dylib"

# AVAuthorizationStatus values from AVFoundation.
_AV_STATUS_NOT_DETERMINED = 0
_AV_STATUS_RESTRICTED = 1
_AV_STATUS_DENIED = 2
_AV_STATUS_AUTHORIZED = 3

# Deep-link scheme that opens System Settings > Privacy & Security on one pane.
_PRIVACY_PANE_URL = "x-apple.systempreferences:com.apple.preference.security?{pane}"

PERMISSION_ACCESSIBILITY = "accessibility"
PERMISSION_INPUT_MONITORING = "input_monitoring"
PERMISSION_MICROPHONE = "microphone"


@dataclass(frozen=True)
class MacPermission:
    """One protected capability Audiby needs, with user-facing copy."""

    key: str
    name: str
    purpose: str
    settings_pane: str
    # Accessibility and Input Monitoring grants apply to event taps created
    # after the grant, so a process that already tried may need a relaunch.
    needs_relaunch: bool


MAC_PERMISSIONS: tuple[MacPermission, ...] = (
    MacPermission(
        key=PERMISSION_MICROPHONE,
        name="Microphone",
        purpose="Capture your voice while the push-to-talk key is held.",
        settings_pane="Privacy_Microphone",
        needs_relaunch=False,
    ),
    MacPermission(
        key=PERMISSION_INPUT_MONITORING,
        name="Input Monitoring",
        purpose="Detect the push-to-talk hotkey while other apps are focused.",
        settings_pane="Privacy_ListenEvent",
        needs_relaunch=True,
    ),
    MacPermission(
        key=PERMISSION_ACCESSIBILITY,
        name="Accessibility",
        purpose="Paste the transcribed text into the active window.",
        settings_pane="Privacy_Accessibility",
        needs_relaunch=True,
    ),
)


def ensure_mac_input_permissions() -> None:
    """Log macOS input permission status without blocking application startup.

    This is a startup preflight only. It does not request, enable, or modify
    any OS permissions. It asks macOS whether the current process is already
    authorized and logs actionable guidance when permissions appear to be missing.

    The check is intentionally non-fatal because macOS/TCC can report permission
    state inconsistently for unsigned or relocated app bundles. Runtime hotkey
    registration remains the authoritative failure point.
    """
    if sys.platform != "darwin":
        return

    missing = get_missing_mac_input_permissions()
    if not missing:
        return

    host = resolve_host_hint()
    missing_text = ", ".join(missing)
    logger.warning(
        "macOS permissions missing: "
        f"{missing_text}. Enable them for {host} in System Settings > Privacy & Security, "
        "then fully restart that host app."
    )


def get_missing_mac_input_permissions() -> list[str]:
    """Return missing macOS *input* permissions (display names) for this process.

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

    app_services = _load_framework(_APP_SERVICES_PATH)
    if app_services is None:
        logger.warning("ApplicationServices unavailable; skipping macOS permission preflight")
        return []

    missing: list[str] = []
    if not _has_accessibility_access(app_services):
        missing.append("Accessibility")
    if not _has_input_monitoring_access(app_services):
        missing.append("Input Monitoring")
    return missing


def get_missing_mac_permissions() -> list[str]:
    """Return the keys of every permission Audiby needs that is not granted.

    Includes the microphone on top of the input permissions. A permission whose
    state cannot be determined (framework missing, API absent) is treated as
    granted so a probe failure never blocks startup.
    """
    if sys.platform != "darwin":
        return []
    return [perm.key for perm in MAC_PERMISSIONS if not is_mac_permission_granted(perm.key)]


def is_mac_permission_granted(key: str) -> bool:
    """Ask macOS whether the current process holds the given permission."""
    if sys.platform != "darwin":
        return True
    if key == PERMISSION_ACCESSIBILITY:
        app_services = _load_framework(_APP_SERVICES_PATH)
        return True if app_services is None else _has_accessibility_access(app_services)
    if key == PERMISSION_INPUT_MONITORING:
        app_services = _load_framework(_APP_SERVICES_PATH)
        return True if app_services is None else _has_input_monitoring_access(app_services)
    if key == PERMISSION_MICROPHONE:
        return _has_microphone_access()
    raise ValueError(f"Unknown macOS permission: {key}")


def request_mac_permission(key: str) -> bool:
    """Trigger the macOS system prompt for one permission and return its state.

    Each capability has its own Apple-sanctioned way to prompt:

    - Accessibility: ``AXIsProcessTrustedWithOptions`` with the prompt option
      shows the "would like to control this computer" dialog and adds the app
      to the Accessibility list so the user only has to flip the toggle.
    - Input Monitoring: ``CGRequestListenEventAccess`` does the same for the
      Input Monitoring list.
    - Microphone: opening an input stream makes macOS show the microphone
      prompt the first time; later calls are silent.

    The prompt only appears when the state is "not determined". Once the user
    has denied, macOS stays silent and the settings pane is the only way back,
    which is why callers pair this with :func:`open_mac_privacy_pane`.
    """
    if sys.platform != "darwin":
        return True
    if key == PERMISSION_ACCESSIBILITY:
        return _request_accessibility_access()
    if key == PERMISSION_INPUT_MONITORING:
        return _request_input_monitoring_access()
    if key == PERMISSION_MICROPHONE:
        return _request_microphone_access()
    raise ValueError(f"Unknown macOS permission: {key}")


def open_mac_privacy_pane(key: str) -> None:
    """Open System Settings > Privacy & Security on the pane for ``key``."""
    if sys.platform != "darwin":
        return
    permission = get_mac_permission(key)
    url = _PRIVACY_PANE_URL.format(pane=permission.settings_pane)
    logger.debug("Opening macOS privacy pane: %s", url)
    try:
        subprocess.Popen(["open", url])
    except OSError as exc:
        logger.warning("Failed to open System Settings pane %s: %s", permission.settings_pane, exc)


def get_mac_permission(key: str) -> MacPermission:
    """Return the :class:`MacPermission` definition for ``key``."""
    for permission in MAC_PERMISSIONS:
        if permission.key == key:
            return permission
    raise ValueError(f"Unknown macOS permission: {key}")


def is_dev_host() -> bool:
    """Return True when Audiby runs under a plain Python interpreter.

    In that case macOS attributes permissions to whichever app launched
    Python (Terminal, iTerm, an IDE), not to Audiby itself.
    """
    return "python" in Path(sys.executable).name.lower()


def resolve_host_hint() -> str:
    """Return a user-facing hint for which app likely needs macOS permission.

    During development, Audiby often runs under ``python`` launched by
    ``Terminal``, ``iTerm``, or an IDE. macOS permissions are effectively tied
    to that host app/process context, so the error message needs to point the
    user to the launcher rather than implying that this module can grant access.
    """
    if is_dev_host():
        return "the app that launched Audiby (for example Terminal, iTerm, VS Code, or PyCharm)"
    return Path(sys.executable).name


# Kept for callers and tests that still use the private name.
_resolve_host_hint = resolve_host_hint


def app_bundle_path() -> Path | None:
    """Return the ``.app`` bundle this process runs from, or None outside a bundle."""
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def can_relaunch_app() -> bool:
    """Return True when this process can relaunch itself as a fresh app instance.

    Only the packaged bundle qualifies. Under a plain interpreter the grants
    belong to the terminal or IDE, which has to be restarted by hand.
    """
    return sys.platform == "darwin" and app_bundle_path() is not None


def relaunch_app() -> bool:
    """Schedule a fresh launch of this app bundle and return True on success.

    macOS applies Accessibility and Input Monitoring grants to processes
    started after the grant, so the running instance must exit and a new one
    must start. The launch is delayed by a detached shell so the new instance
    comes up after this one has exited; the caller is expected to exit
    promptly after a True result.
    """
    bundle = app_bundle_path()
    if sys.platform != "darwin" or bundle is None:
        return False
    try:
        subprocess.Popen(
            ["/bin/sh", "-c", 'sleep 1; exec open -n "$0"', str(bundle)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.warning("Failed to schedule relaunch of %s: %s", bundle, exc)
        return False
    logger.info("Scheduled relaunch of %s", bundle)
    return True


# ---------------------------------------------------------------------------
# Framework loading
# ---------------------------------------------------------------------------

def _load_framework(path: str):
    """Load an Apple system framework and return a ctypes handle, or None.

    Loading a framework does not enable any permission by itself; it only lets
    Python look up and call Apple's permission APIs.
    """
    try:
        return ctypes.CDLL(path)
    except OSError as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def _load_application_services():
    """Backwards-compatible alias used by older callers and tests."""
    return _load_framework(_APP_SERVICES_PATH)


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------

def _has_accessibility_access(app_services) -> bool:
    """Return whether macOS trusts the current process for Accessibility access.

    ``AXIsProcessTrusted`` is an Apple API. macOS evaluates the current process
    against its privacy/TCC permission state and returns ``True`` when that
    process is allowed to use Accessibility features.
    """
    is_trusted = getattr(app_services, "AXIsProcessTrusted", None)
    if is_trusted is None:
        logger.warning("AXIsProcessTrusted not available; assuming Accessibility is granted")
        return True

    is_trusted.restype = ctypes.c_bool
    return bool(is_trusted())


def _request_accessibility_access() -> bool:
    """Call ``AXIsProcessTrustedWithOptions`` with the prompt option enabled.

    The options argument is a ``CFDictionary`` mapping
    ``kAXTrustedCheckOptionPrompt`` to ``kCFBooleanTrue``; both constants are
    exported globals, so they are read with ``in_dll`` rather than created.
    """
    app_services = _load_framework(_APP_SERVICES_PATH)
    core_foundation = _load_framework(_CORE_FOUNDATION_PATH)
    if app_services is None or core_foundation is None:
        return True

    with_options = getattr(app_services, "AXIsProcessTrustedWithOptions", None)
    if with_options is None:
        logger.warning("AXIsProcessTrustedWithOptions not available; cannot prompt")
        return _has_accessibility_access(app_services)

    try:
        prompt_key = ctypes.c_void_p.in_dll(app_services, "kAXTrustedCheckOptionPrompt")
        true_value = ctypes.c_void_p.in_dll(core_foundation, "kCFBooleanTrue")
        key_callbacks = ctypes.addressof(
            ctypes.c_char.in_dll(core_foundation, "kCFTypeDictionaryKeyCallBacks")
        )
        value_callbacks = ctypes.addressof(
            ctypes.c_char.in_dll(core_foundation, "kCFTypeDictionaryValueCallBacks")
        )
    except ValueError as exc:
        logger.warning("Accessibility prompt constants unavailable: %s", exc)
        return _has_accessibility_access(app_services)

    create_dict = core_foundation.CFDictionaryCreate
    create_dict.restype = ctypes.c_void_p
    create_dict.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    release.restype = None

    keys = (ctypes.c_void_p * 1)(prompt_key.value)
    values = (ctypes.c_void_p * 1)(true_value.value)
    options = create_dict(None, keys, values, 1, key_callbacks, value_callbacks)
    if not options:
        logger.warning("CFDictionaryCreate failed; cannot prompt for Accessibility")
        return _has_accessibility_access(app_services)

    with_options.restype = ctypes.c_bool
    with_options.argtypes = [ctypes.c_void_p]
    try:
        granted = bool(with_options(options))
    finally:
        release(options)
    logger.info("Accessibility prompt issued; granted=%s", granted)
    return granted


# ---------------------------------------------------------------------------
# Input Monitoring
# ---------------------------------------------------------------------------

def _has_input_monitoring_access(app_services) -> bool:
    """Return whether macOS allows the current process to listen for input events.

    ``CGPreflightListenEventAccess`` is an Apple API that checks whether the
    current process has Input Monitoring permission. This is what Audiby needs
    for global hotkey capture on macOS.
    """
    preflight = getattr(app_services, "CGPreflightListenEventAccess", None)
    if preflight is None:
        logger.warning(
            "CGPreflightListenEventAccess not available; falling back to Accessibility trust status"
        )
        return _has_accessibility_access(app_services)

    preflight.restype = ctypes.c_bool
    return bool(preflight())


def _request_input_monitoring_access() -> bool:
    """Raise the Input Monitoring prompt and register the app in its list.

    ``CGRequestListenEventAccess`` shows the prompt, but after a TCC reset
    macOS does not always put the app back in the Input Monitoring list from
    that call alone. Creating a listen-only event tap is what registers an
    app there, so a throwaway tap is attempted as well; when permission is
    missing the tap simply fails to create, which is harmless.
    """
    app_services = _load_framework(_APP_SERVICES_PATH)
    if app_services is None:
        return True

    request = getattr(app_services, "CGRequestListenEventAccess", None)
    if request is None:
        logger.warning("CGRequestListenEventAccess not available; cannot prompt")
        return _has_input_monitoring_access(app_services)

    request.restype = ctypes.c_bool
    granted = bool(request())
    logger.info("Input Monitoring prompt issued; granted=%s", granted)
    if not granted:
        _probe_event_tap(app_services)
        granted = _has_input_monitoring_access(app_services)
    return granted


# CoreGraphics event tap constants (CGEventTypes.h).
_CG_SESSION_EVENT_TAP = 1
_CG_HEAD_INSERT_EVENT_TAP = 0
_CG_EVENT_TAP_OPTION_LISTEN_ONLY = 1
_CG_EVENT_KEY_DOWN = 10

_EVENT_TAP_CALLBACK = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p
)


def _probe_event_tap(app_services) -> bool:
    """Create and immediately release a listen-only keyboard event tap.

    Returns True when the tap could be created (permission present). The
    attempt itself makes macOS list the app under Input Monitoring.
    """
    create = getattr(app_services, "CGEventTapCreate", None)
    core_foundation = _load_framework(_CORE_FOUNDATION_PATH)
    if create is None or core_foundation is None:
        return False
    create.restype = ctypes.c_void_p
    create.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint64,
        _EVENT_TAP_CALLBACK,
        ctypes.c_void_p,
    ]
    callback = _EVENT_TAP_CALLBACK(lambda _proxy, _type, event, _refcon: event)
    tap = create(
        _CG_SESSION_EVENT_TAP,
        _CG_HEAD_INSERT_EVENT_TAP,
        _CG_EVENT_TAP_OPTION_LISTEN_ONLY,
        1 << _CG_EVENT_KEY_DOWN,
        callback,
        None,
    )
    if not tap:
        logger.info("Event tap probe refused; app should now appear under Input Monitoring")
        return False
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    release.restype = None
    release(tap)
    return True


# ---------------------------------------------------------------------------
# Microphone
# ---------------------------------------------------------------------------

def _microphone_authorization_status() -> int | None:
    """Return the ``AVAuthorizationStatus`` for audio capture, or None if unknown.

    Calls ``[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio]``
    through the Objective-C runtime. Any failure to reach the API yields None so
    the caller can fall back to "assume granted".
    """
    objc = _load_framework(_OBJC_PATH)
    av_foundation = _load_framework(_AV_FOUNDATION_PATH)
    if objc is None or av_foundation is None:
        return None

    try:
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend
        send.restype = ctypes.c_long
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

        capture_device = objc.objc_getClass(b"AVCaptureDevice")
        selector = objc.sel_registerName(b"authorizationStatusForMediaType:")
        media_type = ctypes.c_void_p.in_dll(av_foundation, "AVMediaTypeAudio")
        if not capture_device or not selector or not media_type.value:
            return None
        return int(send(capture_device, selector, media_type.value))
    except (AttributeError, ValueError, OSError) as exc:
        logger.warning("Microphone authorization status unavailable: %s", exc)
        return None


def _has_microphone_access() -> bool:
    """Return whether the current process may capture audio.

    "Not determined" counts as missing so the wizard can trigger the prompt.
    An unknown status (API unreachable) counts as granted so startup proceeds
    and the recorder's own error path stays authoritative.
    """
    status = _microphone_authorization_status()
    if status is None:
        return True
    return status == _AV_STATUS_AUTHORIZED


def _request_microphone_access() -> bool:
    """Open and immediately close an input stream to raise the microphone prompt.

    CoreAudio shows the system microphone dialog the first time a process opens
    an input device. The stream is torn down right away; nothing is recorded.
    """
    try:
        import sounddevice as sd

        with sd.InputStream(samplerate=16000, channels=1):
            pass
    except Exception as exc:
        logger.info("Microphone probe stream failed (prompt may still have shown): %s", exc)
    return _has_microphone_access()
