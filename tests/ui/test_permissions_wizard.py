"""Tests for the macOS permissions wizard with mocked tkinter and platform calls."""

from unittest.mock import MagicMock

import pytest

from audiby.platform.macos_permissions import (
    MAC_PERMISSIONS,
    PERMISSION_ACCESSIBILITY,
    PERMISSION_INPUT_MONITORING,
    PERMISSION_MICROPHONE,
)
from audiby.ui import permissions_wizard as pw
from audiby.ui.permissions_wizard import PermissionsWizard

_P = "audiby.ui.permissions_wizard"


@pytest.fixture
def mock_tk(mocker):
    """Mock tkinter so no real GUI window is created.

    ``after`` records callbacks instead of running them so the periodic status
    poll cannot recurse during a test; tests invoke the recorded callback when
    they want a tick.
    """
    tk_cls = mocker.patch(f"{_P}.tk.Tk")
    mocker.patch(f"{_P}.tk.Toplevel", create=True)
    label_cls = mocker.patch(f"{_P}.ttk.Label", create=True)
    button_cls = mocker.patch(f"{_P}.ttk.Button", create=True)
    # One widget mock per constructed widget, so per-row status labels and
    # buttons can be asserted independently.
    label_cls.side_effect = lambda *args, **kwargs: MagicMock(name="Label")
    button_cls.side_effect = lambda *args, **kwargs: MagicMock(name="Button")
    mocker.patch(f"{_P}.ttk.Frame", create=True)
    mocker.patch(f"{_P}.ttk.Separator", create=True)

    window = MagicMock()
    scheduled: list = []
    window.after.side_effect = lambda _delay, callback: scheduled.append(callback)
    window.mainloop.side_effect = lambda: None
    tk_cls.return_value = window

    return {
        "Tk": tk_cls,
        "Label": label_cls,
        "Button": button_cls,
        "window": window,
        "scheduled": scheduled,
    }


class _Platform:
    """Fake permission backend with mutable state."""

    def __init__(self, granted: dict[str, bool]):
        self.granted = dict(granted)
        self.requested: list[str] = []
        self.opened: list[str] = []
        # Which permissions flip to granted when requested.
        self.grant_on_request: set[str] = set()

    def is_granted(self, key: str) -> bool:
        return self.granted[key]

    def request(self, key: str) -> bool:
        self.requested.append(key)
        if key in self.grant_on_request:
            self.granted[key] = True
        return self.granted[key]

    def open_pane(self, key: str) -> None:
        self.opened.append(key)


def _make_wizard(
    platform: _Platform,
    *,
    dev_host: bool = False,
    can_relaunch: bool = False,
    relaunch=None,
) -> PermissionsWizard:
    return PermissionsWizard(
        [k for k, ok in platform.granted.items() if not ok],
        is_granted=platform.is_granted,
        request=platform.request,
        open_pane=platform.open_pane,
        host_hint=lambda: "Terminal",
        dev_host=lambda: dev_host,
        can_relaunch=lambda: can_relaunch,
        relaunch=relaunch or (lambda: False),
    )


def _buttons_by_text(mock_tk) -> dict[str, list[MagicMock]]:
    found: dict[str, list[MagicMock]] = {}
    for call in mock_tk["Button"].call_args_list:
        found.setdefault(call.kwargs["text"], []).append(call)
    return found


def _label_texts(mock_tk) -> list[str]:
    return [call.kwargs.get("text", "") for call in mock_tk["Label"].call_args_list]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestRendering:
    def test_renders_one_row_per_permission_with_allow_and_settings_buttons(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform)

        wizard.run()

        texts = _label_texts(mock_tk)
        for permission in MAC_PERMISSIONS:
            assert permission.name in texts
            assert permission.purpose in texts
        buttons = _buttons_by_text(mock_tk)
        assert len(buttons["Allow…"]) == len(MAC_PERMISSIONS)
        assert len(buttons["Open Settings"]) == len(MAC_PERMISSIONS)
        assert len(buttons["Quit"]) == 1
        assert len(buttons["Continue"]) == 1

    def test_dev_host_note_names_launcher_only_when_running_from_source(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})

        _make_wizard(platform, dev_host=True).run()
        assert any("Terminal" in text for text in _label_texts(mock_tk))

        mock_tk["Label"].reset_mock()
        _make_wizard(platform, dev_host=False, can_relaunch=True).run()
        assert not any("Terminal" in text for text in _label_texts(mock_tk))

    def test_bundle_shows_relaunch_note_and_button(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})

        _make_wizard(platform, can_relaunch=True).run()

        assert pw.WIZARD_RELAUNCH_NOTE in _label_texts(mock_tk)
        assert "Relaunch" in _buttons_by_text(mock_tk)

    def test_source_run_shows_host_restart_note_without_relaunch_button(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})

        _make_wizard(platform, dev_host=True, can_relaunch=False).run()

        texts = _label_texts(mock_tk)
        assert pw.WIZARD_DEV_RELAUNCH_NOTE.format(host="Terminal") in texts
        assert pw.WIZARD_RELAUNCH_NOTE not in texts
        assert "Relaunch" not in _buttons_by_text(mock_tk)

    def test_window_is_brought_to_front_and_polls_status(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})

        _make_wizard(platform).run()

        window = mock_tk["window"]
        window.lift.assert_called_once()
        assert len(mock_tk["scheduled"]) >= 1


# ---------------------------------------------------------------------------
# Status refresh
# ---------------------------------------------------------------------------

