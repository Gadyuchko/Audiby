"""Application orchestrator — pipeline wiring, thread lifecycle, and startup.

Connects HotkeyManager, AudioRecorder, Transcriber, and TextInjector into
a linear push-to-talk pipeline: hotkey → audio → transcribe → inject.
"""

import logging
import queue
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import Tuple

from audiby.config import Config
from audiby.constants import (
    CONFIG_KEY_ALT_NEUTRALIZATION,
    CONFIG_KEY_HOTKEY,
    CONFIG_KEY_MODEL,
    DEFAULT_ALT_NEUTRALIZATION_STRATEGY,
    DEFAULT_HOTKEY,
    DEFAULT_MODEL_SIZE,
    LOG_BACKUP_COUNT,
    LOG_DIRNAME,
    LOG_FILENAME,
    LOG_FORMAT,
    LOG_LEVEL,
    LOG_MAX_BYTES,
)
from audiby.core import model_manager
from audiby.core.audio_recorder import AudioRecorder
from audiby.core.text_injector import TextInjector
from audiby.core.transcriber import Transcriber
from audiby.platform.hotkey_manager import HotkeyManager

logger = logging.getLogger(__name__)


def run_app(config: Config) -> int:
    """Bootstrap logging, validate model, and run the orchestrator.

    Blocks on stop_event until shutdown is signaled. Guarantees graceful
    cleanup via finally even on unexpected errors.
    """
    log_file = setup_logging(config)
    logger.info(
        "Logging initialized at %s (maxBytes=%s, backupCount=%s)",
        log_file,
        LOG_MAX_BYTES,
        LOG_BACKUP_COUNT,
    )

    # Bail early if the configured model hasn't been downloaded yet
    model_name = config.get(CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE)
    if not model_manager.exists(model_name):
        logger.error("Model '%s' not found", model_name)
        return 1

    app = ApplicationOrchestrator(config)
    try:
        app.start()
        app.stop_event.wait()  # blocks until shutdown is signaled
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Application failed during startup/runtime")
        return 1
    finally:
        app.shutdown()
    return 0


def setup_logging(config: Config) -> Path:
    """Configure root logger with a rotating file handler.

    Reuses an existing handler if one already points at the same log file
    (prevents duplicate handlers across repeated calls).
    """
    log_dir = config.config_dir / LOG_DIRNAME
    log_file = log_dir / LOG_FILENAME

    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()

    file_handler = None

    rotating_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
    for handler in rotating_handlers:
        if Path(handler.baseFilename).resolve() == log_file.resolve():
            file_handler = handler
            break

    if file_handler is None:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(file_handler)

    # Console handler for live terminal output during development
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
               for h in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(console_handler)

    root_logger.setLevel(getattr(logging, LOG_LEVEL))

    return log_file

