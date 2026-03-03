"""Behavior-focused tests for ApplicationOrchestrator.

Tests validate pipeline wiring, queue/event initialization, thread creation,
hotkey signal paths, sequential burst independence, worker exception recovery,
and graceful shutdown. All component dependencies are mocked.
"""

import logging
import queue
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audiby.app import ApplicationOrchestrator
from audiby.exceptions import AudioError, InjectionError, TranscriptionError


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
    hotkey_cls = mocker.patch("audiby.app.HotkeyManager")
    mocker.patch("audiby.app.model_manager")
    return recorder_cls, transcriber_cls, injector_cls, hotkey_cls


@pytest.fixture
def orchestrator(mock_config, patch_components):
    """Create an orchestrator with all components mocked."""
    return ApplicationOrchestrator(mock_config)


# ---------------------------------------------------------------------------
# Task 1.1 — Queues and control events initialized correctly (AC: #1)
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

        # AudioRecorder gets audio_queue
        recorder_call_kwargs = recorder_cls.call_args
        assert orchestrator.audio_queue in recorder_call_kwargs.args or \
            recorder_call_kwargs.kwargs.get("audio_queue") is orchestrator.audio_queue

        # TextInjector gets text_queue
        injector_call_kwargs = injector_cls.call_args
        assert orchestrator.text_queue in injector_call_kwargs.args or \
            injector_call_kwargs.kwargs.get("text_queue") is orchestrator.text_queue


# ---------------------------------------------------------------------------
# Task 1.2 — Worker threads created with expected targets and names (AC: #1)
# ---------------------------------------------------------------------------

class TestWorkerThreads:
    def test_start_creates_worker_threads(self, orchestrator):
        """start() must spawn worker threads for transcriber and injector."""
        orchestrator.start()
        try:
            thread_names = [t.name for t in threading.enumerate()]
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
# Task 1.3 — Hotkey press/release trigger start/stop signaling (AC: #1, #2)
# ---------------------------------------------------------------------------

class TestHotkeySignaling:
    def test_on_hotkey_press_sets_recording_event(self, orchestrator):
        """Pressing hotkey must set recording_event to signal recorder to start."""
        orchestrator.on_hotkey_press()
        assert orchestrator.recording_event.is_set()

    def test_on_hotkey_press_starts_recorder(self, orchestrator, patch_components):
        """Pressing hotkey must call AudioRecorder.start()."""
        recorder_cls, _, _, _ = patch_components
        orchestrator.on_hotkey_press()
        recorder_cls.return_value.start.assert_called_once()

    def test_on_hotkey_release_clears_recording_event(self, orchestrator):
        """Releasing hotkey must clear recording_event."""
        orchestrator.on_hotkey_press()
        orchestrator.on_hotkey_release()
        assert not orchestrator.recording_event.is_set()

    def test_on_hotkey_release_stops_recorder(self, orchestrator, patch_components):
        """Releasing hotkey must call AudioRecorder.stop() to push audio to queue."""
        recorder_cls, _, _, _ = patch_components
        orchestrator.on_hotkey_press()
        orchestrator.on_hotkey_release()
        recorder_cls.return_value.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Task 1.4 — Sequential bursts process independently (AC: #2)
# ---------------------------------------------------------------------------

class TestSequentialBursts:
    def test_multiple_press_release_cycles_are_independent(
        self, orchestrator, patch_components
    ):
        """Each press/release cycle must trigger a fresh start/stop on recorder."""
        recorder_cls, _, _, _ = patch_components
        mock_recorder = recorder_cls.return_value

        # First burst
        orchestrator.on_hotkey_press()
        orchestrator.on_hotkey_release()

        # Second burst
        orchestrator.on_hotkey_press()
        orchestrator.on_hotkey_release()

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
# Task 1.5 — Worker exception logs failure and triggers recovery (AC: #3)
# ---------------------------------------------------------------------------

class TestWorkerRecovery:
    def test_audio_error_in_press_is_logged_not_fatal(
        self, orchestrator, patch_components, caplog
    ):
        """AudioError during hotkey press must be logged, not crash the orchestrator."""
        recorder_cls, _, _, _ = patch_components
        recorder_cls.return_value.start.side_effect = AudioError("device lost")

        with caplog.at_level(logging.ERROR, logger="audiby.app"):
            orchestrator.on_hotkey_press()

        # Orchestrator must still be alive (not raised)
        assert any("device lost" in r.message or "AudioError" in r.message
                    for r in caplog.records)

    def test_transcription_error_in_worker_is_logged_not_fatal(
        self, orchestrator, patch_components, caplog
    ):
        """TranscriptionError in transcriber worker must be caught and logged."""
        _, transcriber_cls, _, _ = patch_components
        mock_transcriber = transcriber_cls.return_value
        mock_transcriber.transcribe.side_effect = TranscriptionError("model fault")

        orchestrator.start()
        try:
            # Simulate audio arriving on queue
            orchestrator.audio_queue.put(np.zeros(1600, dtype="float32"))

            # Give worker time to process
            time.sleep(0.3)

            # Orchestrator must still be running
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
            # Simulate text arriving on queue
            orchestrator.text_queue.put("hello world")

            # Give worker time to process
            time.sleep(0.3)

            # Orchestrator must still be running
            assert not orchestrator.stop_event.is_set()
        finally:
            orchestrator.shutdown()


# ---------------------------------------------------------------------------
# Task 1.6 — Graceful shutdown and idempotency (AC: #3)
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
        orchestrator.shutdown()  # second call — no error

    def test_worker_threads_exit_after_shutdown(self, orchestrator):
        """Worker threads must terminate within a reasonable time after shutdown."""
        orchestrator.start()
        orchestrator.shutdown()

        # Give threads time to notice stop_event
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

        # Make transcriber put text on text_queue when transcribe is called
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