class TestStatusRefresh:
    def test_status_labels_reflect_granted_state(self, mock_tk):
        platform = _Platform({
            PERMISSION_MICROPHONE: True,
            PERMISSION_INPUT_MONITORING: False,
            PERMISSION_ACCESSIBILITY: False,
        })
        wizard = _make_wizard(platform)

        wizard.run()

        mic_label = wizard._status_labels[PERMISSION_MICROPHONE]
        listen_label = wizard._status_labels[PERMISSION_INPUT_MONITORING]
        assert mic_label.configure.call_args.kwargs["text"] == pw.STATUS_GRANTED
        assert listen_label.configure.call_args.kwargs["text"] == pw.STATUS_MISSING

    def test_allow_button_disabled_once_granted(self, mock_tk):
        platform = _Platform({
            PERMISSION_MICROPHONE: True,
            PERMISSION_INPUT_MONITORING: False,
            PERMISSION_ACCESSIBILITY: False,
        })
        wizard = _make_wizard(platform)

        wizard.run()

        assert wizard._allow_buttons[PERMISSION_MICROPHONE].state.call_args.args[0] == ["disabled"]
        assert wizard._allow_buttons[PERMISSION_ACCESSIBILITY].state.call_args.args[0] == ["!disabled"]

    def test_summary_and_continue_label_follow_missing_state(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform)
        wizard.run()

        assert wizard._summary_label.configure.call_args.kwargs["text"] == pw.WIZARD_SOME_MISSING
        assert wizard._continue_button.configure.call_args.kwargs["text"] == "Continue anyway"

        for key in platform.granted:
            platform.granted[key] = True
        wizard._poll()

        assert wizard._summary_label.configure.call_args.kwargs["text"] == pw.WIZARD_ALL_GRANTED
        assert wizard._continue_button.configure.call_args.kwargs["text"] == "Continue"

    @staticmethod
    def _poll_callbacks(mock_tk, wizard) -> list:
        return [cb for cb in mock_tk["scheduled"] if cb == wizard._poll]

    def test_poll_reschedules_itself_while_open(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform)
        wizard.run()
        before = len(self._poll_callbacks(mock_tk, wizard))
        assert before == 1

        self._poll_callbacks(mock_tk, wizard)[-1]()

        assert len(self._poll_callbacks(mock_tk, wizard)) == before + 1

    def test_poll_stops_after_close(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform)
        wizard.run()
        wizard._on_continue()
        before = len(self._poll_callbacks(mock_tk, wizard))

        self._poll_callbacks(mock_tk, wizard)[-1]()

        assert len(self._poll_callbacks(mock_tk, wizard)) == before


# ---------------------------------------------------------------------------
# Button handlers
# ---------------------------------------------------------------------------

class TestActions:
    def test_allow_requests_permission_and_refreshes(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        platform.grant_on_request.add(PERMISSION_INPUT_MONITORING)
        wizard = _make_wizard(platform)
        wizard.run()

        wizard._on_allow(PERMISSION_INPUT_MONITORING)

        assert platform.requested == [PERMISSION_INPUT_MONITORING]
        label = wizard._status_labels[PERMISSION_INPUT_MONITORING]
        assert label.configure.call_args.kwargs["text"] == pw.STATUS_GRANTED

    def test_allow_survives_request_failure(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = PermissionsWizard(
            is_granted=platform.is_granted,
            request=MagicMock(side_effect=OSError("boom")),
            open_pane=platform.open_pane,
            host_hint=lambda: "Terminal",
            dev_host=lambda: False,
        )
        wizard.run()

        wizard._on_allow(PERMISSION_ACCESSIBILITY)

        label = wizard._status_labels[PERMISSION_ACCESSIBILITY]
        assert label.configure.call_args.kwargs["text"] == pw.STATUS_MISSING

    def test_open_settings_opens_pane_for_that_permission(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform)
        wizard.run()

        wizard._on_open_settings(PERMISSION_MICROPHONE)

        assert platform.opened == [PERMISSION_MICROPHONE]

    def test_continue_returns_remaining_missing_permissions(self, mock_tk):
        platform = _Platform({
            PERMISSION_MICROPHONE: True,
            PERMISSION_INPUT_MONITORING: False,
            PERMISSION_ACCESSIBILITY: True,
        })
        wizard = _make_wizard(platform)
        wizard.run()

        wizard._on_continue()

        assert wizard.result.status == "continue"
        assert wizard.result.missing == [PERMISSION_INPUT_MONITORING]
        mock_tk["window"].quit.assert_called_once()
        mock_tk["window"].destroy.assert_called_once()

    def test_quit_and_window_close_report_quit(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform)
        wizard.run()

        wizard._on_quit()

        assert wizard.result.status == "quit"
        close_handler = mock_tk["window"].protocol.call_args.args
        assert close_handler[0] == "WM_DELETE_WINDOW"
        assert close_handler[1] == wizard._on_quit

    def test_close_is_idempotent(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform)
        wizard.run()

        wizard._on_continue()
        wizard._close()

        mock_tk["window"].destroy.assert_called_once()
        assert wizard.result.status == "continue"

    def test_relaunch_schedules_new_instance_and_reports_relaunch(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        relaunch = MagicMock(return_value=True)
        wizard = _make_wizard(platform, can_relaunch=True, relaunch=relaunch)
        wizard.run()

        wizard._on_relaunch()

        relaunch.assert_called_once_with()
        assert wizard.result.status == "relaunch"
        mock_tk["window"].destroy.assert_called_once()

    def test_relaunch_failure_keeps_window_open(self, mock_tk):
        platform = _Platform({p.key: False for p in MAC_PERMISSIONS})
        wizard = _make_wizard(platform, can_relaunch=True, relaunch=MagicMock(return_value=False))
        wizard.run()

        wizard._on_relaunch()

        assert wizard.result.status == "quit"
        mock_tk["window"].destroy.assert_not_called()
