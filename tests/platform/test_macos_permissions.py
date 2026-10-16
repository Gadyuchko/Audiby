"""Tests for macOS permission preflight messaging, detection, prompting, and deep links."""

import pytest

from audiby.platform import macos_permissions as mp
from audiby.platform.macos_permissions import ensure_mac_input_permissions


def test_non_mac_preflight_is_noop(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    ensure_mac_input_permissions()


def test_mac_preflight_logs_clear_message_without_blocking(monkeypatch, mocker, caplog):
    monkeypatch.setattr("sys.platform", "darwin")
    mocker.patch(
        "audiby.platform.macos_permissions.get_missing_mac_input_permissions",
        return_value=["Accessibility", "Input Monitoring"],
    )

    with caplog.at_level("WARNING", logger="audiby.platform.macos_permissions"):
        ensure_mac_input_permissions()

    message = caplog.text
    assert "Accessibility" in message
    assert "Input Monitoring" in message
    assert "System Settings > Privacy & Security" in message


def test_mac_preflight_passes_when_permissions_granted(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "darwin")
    mocker.patch(
        "audiby.platform.macos_permissions.get_missing_mac_input_permissions",
        return_value=[],
    )

    ensure_mac_input_permissions()


# ---------------------------------------------------------------------------
# Permission catalogue
# ---------------------------------------------------------------------------

def test_catalogue_covers_mic_input_monitoring_and_accessibility():
    keys = [p.key for p in mp.MAC_PERMISSIONS]
    assert keys == [
        mp.PERMISSION_MICROPHONE,
        mp.PERMISSION_INPUT_MONITORING,
        mp.PERMISSION_ACCESSIBILITY,
    ]
    for permission in mp.MAC_PERMISSIONS:
        assert permission.name
        assert permission.purpose
        assert permission.settings_pane.startswith("Privacy_")


def test_get_mac_permission_rejects_unknown_key():
    with pytest.raises(ValueError):
        mp.get_mac_permission("bogus")


# ---------------------------------------------------------------------------
# get_missing_mac_permissions / is_mac_permission_granted
# ---------------------------------------------------------------------------

def test_missing_permissions_is_empty_off_mac(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    assert mp.get_missing_mac_permissions() == []


def test_missing_permissions_lists_only_ungranted_keys(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "darwin")
    granted = {mp.PERMISSION_MICROPHONE: True, mp.PERMISSION_INPUT_MONITORING: False,
               mp.PERMISSION_ACCESSIBILITY: False}
    mocker.patch.object(mp, "is_mac_permission_granted", side_effect=lambda key: granted[key])

    assert mp.get_missing_mac_permissions() == [
        mp.PERMISSION_INPUT_MONITORING,
        mp.PERMISSION_ACCESSIBILITY,
    ]


def test_is_granted_dispatches_to_native_checks(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "darwin")
    framework = object()
    mocker.patch.object(mp, "_load_framework", return_value=framework)
    ax = mocker.patch.object(mp, "_has_accessibility_access", return_value=False)
    listen = mocker.patch.object(mp, "_has_input_monitoring_access", return_value=True)
    mic = mocker.patch.object(mp, "_has_microphone_access", return_value=True)

    assert mp.is_mac_permission_granted(mp.PERMISSION_ACCESSIBILITY) is False
    assert mp.is_mac_permission_granted(mp.PERMISSION_INPUT_MONITORING) is True
    assert mp.is_mac_permission_granted(mp.PERMISSION_MICROPHONE) is True
    ax.assert_called_once_with(framework)
    listen.assert_called_once_with(framework)
    mic.assert_called_once_with()


def test_is_granted_assumes_granted_when_framework_missing(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "darwin")
    mocker.patch.object(mp, "_load_framework", return_value=None)

    assert mp.is_mac_permission_granted(mp.PERMISSION_ACCESSIBILITY) is True
    assert mp.is_mac_permission_granted(mp.PERMISSION_INPUT_MONITORING) is True


def test_is_granted_rejects_unknown_key(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    with pytest.raises(ValueError):
        mp.is_mac_permission_granted("bogus")


@pytest.mark.parametrize(
    "status, expected",
    [
        (mp._AV_STATUS_AUTHORIZED, True),
        (mp._AV_STATUS_NOT_DETERMINED, False),
        (mp._AV_STATUS_DENIED, False),
        (mp._AV_STATUS_RESTRICTED, False),
        (None, True),
    ],
)
def test_microphone_access_maps_av_authorization_status(mocker, status, expected):
    mocker.patch.object(mp, "_microphone_authorization_status", return_value=status)
    assert mp._has_microphone_access() is expected


# ---------------------------------------------------------------------------
# request_mac_permission
# ---------------------------------------------------------------------------

def test_request_is_noop_off_mac(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert mp.request_mac_permission(mp.PERMISSION_ACCESSIBILITY) is True


def test_request_dispatches_per_permission(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "darwin")
    ax = mocker.patch.object(mp, "_request_accessibility_access", return_value=False)
    listen = mocker.patch.object(mp, "_request_input_monitoring_access", return_value=True)
    mic = mocker.patch.object(mp, "_request_microphone_access", return_value=True)

    assert mp.request_mac_permission(mp.PERMISSION_ACCESSIBILITY) is False
    assert mp.request_mac_permission(mp.PERMISSION_INPUT_MONITORING) is True
    assert mp.request_mac_permission(mp.PERMISSION_MICROPHONE) is True
    ax.assert_called_once()
    listen.assert_called_once()
    mic.assert_called_once()


def test_request_rejects_unknown_key(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    with pytest.raises(ValueError):
        mp.request_mac_permission("bogus")


def test_request_input_monitoring_calls_cg_request(mocker):
    framework = mocker.MagicMock()
    framework.CGRequestListenEventAccess.return_value = True
    mocker.patch.object(mp, "_load_framework", return_value=framework)
    probe = mocker.patch.object(mp, "_probe_event_tap")

    assert mp._request_input_monitoring_access() is True
    framework.CGRequestListenEventAccess.assert_called_once_with()
    probe.assert_not_called()


def test_request_input_monitoring_probes_event_tap_when_refused(mocker):
    """After a TCC reset only a real tap attempt re-lists the app, so one is made."""
    framework = mocker.MagicMock()
    framework.CGRequestListenEventAccess.return_value = False
    mocker.patch.object(mp, "_load_framework", return_value=framework)
    probe = mocker.patch.object(mp, "_probe_event_tap", return_value=False)
    mocker.patch.object(mp, "_has_input_monitoring_access", return_value=False)

    assert mp._request_input_monitoring_access() is False
    probe.assert_called_once_with(framework)


def test_probe_event_tap_creates_listen_only_tap_and_releases_it(mocker):
    cg = mocker.MagicMock()
    cg.CGEventTapCreate.return_value = 0x1234
    cf = mocker.MagicMock()
    mocker.patch.object(mp, "_load_framework", return_value=cf)

    assert mp._probe_event_tap(cg) is True

    args = cg.CGEventTapCreate.call_args.args
    assert args[0] == mp._CG_SESSION_EVENT_TAP
    assert args[2] == mp._CG_EVENT_TAP_OPTION_LISTEN_ONLY
    assert args[3] == 1 << mp._CG_EVENT_KEY_DOWN
    cf.CFRelease.assert_called_once_with(0x1234)


def test_probe_event_tap_reports_refusal_without_releasing(mocker):
    cg = mocker.MagicMock()
    cg.CGEventTapCreate.return_value = None
    cf = mocker.MagicMock()
    mocker.patch.object(mp, "_load_framework", return_value=cf)

    assert mp._probe_event_tap(cg) is False
    cf.CFRelease.assert_not_called()


def test_request_microphone_opens_probe_stream_then_reports_status(mocker):
    stream_cls = mocker.patch("sounddevice.InputStream")
    mocker.patch.object(mp, "_has_microphone_access", return_value=True)

    assert mp._request_microphone_access() is True
    stream_cls.assert_called_once_with(samplerate=16000, channels=1)


def test_request_microphone_survives_stream_failure(mocker):
    mocker.patch("sounddevice.InputStream", side_effect=RuntimeError("no device"))
    mocker.patch.object(mp, "_has_microphone_access", return_value=False)

    assert mp._request_microphone_access() is False


# ---------------------------------------------------------------------------
# open_mac_privacy_pane
# ---------------------------------------------------------------------------

def test_open_pane_is_noop_off_mac(monkeypatch, mocker):
    monkeypatch.setattr("sys.platform", "win32")
    popen = mocker.patch("audiby.platform.macos_permissions.subprocess.Popen")

    mp.open_mac_privacy_pane(mp.PERMISSION_ACCESSIBILITY)

    popen.assert_not_called()


@pytest.mark.parametrize(
    "key, pane",
    [
        (mp.PERMISSION_ACCESSIBILITY, "Privacy_Accessibility"),
        (mp.PERMISSION_INPUT_MONITORING, "Privacy_ListenEvent"),
        (mp.PERMISSION_MICROPHONE, "Privacy_Microphone"),
    ],
)
def test_open_pane_launches_system_settings_deep_link(monkeypatch, mocker, key, pane):
    monkeypatch.setattr("sys.platform", "darwin")
    popen = mocker.patch("audiby.platform.macos_permissions.subprocess.Popen")

    mp.open_mac_privacy_pane(key)

    argv = popen.call_args.args[0]
    assert argv[0] == "open"
    assert argv[1] == f"x-apple.systempreferences:com.apple.preference.security?{pane}"


def test_open_pane_logs_instead_of_raising_when_open_fails(monkeypatch, mocker, caplog):
    monkeypatch.setattr("sys.platform", "darwin")
    mocker.patch("audiby.platform.macos_permissions.subprocess.Popen", side_effect=OSError("nope"))

    with caplog.at_level("WARNING", logger="audiby.platform.macos_permissions"):
        mp.open_mac_privacy_pane(mp.PERMISSION_MICROPHONE)

    assert "Failed to open System Settings" in caplog.text


# ---------------------------------------------------------------------------
# Host hint
# ---------------------------------------------------------------------------

def test_host_hint_points_at_launcher_under_python(monkeypatch):
    monkeypatch.setattr("sys.executable", "/usr/local/bin/python3.11")
    assert mp.is_dev_host() is True
    assert "launched Audiby" in mp.resolve_host_hint()


def test_host_hint_names_bundle_executable(monkeypatch):
    monkeypatch.setattr("sys.executable", "/Applications/Audiby.app/Contents/MacOS/Audiby")
    assert mp.is_dev_host() is False
    assert mp.resolve_host_hint() == "Audiby"


# ---------------------------------------------------------------------------
# Relaunch
# ---------------------------------------------------------------------------

def test_bundle_path_found_from_executable_inside_app(monkeypatch, tmp_path):
    exe = tmp_path / "Audiby.app" / "Contents" / "MacOS" / "Audiby"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr("sys.executable", str(exe))

    assert mp.app_bundle_path() == (tmp_path / "Audiby.app").resolve()


def test_bundle_path_none_under_plain_interpreter(monkeypatch, tmp_path):
    exe = tmp_path / "venv" / "bin" / "python"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr("sys.executable", str(exe))

    assert mp.app_bundle_path() is None
    monkeypatch.setattr("sys.platform", "darwin")
    assert mp.can_relaunch_app() is False


def test_relaunch_schedules_detached_open_of_bundle(monkeypatch, mocker, tmp_path):
    exe = tmp_path / "Audiby.app" / "Contents" / "MacOS" / "Audiby"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr("sys.executable", str(exe))
    monkeypatch.setattr("sys.platform", "darwin")
    popen = mocker.patch("audiby.platform.macos_permissions.subprocess.Popen")

    assert mp.can_relaunch_app() is True
    assert mp.relaunch_app() is True

    argv = popen.call_args.args[0]
    assert argv[0] == "/bin/sh"
    assert "open -n" in argv[2]
    assert argv[-1] == str((tmp_path / "Audiby.app").resolve())
    assert popen.call_args.kwargs["start_new_session"] is True


def test_relaunch_reports_failure_when_open_cannot_start(monkeypatch, mocker, tmp_path):
    exe = tmp_path / "Audiby.app" / "Contents" / "MacOS" / "Audiby"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr("sys.executable", str(exe))
    monkeypatch.setattr("sys.platform", "darwin")
    mocker.patch("audiby.platform.macos_permissions.subprocess.Popen", side_effect=OSError("nope"))

    assert mp.relaunch_app() is False


def test_relaunch_is_noop_outside_bundle(monkeypatch, mocker, tmp_path):
    monkeypatch.setattr("sys.executable", str(tmp_path / "python"))
    monkeypatch.setattr("sys.platform", "darwin")
    popen = mocker.patch("audiby.platform.macos_permissions.subprocess.Popen")

    assert mp.relaunch_app() is False
    popen.assert_not_called()
