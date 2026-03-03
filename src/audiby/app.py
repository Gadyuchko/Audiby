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

from audiby.config import Config
from audiby.constants import (
    CONFIG_KEY_HOTKEY,
    CONFIG_KEY_MODEL,
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


def run_app(config: Config) -> None:
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
        return

    app = ApplicationOrchestrator(config)
    try:
        app.start()
        app.stop_event.wait()  # blocks until shutdown is signaled
    finally:
        app.shutdown()


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

    _QUEUE_POLL_TIMEOUT = 0.5  # seconds between stop_event checks in worker loops

    def __init__(self, config: Config) -> None:
        """Compose pipeline components from config and wire shared queues/events."""
        self._audio_queue: Queue = Queue()
        self._text_queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._recording_event = threading.Event()
        self._transcriber_thread: threading.Thread | None = None
        self._injector_thread: threading.Thread | None = None

        model_name = config.get(CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE)
        hotkey = config.get(CONFIG_KEY_HOTKEY, DEFAULT_HOTKEY)
        model_path = model_manager.get_model_root() / model_name

        self._recorder = AudioRecorder(self._audio_queue)
        self._transcriber = Transcriber(model_path, self._audio_queue, self._text_queue)
        self._injector = TextInjector(self._text_queue)
        self._hotkey_manager = HotkeyManager(hotkey, self.on_hotkey_press, self.on_hotkey_release)

    def on_hotkey_press(self) -> None:
        """Signal recording start — called by HotkeyManager on combo press."""
        try:
            self._recording_event.set()
            self._recorder.start()
        except Exception as e:
            logger.error("Failed to start recording: %s", e)
            self._recording_event.clear()

    def on_hotkey_release(self) -> None:
        """Signal recording stop — called by HotkeyManager on combo release.

        Stopping the recorder pushes the captured audio buffer onto audio_queue
        for the transcriber worker to pick up.
        """
        try:
            self._recording_event.clear()
            self._recorder.stop()
        except Exception as e:
            logger.error("Failed to stop recording: %s", e)

    def start(self) -> None:
        """Spawn worker threads and start the hotkey listener."""
        self._transcriber_thread = threading.Thread(
            target=self._transcriber_worker, name="transcriber", daemon=True,
        )
        self._injector_thread = threading.Thread(
            target=self._injector_worker, name="injector", daemon=True,
        )
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
        if self._transcriber_thread:
            self._transcriber_thread.join(timeout=2)
        if self._injector_thread:
            self._injector_thread.join(timeout=2)
        logger.info("Orchestrator shut down")

    def _transcriber_worker(self) -> None:
        """Poll audio_queue and transcribe each buffer until stop_event is set."""
        # continuous loop till stop event is set, probing queue for data and processing it
        while not self._stop_event.is_set():
            try:
                audio = self._audio_queue.get(timeout=self._QUEUE_POLL_TIMEOUT)

                # no exception for a timeout window, we got audio -> transcribe
                try:
                    self._transcriber.transcribe(audio)
                except Exception as e:
                    logger.error("Transcription failed: %s", type(e).__name__)

            except queue.Empty:
                # nothing in queue -> continue probing
                continue

    def _injector_worker(self) -> None:
        """Poll text_queue and inject each text payload until stop_event is set."""
        # continuous loop till stop event is set, probing queue for data and processing it
        while not self._stop_event.is_set():
            try:
                self._text_queue.get(timeout=self._QUEUE_POLL_TIMEOUT)

                # no exception for a timeout window, we have text to inject try injecting
                try:
                    self._injector.inject()
                except Exception as e:
                    logger.error("Text injection failed: %s", type(e).__name__)

            except queue.Empty:
                # nothing in queue -> continue probing
                continue

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
