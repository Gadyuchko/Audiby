"""Behavior-focused tests for ApplicationOrchestrator.

Tests validate pipeline wiring, queue/event initialization, thread creation,
hotkey signal paths, sequential burst independence, worker exception recovery,
graceful shutdown, and settings apply (hotkey, autostart, model).
All component dependencies are mocked.
"""

import logging
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audiby.app import ApplicationOrchestrator, run_app
from audiby.exceptions import (
    AudioDeviceError,
    AudioError,
    HotkeyPermissionError,
    InjectionError,
    MicPermissionError,
    TranscriptionError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config(tmp_path):
    """Minimal Config mock with config_dir pointing to tmp_path."""
    cfg = MagicMock()
    cfg.config_dir = tmp_path
    cfg.get.side_effect = lambda key, default=None: {
        "model_size": "base",
        "push_to_talk_key": "alt+z",
    }.get(key, default)
    return cfg


@pytest.fixture
def patch_components(mocker):
    """Patch all four pipeline components so no real hardware is touched."""
    recorder_cls = mocker.patch("audiby.app.AudioRecorder")
    transcriber_cls = mocker.patch("audiby.app.Transcriber")
    injector_cls = mocker.patch("audiby.app.TextInjector")
    hotkey_cls = mocker.patch("audiby.app.get_hotkey_manager")
    mocker.patch("audiby.app.model_manager")
    return recorder_cls, transcriber_cls, injector_cls, hotkey_cls


@pytest.fixture
def orchestrator(mock_config, patch_components):
    """Create an orchestrator with all components mocked."""
    return ApplicationOrchestrator(mock_config)


# ---------------------------------------------------------------------------
# Queues and control events initialized correctly
# ---------------------------------------------------------------------------

class TestOrchestratorInit:
    def test_audio_queue_is_standard_queue(self, orchestrator):
        """audio_queue must be a queue.Queue instance for thread-safe data passing."""
        assert isinstance(orchestrator.audio_queue, queue.Queue)

    def test_text_queue_is_standard_queue(self, orchestrator):
        """text_queue must be a queue.Queue instance for thread-safe data passing."""
        assert isinstance(orchestrator.text_queue, queue.Queue)

    def test_stop_event_is_threading_event(self, orchestrator):
        """stop_event must be a threading.Event for coordinating shutdown."""
        assert isinstance(orchestrator.stop_event, threading.Event)

    def test_recording_event_is_threading_event(self, orchestrator):
        """recording_event must be a threading.Event for start/stop signaling."""
        assert isinstance(orchestrator.recording_event, threading.Event)

    def test_stop_event_not_set_initially(self, orchestrator):
        """stop_event must not be set at init — workers should run."""
        assert not orchestrator.stop_event.is_set()

    def test_recording_event_not_set_initially(self, orchestrator):
        """recording_event must not be set at init — no recording until hotkey."""
        assert not orchestrator.recording_event.is_set()

    def test_components_receive_correct_queues(self, orchestrator, patch_components):
        """AudioRecorder, Transcriber, and TextInjector must receive the shared queues."""
        recorder_cls, transcriber_cls, injector_cls, _ = patch_components

        recorder_call_kwargs = recorder_cls.call_args
        assert orchestrator.audio_queue in recorder_call_kwargs.args or \
            recorder_call_kwargs.kwargs.get("audio_queue") is orchestrator.audio_queue

        injector_call_kwargs = injector_cls.call_args
        assert orchestrator.text_queue in injector_call_kwargs.args or \
            injector_call_kwargs.kwargs.get("text_queue") is orchestrator.text_queue


# ---------------------------------------------------------------------------
# Worker threads created with expected targets and names
# ---------------------------------------------------------------------------

class TestWorkerThreads:
    def test_start_runs_mac_permission_preflight(self, orchestrator, mocker):
        preflight = mocker.patch("audiby.app.ensure_mac_input_permissions")

        orchestrator.start()
        try:
            preflight.assert_called_once()
        finally:
            orchestrator.shutdown()

    def test_start_creates_worker_threads(self, orchestrator):
        """start() must spawn worker threads for audio, transcriber, and injector."""
        orchestrator.start()
        try:
            thread_names = [t.name for t in threading.enumerate()]
            assert any("audio" in name.lower() for name in thread_names), \
                f"No audio thread found in {thread_names}"
            assert any("transcriber" in name.lower() for name in thread_names), \
                f"No transcriber thread found in {thread_names}"
            assert any("injector" in name.lower() for name in thread_names), \
                f"No injector thread found in {thread_names}"
        finally:
            orchestrator.shutdown()

    def test_worker_threads_are_daemon(self, orchestrator):
        """Worker threads must be daemon so they don't prevent process exit."""
        orchestrator.start()
        try:
            workers = [t for t in threading.enumerate()
                       if "transcriber" in t.name.lower() or "injector" in t.name.lower()]
            for w in workers:
                assert w.daemon, f"Thread {w.name} must be daemon"
        finally:
            orchestrator.shutdown()

    def test_hotkey_manager_started(self, orchestrator, patch_components):
        """start() must call HotkeyManager.start()."""
        _, _, _, hotkey_cls = patch_components
        orchestrator.start()
        try:
            hotkey_cls.return_value.start.assert_called_once()
        finally:
            orchestrator.shutdown()


# ---------------------------------------------------------------------------
# Hotkey press/release trigger start/stop signaling
# ---------------------------------------------------------------------------

class TestHotkeySignaling:
    def test_on_hotkey_press_sets_recording_event(self, orchestrator):
        """Pressing hotkey must set recording_event to signal recorder to start."""
        orchestrator.on_hotkey_press()
        assert orchestrator.recording_event.is_set()

    def test_on_hotkey_press_does_not_start_recorder_directly(self, orchestrator, patch_components):
        """Press callback should only set intent; audio worker starts recorder."""
        recorder_cls, _, _, _ = patch_components
        orchestrator.on_hotkey_press()
        recorder_cls.return_value.start.assert_not_called()

    def test_on_hotkey_release_clears_recording_event(self, orchestrator):
        """Releasing hotkey must clear recording_event."""
        orchestrator.on_hotkey_press()
        orchestrator.on_hotkey_release()
        assert not orchestrator.recording_event.is_set()

    def test_on_hotkey_release_does_not_stop_recorder_directly(self, orchestrator, patch_components):
        """Release callback should only clear intent; audio worker stops recorder."""
        recorder_cls, _, _, _ = patch_components
        orchestrator.on_hotkey_press()
        orchestrator.on_hotkey_release()
        recorder_cls.return_value.stop.assert_not_called()

    def test_hotkey_press_wakes_audio_worker_immediately(self, orchestrator, patch_components):
        """Press should wake audio worker without waiting full poll interval."""
        recorder_cls, _, _, _ = patch_components
        orchestrator._QUEUE_POLL_TIMEOUT = 1.0

        orchestrator.start()
        try:
            orchestrator.on_hotkey_press()
            time.sleep(0.1)
        finally:
            orchestrator.on_hotkey_release()
            orchestrator.shutdown()

        recorder_cls.return_value.start.assert_called()


# ---------------------------------------------------------------------------
# Sequential bursts process independently
# ---------------------------------------------------------------------------

class TestSequentialBursts:
    def test_multiple_press_release_cycles_are_independent(
        self, orchestrator, patch_components
    ):
        """Each press/release cycle must trigger a fresh start/stop via audio worker."""
        recorder_cls, _, _, _ = patch_components
        mock_recorder = recorder_cls.return_value
        orchestrator._QUEUE_POLL_TIMEOUT = 0.05

        orchestrator.start()
        try:
            orchestrator.on_hotkey_press()
            time.sleep(0.1)
            orchestrator.on_hotkey_release()
            time.sleep(0.1)

            orchestrator.on_hotkey_press()
            time.sleep(0.1)
            orchestrator.on_hotkey_release()
            time.sleep(0.1)
        finally:
            orchestrator.shutdown()

        assert mock_recorder.start.call_count == 2
        assert mock_recorder.stop.call_count == 2

    def test_recording_event_toggles_per_burst(self, orchestrator):
        """recording_event must be set during press, clear after release, for each burst."""
        for _ in range(3):
            orchestrator.on_hotkey_press()
            assert orchestrator.recording_event.is_set()
            orchestrator.on_hotkey_release()
            assert not orchestrator.recording_event.is_set()


# ---------------------------------------------------------------------------
# Worker exception logs failure and triggers recovery
# ---------------------------------------------------------------------------

class TestWorkerRecovery:
    def test_audio_error_in_worker_is_logged_not_fatal(
        self, orchestrator, patch_components, caplog
    ):
        """AudioError during worker start must be logged, not crash the orchestrator."""
        recorder_cls, _, _, _ = patch_components
        recorder_cls.return_value.start.side_effect = AudioError("device lost")
        orchestrator._QUEUE_POLL_TIMEOUT = 0.05

        with caplog.at_level(logging.ERROR, logger="audiby.app"):
            orchestrator.start()
            try:
                orchestrator.on_hotkey_press()
                time.sleep(0.2)
                orchestrator.on_hotkey_release()
            finally:
                orchestrator.shutdown()

        assert any("device lost" in r.message or "AudioError" in r.message
                    for r in caplog.records)

    def test_audio_start_failure_retries_then_recovers(
        self, orchestrator, patch_components
    ):
        """Audio worker should retry start with backoff and recover on later success."""
        recorder_cls, _, _, _ = patch_components
        recorder_cls.return_value.start.side_effect = [AudioError("device lost"), None]
        orchestrator._QUEUE_POLL_TIMEOUT = 0.02
        orchestrator._backoff_initial = 0.01
        orchestrator._backoff_max = 0.05

        orchestrator.start()
        try:
            orchestrator.on_hotkey_press()
            time.sleep(0.25)
            orchestrator.on_hotkey_release()
            time.sleep(0.1)
        finally:
            orchestrator.shutdown()

        assert recorder_cls.return_value.start.call_count >= 2
        assert recorder_cls.return_value.stop.call_count >= 1

    def test_audio_device_error_warns_and_allows_future_attempt(
        self, orchestrator, patch_components, mocker
    ):
        """Mid-session device failure should warn once and stay alive for a later attempt."""
        recorder_cls, _, _, _ = patch_components
        warning = mocker.patch("audiby.app.show_device_disconnected_warning")
        recorder_cls.return_value.start.side_effect = [AudioDeviceError("device lost"), None]
        orchestrator._QUEUE_POLL_TIMEOUT = 0.02

        orchestrator.start()
        try:
            orchestrator.on_hotkey_press()
            time.sleep(0.12)
            orchestrator.on_hotkey_release()
            time.sleep(0.05)
            assert not orchestrator.stop_event.is_set()

            orchestrator.on_hotkey_press()
            time.sleep(0.12)
            orchestrator.on_hotkey_release()
            time.sleep(0.05)
        finally:
            orchestrator.shutdown()

        warning.assert_called_once()
        assert recorder_cls.return_value.start.call_count >= 2

    def test_audio_prime_mic_permission_warns_without_stopping_app(
        self, orchestrator, patch_components, mocker
    ):
        """Startup mic denial should show guidance but keep tray-capable app alive."""
        recorder_cls, _, _, _ = patch_components
        dialog = mocker.patch("audiby.app.show_mic_permission_error")
        recorder_cls.return_value.prime.side_effect = MicPermissionError("mic denied")
        orchestrator._QUEUE_POLL_TIMEOUT = 0.02

        orchestrator.start()
        try:
            time.sleep(0.1)
            assert not orchestrator.stop_event.is_set()
        finally:
            orchestrator.shutdown()

        dialog.assert_called_once()
        recorder_cls.return_value.start.assert_not_called()

    def test_audio_start_mic_permission_warns_once_and_allows_future_attempt(
        self, orchestrator, patch_components, mocker
    ):
        """Hotkey-time mic denial should not stop the app or spam dialogs."""
        recorder_cls, _, _, _ = patch_components
        dialog = mocker.patch("audiby.app.show_mic_permission_error")
        recorder_cls.return_value.start.side_effect = [
            MicPermissionError("mic denied"),
            MicPermissionError("still denied"),
        ]
        orchestrator._QUEUE_POLL_TIMEOUT = 0.02

        orchestrator.start()
        try:
            orchestrator.on_hotkey_press()
            time.sleep(0.1)
            assert not orchestrator.stop_event.is_set()

            orchestrator.on_hotkey_press()
            time.sleep(0.1)
            assert not orchestrator.stop_event.is_set()
        finally:
            orchestrator.on_hotkey_release()
            orchestrator.shutdown()

        dialog.assert_called_once()
        assert recorder_cls.return_value.start.call_count >= 2

    def test_audio_start_failure_exceeds_max_attempts_sets_stop_event(
        self, orchestrator, patch_components
    ):
        """Audio worker should stop pipeline after bounded retry exhaustion."""
        recorder_cls, _, _, _ = patch_components
        recorder_cls.return_value.start.side_effect = AudioError("device lost")
        orchestrator._QUEUE_POLL_TIMEOUT = 0.02
        orchestrator._backoff_initial = 0.01
        orchestrator._backoff_max = 0.05
        orchestrator._MAX_RECOVERY_ATTEMPTS = 1

        orchestrator.start()
        try:
            orchestrator.on_hotkey_press()
            time.sleep(0.2)
            assert orchestrator.stop_event.is_set()
        finally:
            orchestrator.shutdown()

    def test_transcription_error_in_worker_is_logged_not_fatal(
        self, orchestrator, patch_components, caplog
    ):
        """TranscriptionError in transcriber worker must be caught and logged."""
        _, transcriber_cls, _, _ = patch_components
        mock_transcriber = transcriber_cls.return_value
        mock_transcriber.transcribe.side_effect = TranscriptionError("model fault")

        orchestrator.start()
        try:
            orchestrator.audio_queue.put(np.zeros(1600, dtype="float32"))
            time.sleep(0.3)
            assert not orchestrator.stop_event.is_set()
        finally:
            orchestrator.shutdown()

    def test_injection_error_in_worker_is_logged_not_fatal(
        self, orchestrator, patch_components, caplog
    ):
        """InjectionError in injector worker must be caught and logged."""
        _, _, injector_cls, _ = patch_components
        mock_injector = injector_cls.return_value
        mock_injector.inject.side_effect = InjectionError("paste failed")

        orchestrator.start()
        try:
            orchestrator.text_queue.put("hello world")
            time.sleep(0.3)
            assert not orchestrator.stop_event.is_set()
        finally:
            orchestrator.shutdown()

    def test_transcriber_failure_attempts_component_recovery(
        self, mock_config, patch_components
    ):
        """On worker failure, orchestrator should recreate transcriber component."""
        _, transcriber_cls, _, _ = patch_components
        first = MagicMock()
        second = MagicMock()
        first.transcribe.side_effect = TranscriptionError("first instance failed")
        transcriber_cls.side_effect = [first, second]

        orchestrator = ApplicationOrchestrator(mock_config)
        orchestrator.start()
        try:
            orchestrator.audio_queue.put(np.zeros(1600, dtype="float32"))
            time.sleep(0.3)
            assert transcriber_cls.call_count >= 2
        finally:
            orchestrator.shutdown()


# ---------------------------------------------------------------------------
# Graceful shutdown and idempotency
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_shutdown_sets_stop_event(self, orchestrator):
        """shutdown() must set stop_event to signal all workers to exit."""
        orchestrator.start()
        orchestrator.shutdown()
        assert orchestrator.stop_event.is_set()

    def test_shutdown_stops_hotkey_manager(self, orchestrator, patch_components):
        """shutdown() must call HotkeyManager.stop()."""
        _, _, _, hotkey_cls = patch_components
        orchestrator.start()
        orchestrator.shutdown()
        hotkey_cls.return_value.stop.assert_called()

    def test_shutdown_is_idempotent(self, orchestrator, patch_components):
        """Calling shutdown() twice must not raise."""
        orchestrator.start()
        orchestrator.shutdown()
        orchestrator.shutdown()

    def test_worker_threads_exit_after_shutdown(self, orchestrator):
        """Worker threads must terminate within a reasonable time after shutdown."""
        orchestrator.start()
        orchestrator.shutdown()

        time.sleep(0.5)

        thread_names = [t.name for t in threading.enumerate()]
        assert not any("transcriber" in name.lower() for name in thread_names), \
            "Transcriber thread still alive after shutdown"
        assert not any("injector" in name.lower() for name in thread_names), \
            "Injector thread still alive after shutdown"

    def test_no_transcript_text_in_logs(self, orchestrator, patch_components, caplog):
        """Privacy: transcribed text content must never appear in log output."""
        _, transcriber_cls, _, _ = patch_components
        secret_text = "my secret medical information"

        def fake_transcribe(audio):
            orchestrator.text_queue.put(secret_text)

        transcriber_cls.return_value.transcribe.side_effect = fake_transcribe

        with caplog.at_level(logging.DEBUG):
            orchestrator.start()
            orchestrator.audio_queue.put(np.zeros(1600, dtype="float32"))
            time.sleep(0.3)
            orchestrator.shutdown()

        for record in caplog.records:
            assert secret_text not in record.message, \
                f"Transcript text leaked into log: {record.message}"


# ---------------------------------------------------------------------------
# Tray lifecycle integration and quit behavior
# ---------------------------------------------------------------------------

class TestTrayIntegration:
    """Tests for tray controller integration with the application orchestrator."""

    def test_start_tray_wires_tray_callbacks(self, mock_config, patch_components, mocker):
        """ApplicationOrchestrator must wire tray callbacks when tray is started."""
        mock_tray_cls = mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")

        orch = ApplicationOrchestrator(mock_config)
        orch.start_tray()

        _, kwargs = mock_tray_cls.call_args
        assert kwargs["on_settings"] is not None
        assert kwargs["on_open_log_folder"] is not None
        assert kwargs["on_quit"] is not None

    def test_start_tray_starts_tray_controller(self, mock_config, patch_components, mocker):
        """start_tray() must delegate to the tray controller."""
        mock_tray_cls = mocker.patch("audiby.app.TrayController")
        orch = ApplicationOrchestrator(mock_config)

        orch.start_tray()

        mock_tray_cls.return_value.start.assert_called_once()

    def test_quit_from_tray_sets_stop_event(self, mock_config, patch_components, mocker):
        """Quit callback from tray must signal stop_event for graceful shutdown."""
        mock_tray_cls = mocker.patch("audiby.app.TrayController")
        orch = ApplicationOrchestrator(mock_config)

        orch.start()
        orch.start_tray()
        orch._on_tray_quit()

        assert orch.stop_event.is_set()
        mock_tray_cls.return_value.stop.assert_called()

    def test_shutdown_stops_tray(self, mock_config, patch_components, mocker):
        """shutdown() must stop the tray controller if it exists."""
        mock_tray_cls = mocker.patch("audiby.app.TrayController")
        orch = ApplicationOrchestrator(mock_config)
        orch.start()
        orch.start_tray()
        orch.shutdown()
        mock_tray_cls.return_value.stop.assert_called()

    def test_tray_shutdown_is_idempotent(self, mock_config, patch_components, mocker):
        """Multiple shutdown() calls must not raise even with tray present."""
        mock_tray_cls = mocker.patch("audiby.app.TrayController")
        orch = ApplicationOrchestrator(mock_config)
        orch.start()
        orch.shutdown()
        orch.shutdown()


# ---------------------------------------------------------------------------
# Reinitialize hotkey with updated combo
# ---------------------------------------------------------------------------

class TestReinitializeHotkey:
    """Tests for orchestrator hotkey re-registration without app restart."""

    def test_reinitialize_stops_old_manager(self, mock_config, patch_components, mocker):
        """reinitialize_hotkey() must stop the current hotkey manager."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        _, _, _, hotkey_factory = patch_components

        old_manager = hotkey_factory.return_value
        orch = ApplicationOrchestrator(mock_config)

        orch.reinitialize_hotkey("ctrl+shift+a")

        old_manager.stop.assert_called_once()

    def test_reinitialize_creates_new_manager_with_new_combo(self, mock_config, patch_components, mocker):
        """reinitialize_hotkey() must create a new manager with the provided combo."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        _, _, _, hotkey_factory = patch_components

        orch = ApplicationOrchestrator(mock_config)
        initial_call_count = hotkey_factory.call_count

        orch.reinitialize_hotkey("ctrl+shift+a")

        assert hotkey_factory.call_count == initial_call_count + 1
        last_call_args = hotkey_factory.call_args
        assert last_call_args.args[0] == "ctrl+shift+a"

    def test_reinitialize_starts_new_manager(self, mock_config, patch_components, mocker):
        """reinitialize_hotkey() must start the newly created manager."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        _, _, _, hotkey_factory = patch_components

        new_manager = MagicMock()
        hotkey_factory.side_effect = [hotkey_factory.return_value, new_manager]

        orch = ApplicationOrchestrator(mock_config)
        hotkey_factory.side_effect = [new_manager]
        orch.reinitialize_hotkey("ctrl+shift+a")

        new_manager.start.assert_called_once()

    def test_reinitialize_failure_keeps_old_manager(self, mock_config, patch_components, mocker):
        """If new hotkey registration fails, old manager must be restored."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        _, _, _, hotkey_factory = patch_components

        from audiby.exceptions import HotkeyError

        old_manager = MagicMock()
        bad_manager = MagicMock()
        bad_manager.start.side_effect = HotkeyError("registration failed")
        restored_manager = MagicMock()

        hotkey_factory.side_effect = [old_manager, bad_manager, restored_manager]

        orch = ApplicationOrchestrator(mock_config)
        result = orch.reinitialize_hotkey("bad+combo")

        assert hotkey_factory.call_count == 3
        restored_manager.start.assert_called_once()
        assert result is not None  # error string returned

    def test_reinitialize_failure_logs_error(self, mock_config, patch_components, mocker, caplog):
        """Failed hotkey re-registration must be logged."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        _, _, _, hotkey_factory = patch_components

        from audiby.exceptions import HotkeyError

        old_manager = MagicMock()
        bad_manager = MagicMock()
        bad_manager.start.side_effect = HotkeyError("registration failed")

        hotkey_factory.side_effect = [old_manager, bad_manager, MagicMock()]

        orch = ApplicationOrchestrator(mock_config)

        with caplog.at_level(logging.ERROR, logger="audiby.app"):
            orch.reinitialize_hotkey("bad+combo")

        assert any("registration failed" in r.message or "HotkeyError" in r.message
                    for r in caplog.records)

    def test_reinitialize_returns_none_on_success(self, mock_config, patch_components, mocker):
        """Successful hotkey reinit must return None."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        _, _, _, hotkey_factory = patch_components

        orch = ApplicationOrchestrator(mock_config)
        result = orch.reinitialize_hotkey("ctrl+shift+a")

        assert result is None


# ---------------------------------------------------------------------------
# apply_settings orchestrator callback
# ---------------------------------------------------------------------------

class TestApplySettings:
    """Tests for the orchestrator apply_settings callback used by SettingsWindow."""

    def test_apply_settings_returns_none_on_full_success(self, mock_config, patch_components, mocker):
        """All settings applied successfully → returns None."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mocker.patch("audiby.app.get_autostart")
        _, _, _, hotkey_factory = patch_components

        orch = ApplicationOrchestrator(mock_config)
        result = orch.apply_settings("alt+z", False, "base")

        assert result is None

    def test_apply_settings_persists_config_on_success(self, mock_config, patch_components, mocker):
        """Successful apply must call config.set() for each setting and config.save()."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mocker.patch("audiby.app.get_autostart")
        _, _, _, hotkey_factory = patch_components

        orch = ApplicationOrchestrator(mock_config)
        orch.apply_settings("alt+z", False, "base")

        mock_config.set.assert_any_call("push_to_talk_key", "alt+z")
        mock_config.save.assert_called_once()

    def test_apply_settings_returns_error_on_hotkey_failure(self, mock_config, patch_components, mocker):
        """Hotkey failure → error string returned, other settings still attempted."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mocker.patch("audiby.app.get_autostart")
        _, _, _, hotkey_factory = patch_components

        from audiby.exceptions import HotkeyError

        old_mgr = MagicMock()
        bad_mgr = MagicMock()
        bad_mgr.start.side_effect = HotkeyError("fail")
        restored_mgr = MagicMock()
        hotkey_factory.side_effect = [old_mgr, bad_mgr, restored_mgr]

        orch = ApplicationOrchestrator(mock_config)
        result = orch.apply_settings("bad+combo", False, "base")

        assert result is not None
        assert "hotkey" in result.lower() or "Failed" in result

    def test_apply_settings_returns_error_on_autostart_failure(self, mock_config, patch_components, mocker):
        """Autostart failure → error string returned."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_autostart = mocker.patch("audiby.app.get_autostart")
        mock_autostart.return_value.enable.side_effect = OSError("registry denied")
        _, _, _, hotkey_factory = patch_components

        # Config returns autostart=False so new value True triggers the change
        mock_config.get.side_effect = lambda key, default=None: {
            "model_size": "base",
            "push_to_talk_key": "alt+z",
            "start_on_boot": False,
        }.get(key, default)

        orch = ApplicationOrchestrator(mock_config)
        result = orch.apply_settings("alt+z", True, "base")

        assert result is not None
        assert "autostart" in result.lower()


# ---------------------------------------------------------------------------
# set_model model switching
# ---------------------------------------------------------------------------

class TestSetModel:
    """Tests for model switching in the orchestrator."""

    def test_no_op_when_model_unchanged(self, mock_config, patch_components, mocker):
        """If the selected model matches the active model, skip reload."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        _, transcriber_cls, _, _ = patch_components

        orch = ApplicationOrchestrator(mock_config)
        initial_transcriber = orch._transcriber
        result = orch.set_model("base")

        assert result is None
        # Transcriber should NOT have been recreated
        assert orch._transcriber is initial_transcriber

    def test_model_switch_recreates_transcriber(self, mock_config, patch_components, mocker):
        """Switching to a downloaded model must create a new Transcriber."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_mm = mocker.patch("audiby.app.model_manager")
        mock_mm.get_model_root.return_value = Path("/models")
        mock_mm.exists.return_value = True
        _, transcriber_cls, _, _ = patch_components

        orch = ApplicationOrchestrator(mock_config)
        initial_count = transcriber_cls.call_count

        result = orch.set_model("medium")

        assert result is None
        assert transcriber_cls.call_count > initial_count

    def test_model_switch_rollback_on_transcriber_failure(self, mock_config, patch_components, mocker):
        """Failed Transcriber creation must restore the previous model path."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_mm = mocker.patch("audiby.app.model_manager")
        mock_mm.get_model_root.return_value = Path("/models")
        mock_mm.exists.return_value = True
        _, transcriber_cls, _, _ = patch_components

        orch = ApplicationOrchestrator(mock_config)
        original_model_path = orch._model_path
        restored_transcriber = MagicMock()
        transcriber_cls.side_effect = [RuntimeError("load failed"), restored_transcriber]
        result = orch.set_model("medium")

        assert result is not None
        assert orch._model_path == original_model_path
        assert orch._transcriber is restored_transcriber

    def test_model_switch_releases_old_transcriber_before_loading_new_one(self, mock_config, patch_components, mocker):
        """Large model swaps should drop the old transcriber before loading the replacement."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_mm = mocker.patch("audiby.app.model_manager")
        mock_mm.get_model_root.return_value = Path("/models")
        mock_mm.exists.return_value = True

        orch = ApplicationOrchestrator(mock_config)
        release_spy = mocker.spy(orch, "_release_transcriber")

        result = orch.set_model("medium")

        assert result is None
        release_spy.assert_called_once()

    def test_model_not_downloaded_returns_error(self, mock_config, patch_components, mocker):
        """If model path doesn't exist, set_model must return error without creating Transcriber."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_mm = mocker.patch("audiby.app.model_manager")
        mock_mm.get_model_root.return_value = Path("/models")
        mock_mm.exists.return_value = False
        _, transcriber_cls, _, _ = patch_components

        orch = ApplicationOrchestrator(mock_config)
        initial_count = transcriber_cls.call_count
        result = orch.set_model("large-v3")

        assert result is not None
        assert transcriber_cls.call_count == initial_count


class TestRunAppStartupFallback:
    """Tests for startup fallback when the configured model is missing."""

    def test_missing_model_prompts_download_and_continues_boot(self, mocker, tmp_path):
        """Startup should continue when the fallback download succeeds."""
        config = MagicMock()
        config.config_dir = tmp_path
        config.get.side_effect = lambda key, default=None: {
            "model_size": "medium",
        }.get(key, default)

        mocker.patch("audiby.app.setup_logging", return_value=tmp_path / "audiby.log")
        mocker.patch("audiby.app.model_manager.exists", return_value=False)
        dialog_cls = mocker.patch("audiby.app.DownloadDialog")
        dialog_cls.return_value.run.return_value = SimpleNamespace(status="success")
        app_cls = mocker.patch("audiby.app.ApplicationOrchestrator")

        result = run_app(config)

        assert result == 0
        dialog_cls.assert_called_once_with("medium")
        app_cls.return_value.start.assert_called_once()
        app_cls.return_value.start_tray.assert_called_once()
        app_cls.return_value.shutdown.assert_called_once()

    def test_missing_model_returns_nonzero_when_download_declined_or_fails(self, mocker, tmp_path):
        """Startup should stop cleanly when the fallback dialog does not succeed."""
        config = MagicMock()
        config.config_dir = tmp_path
        config.get.side_effect = lambda key, default=None: {
            "model_size": "medium",
        }.get(key, default)

        mocker.patch("audiby.app.setup_logging", return_value=tmp_path / "audiby.log")
        mocker.patch("audiby.app.model_manager.exists", return_value=False)
        dialog_cls = mocker.patch("audiby.app.DownloadDialog")
        dialog_cls.return_value.run.return_value = SimpleNamespace(
            status="failed",
            message="Failed to download the medium model.",
        )
        app_cls = mocker.patch("audiby.app.ApplicationOrchestrator")

        result = run_app(config)

        assert result == 1
        dialog_cls.assert_called_once_with("medium")
        app_cls.assert_not_called()


class TestRunAppPermissionFailures:
    """Tests for friendly startup permission failure handling."""

    def test_mic_permission_failure_shows_dialog_and_skips_tray(self, mocker, tmp_path):
        config = MagicMock()
        config.config_dir = tmp_path
        config.get.side_effect = lambda key, default=None: {
            "model_size": "base",
            "push_to_talk_key": "alt+z",
        }.get(key, default)

        mocker.patch("audiby.app.setup_logging", return_value=tmp_path / "audiby.log")
        mocker.patch("audiby.app.model_manager.exists", return_value=True)
        mocker.patch("audiby.app.AudioRecorder")
        mocker.patch("audiby.app.Transcriber")
        mocker.patch("audiby.app.TextInjector")
        mocker.patch("audiby.app.get_hotkey_manager")
        mocker.patch(
            "audiby.app.ensure_mac_input_permissions",
            side_effect=MicPermissionError("mic denied"),
        )
        tray_cls = mocker.patch("audiby.app.TrayController")
        dialog = mocker.patch("audiby.app.show_mic_permission_error")

        result = run_app(config)

        assert result == 1
        dialog.assert_called_once()
        tray_cls.assert_not_called()

    def test_hotkey_permission_failure_shows_dialog_and_skips_tray(self, mocker, tmp_path):
        config = MagicMock()
        config.config_dir = tmp_path
        config.get.side_effect = lambda key, default=None: {
            "model_size": "base",
            "push_to_talk_key": "alt+z",
        }.get(key, default)

        mocker.patch("audiby.app.setup_logging", return_value=tmp_path / "audiby.log")
        mocker.patch("audiby.app.model_manager.exists", return_value=True)
        mocker.patch("audiby.app.AudioRecorder")
        mocker.patch("audiby.app.Transcriber")
        mocker.patch("audiby.app.TextInjector")
        hotkey_factory = mocker.patch("audiby.app.get_hotkey_manager")
        hotkey_factory.return_value.start.side_effect = HotkeyPermissionError("input denied")
        tray_cls = mocker.patch("audiby.app.TrayController")
        dialog = mocker.patch("audiby.app.show_hotkey_permission_error")

        result = run_app(config)

        assert result == 1
        dialog.assert_called_once()
        tray_cls.assert_not_called()


# ---------------------------------------------------------------------------
# set_autostart toggle
# ---------------------------------------------------------------------------

class TestSetAutostart:
    """Tests for autostart enable/disable in the orchestrator."""

    def test_no_op_when_autostart_unchanged(self, mock_config, patch_components, mocker):
        """If autostart value matches config, skip platform call."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_get_autostart = mocker.patch("audiby.app.get_autostart")

        mock_config.get.side_effect = lambda key, default=None: {
            "model_size": "base",
            "push_to_talk_key": "alt+z",
            "start_on_boot": False,
        }.get(key, default)

        orch = ApplicationOrchestrator(mock_config)
        result = orch.set_autostart(False)

        assert result is None
        mock_get_autostart.assert_not_called()

    def test_enable_autostart_calls_platform(self, mock_config, patch_components, mocker):
        """Enabling autostart must call get_autostart().enable()."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_get_autostart = mocker.patch("audiby.app.get_autostart")

        mock_config.get.side_effect = lambda key, default=None: {
            "model_size": "base",
            "push_to_talk_key": "alt+z",
            "start_on_boot": False,
        }.get(key, default)

        orch = ApplicationOrchestrator(mock_config)
        result = orch.set_autostart(True)

        assert result is None
        mock_get_autostart.return_value.enable.assert_called_once()

    def test_disable_autostart_calls_platform(self, mock_config, patch_components, mocker):
        """Disabling autostart must call get_autostart().disable()."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_get_autostart = mocker.patch("audiby.app.get_autostart")

        mock_config.get.side_effect = lambda key, default=None: {
            "model_size": "base",
            "push_to_talk_key": "alt+z",
            "start_on_boot": True,
        }.get(key, default)

        orch = ApplicationOrchestrator(mock_config)
        result = orch.set_autostart(False)

        assert result is None
        mock_get_autostart.return_value.disable.assert_called_once()

    def test_autostart_failure_returns_error(self, mock_config, patch_components, mocker):
        """Platform autostart failure must return an error string for UI display."""
        mocker.patch("audiby.app.TrayController")
        mocker.patch("audiby.app.SettingsWindow")
        mock_get_autostart = mocker.patch("audiby.app.get_autostart")
        mock_get_autostart.return_value.enable.side_effect = OSError("registry denied")

        mock_config.get.side_effect = lambda key, default=None: {
            "model_size": "base",
            "push_to_talk_key": "alt+z",
            "start_on_boot": False,
        }.get(key, default)

        orch = ApplicationOrchestrator(mock_config)
        result = orch.set_autostart(True)

        assert result is not None
        assert "autostart" in result.lower()
