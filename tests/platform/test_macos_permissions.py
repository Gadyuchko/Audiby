"""Tests for macOS permission preflight messaging and detection."""

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