class ApplicationOrchestrator:
    """Orchestrates the full push-to-talk pipeline lifecycle.

    Wires HotkeyManager, AudioRecorder, Transcriber, and TextInjector
    into a linear data flow connected by thread-safe queues:

        hotkey press → AudioRecorder → audio_queue → Transcriber → text_queue → TextInjector

    Transcriber and Injector each run in dedicated daemon threads that poll
    their respective queues. Call start() from the main thread to launch
    workers and the hotkey listener; call shutdown() to tear everything down.

    """
    _MAX_RECOVERY_ATTEMPTS = 3
    _QUEUE_POLL_TIMEOUT = 0.5  # seconds between stop_event checks in worker loops

    def __init__(self, config: Config) -> None:
        """Compose pipeline components from config and wire shared queues/events."""
        self._audio_queue: Queue = Queue()
        self._text_queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._recording_event = threading.Event()
        self._transcriber_thread: threading.Thread | None = None
        self._injector_thread: threading.Thread | None = None
        self._audio_thread: threading.Thread | None = None

        model_name = config.get(CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE)
        hotkey = config.get(CONFIG_KEY_HOTKEY, DEFAULT_HOTKEY)
        alt_neutralization_strategy = config.get(
            CONFIG_KEY_ALT_NEUTRALIZATION, DEFAULT_ALT_NEUTRALIZATION_STRATEGY
        )
        model_path = model_manager.get_model_root() / model_name
        self._model_path = model_path

        # exponential back off variables
        self._transcriber_failures = 0
        self._injector_failures = 0
        self._audio_failures = 0
        self._backoff_initial = 0.05
        self._backoff_max = 1.0
        self._backoff_factor = 2.0

        # Orchestration parts instantiation
        self._recorder = AudioRecorder(self._audio_queue)
        self._transcriber = Transcriber(model_path, self._audio_queue, self._text_queue)
        self._injector = TextInjector(
            self._text_queue,
            alt_neutralization_strategy=alt_neutralization_strategy,
            hotkey_uses_alt="alt" in hotkey.lower(),
        )
        self._hotkey_manager = HotkeyManager(hotkey, self.on_hotkey_press, self.on_hotkey_release)

    def on_hotkey_press(self) -> None:
        """Signal recording start - called by HotkeyManager on combo press."""
        logger.debug("Hotkey pressed - request recording start")
        self._recording_event.set()

    def on_hotkey_release(self) -> None:
        """Signal recording stop - called by HotkeyManager on combo release.

        Stopping the recorder pushes the captured audio buffer onto audio_queue
        for the transcriber worker to pick up.
        """
        logger.debug("Hotkey released - request recording stop")
        self._recording_event.clear()

    def start(self) -> None:
        """Spawn worker threads and start the hotkey listener."""
        self._transcriber_thread = threading.Thread(
            target=self._transcriber_worker, name="transcriber", daemon=True,
        )
        self._injector_thread = threading.Thread(
            target=self._injector_worker, name="injector", daemon=True,
        )
        self._audio_thread = threading.Thread(
            target=self._audio_worker, name="audio", daemon=True,
        )
        self._audio_thread.start()
        self._transcriber_thread.start()
        self._injector_thread.start()
        self._hotkey_manager.start()
        logger.info("Orchestrator started — pipeline ready")

    def shutdown(self) -> None:
        """Signal all workers to stop and wait for thread cleanup.

        Safe to call multiple times (idempotent).
        """
        self._stop_event.set()
        self._hotkey_manager.stop()
        if self._audio_thread:
            self._audio_thread.join(timeout=2)
        if self._transcriber_thread:
            self._transcriber_thread.join(timeout=2)
        if self._injector_thread:
            self._injector_thread.join(timeout=2)
        logger.info("Orchestrator shut down")

    def _transcriber_worker(self) -> None:
        """
        Handles audio transcription by continuously polling an audio queue, processing audio data,
        and submitting it to a transcription module. Manages retries and recovery for the
        transcriber in case of failures. Operates until a stop event is triggered.

        While the method is running:
          - It retrieves audio data from a queue.
          - Processes the data using a transcription module.
          - Handles exceptions during audio transcription and attempts to recover.

        :return: None
        """
        logger.debug("Transcriber worker started")
        # continuous loop till stop event is set, probing queue for data and processing it
        while not self._stop_event.is_set():
            try:
                audio = self._audio_queue.get(timeout=self._QUEUE_POLL_TIMEOUT)

                # no exception for a timeout window, we got audio -> transcribe
                logger.debug("Transcriber received audio buffer (samples: %d)", len(audio))
                try:
                    self._transcriber.transcribe(audio)

                    # transcription successful, reset backoff
                    self._transcriber_failures = 0
                    logger.debug("Transcription done (text_queue size: %d)", self._text_queue.qsize())
                except Exception as e:
                    logger.error("Transcription failed: %s — %s", type(e).__name__, e)

                    should_retry, self._transcriber_failures = self._schedule_recovery("Transcriber", self._transcriber_failures)
                    if not should_retry:
                        break
                    try:
                        self._transcriber = Transcriber(self._model_path, self._audio_queue, self._text_queue)
                    except Exception as exc:
                        logger.error("Transcriber recovery failed: %s: %s", type(exc).__name__, exc)
            except queue.Empty:
                # nothing in queue -> continue probing
                continue
        logger.debug("Transcriber worker stopped")

    def _injector_worker(self) -> None:
        """Call injector.inject() in a loop — inject() reads from text_queue internally."""
        logger.debug("Injector worker started")
        while not self._stop_event.is_set():
            try:
                self._injector.inject()
            except Exception as e:
                logger.error("Text injection failed: %s — %s", type(e).__name__, e)
            # inject() returns immediately if queue is empty (get_nowait),
            # so sleep briefly to avoid busy-spin
            self._stop_event.wait(timeout=self._QUEUE_POLL_TIMEOUT)
        logger.debug("Injector worker stopped")

    def _audio_worker(self) -> None:
        """
        Handles the audio recording functionalities in a separate worker thread.
        This method manages the lifecycle of audio recording, ensuring it starts
        and stops properly based on event triggers. It also implements recovery
        logic with exponential back off for potential failures during the recording start or stop processes.

        :raises Exception: If audio recording start or stop fails after recovery attempts.
        :raises Exception: If cleanup stop fails during shutdown.
        """
        logger.debug("Audio worker started")
        is_recording = False
        try:
            while not self._stop_event.is_set():
                want_recording = self._recording_event.is_set()
                if want_recording and not is_recording:
                    try:
                        self._recorder.start()
                        is_recording = True
                        self._audio_failures = 0
                        logger.debug("Audio recording started")
                    except Exception as e:
                        logger.error("Audio start failed: %s - %s", type(e).__name__, e)
                        should_retry, self._audio_failures = self._schedule_recovery("Audio", self._audio_failures)
                        if not should_retry:
                            break
                        if not self._recording_event.is_set():
                            self._audio_failures = 0

                elif (not want_recording) and is_recording:
                    try:
                        self._recorder.stop()
                        is_recording = False
                        logger.debug("Audio recording stopped (queue size: %d)", self._audio_queue.qsize())
                    except Exception as e:
                        logger.error("Audio stop failed: %s - %s", type(e).__name__, e)
                        is_recording = False

                self._stop_event.wait(timeout=self._QUEUE_POLL_TIMEOUT)
        finally:
            if is_recording:
                try:
                    self._recorder.stop()
                except Exception as e:
                    logger.exception("Audio cleanup stop failed during shutdown: %s - %s", type(e).__name__, e)
            logger.debug("Audio worker stopped")

    # Read-only accessors for pipeline queues and events.
    @property
    def audio_queue(self):
        return self._audio_queue

    @property
    def text_queue(self):
        return self._text_queue

    @property
    def stop_event(self):
        return self._stop_event

    @property
    def recording_event(self):
        return self._recording_event

    def _schedule_recovery(self, component: str, failures: int) -> Tuple[bool, int]:
        """
        Schedules a recovery attempt for the specified component after a failure, applying
        a backoff strategy based on the number of previous failures. If the maximum number
        of recovery attempts is exceeded, no further retries are scheduled.

        :param component: The name of the component to be recovered.
        :type component: str
        :param failures: The current number of consecutive recovery failures for the component.
        :type failures: int
        :return: A tuple containing a boolean where `True` indicates recovery will continue
                 and `False` indicates recovery attempts have stopped, along with the updated
                 number of failures.
        :rtype: Tuple[bool, int]
        """
        failures += 1
        if failures > self._MAX_RECOVERY_ATTEMPTS:
            logger.critical("%s recovery exceeded max attempts (%d)", component, self._MAX_RECOVERY_ATTEMPTS)
            self._stop_event.set()
            return False, failures

        delay = min(
            self._backoff_max,
            self._backoff_initial * (self._backoff_factor ** failures)
        )
        logger.warning("Retrying %s in %.2fs (failures: %d)", component, delay, failures)
        if self._stop_event.wait(delay):
            return False, failures
        return True, failures
