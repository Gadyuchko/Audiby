"""Application orchestrator — pipeline wiring, thread lifecycle, and startup.

Connects HotkeyManager, AudioRecorder, Transcriber, and TextInjector into
a linear push-to-talk pipeline: hotkey → audio → transcribe → inject.
"""

import logging
import queue
import sys
import threading
import gc
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import Tuple, Any

from audiby.exceptions import HotkeyError
from audiby.platform.shell import get_shell
from audiby.ui.download_dialog import DownloadDialog
from audiby.ui.settings_window import SettingsWindow
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
    LOG_MAX_BYTES, CONFIG_KEY_AUTOSTART,
)
from audiby.core import model_manager
from audiby.core.audio_recorder import AudioRecorder
from audiby.core.text_injector import TextInjector
from audiby.core.transcriber import Transcriber
from audiby.platform.hotkey_manager import get_hotkey_manager
from audiby.platform.macos_permissions import ensure_mac_input_permissions
from audiby.ui.tray import TrayController
from audiby.platform.autostart import get_autostart

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

    model_name = config.get(CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE)
    if not model_manager.exists(model_name):
        logger.warning("Model '%s' not found locally; prompting for download", model_name)
        if not _ensure_startup_model_available(model_name):
            logger.error("Startup aborted because model '%s' is still unavailable", model_name)
            return 1

    app = ApplicationOrchestrator(config)
    try:
        app.start()
        app.start_tray()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception:
        logger.exception("Application failed during startup/runtime")
        return 1
    finally:
        app.shutdown()
    return 0


def _ensure_startup_model_available(model_name: str) -> bool:
    """Prompt for a missing startup model download before orchestrator boot."""
    result = DownloadDialog(model_name).run()
    return result.status == "success"


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
        self._config = config
        self._audio_queue: Queue = Queue()
        self._text_queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._recording_event = threading.Event()
        self._audio_control_event = threading.Event()
        # Re-entrant because model-switch helpers may touch the same shared transcriber
        # state while another locked path is already in progress on this thread.
        self._transcriber_lock = threading.RLock()
        self._transcriber_thread: threading.Thread | None = None
        self._injector_thread: threading.Thread | None = None
        self._audio_thread: threading.Thread | None = None

        model_name = config.get(CONFIG_KEY_MODEL, DEFAULT_MODEL_SIZE)
        self._hotkey = config.get(CONFIG_KEY_HOTKEY, DEFAULT_HOTKEY)
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
            hotkey_uses_alt="alt" in self._hotkey.lower(),
        )
        self._hotkey_manager = get_hotkey_manager(self._hotkey, self.on_hotkey_press, self.on_hotkey_release)

        log_path = config.config_dir / LOG_DIRNAME
        self._settings_win = SettingsWindow(config, self.apply_settings)
        self._tray_controller = TrayController(
            on_settings=self._on_tray_settings,
            on_open_log_folder=lambda: self._on_tray_open_logs_folder(log_path),
            on_quit=self._on_tray_quit
        )

    def on_hotkey_press(self) -> None:
        """Signal recording start - called by HotkeyManager on combo press."""
        logger.debug("Hotkey pressed - request recording start")
        self._recording_event.set()
        self._audio_control_event.set()

    def on_hotkey_release(self) -> None:
        """Signal recording stop - called by HotkeyManager on combo release.

        Stopping the recorder pushes the captured audio buffer onto audio_queue
        for the transcriber worker to pick up.
        """
        logger.debug("Hotkey released - request recording stop")
        self._recording_event.clear()
        self._audio_control_event.set()

    def start(self) -> None:
        """Spawn worker threads and start the hotkey listener."""
        ensure_mac_input_permissions()
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
        self._audio_control_event.set()
        self._hotkey_manager.stop()
        try:
            self._tray_controller.stop()
        except Exception as exc:
            logger.warning("Tray stop failed during shutdown: %s: %s", type(exc).__name__, exc)
        try:
            self._settings_win.destroy()
        except Exception as exc:
            logger.warning("Settings window cleanup failed during shutdown: %s: %s", type(exc).__name__, exc)
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
                    with self._transcriber_lock:
                        transcriber = self._transcriber
                    if transcriber is None:
                        logger.warning("Transcriber unavailable during model switch; dropping audio buffer")
                        continue
                    transcriber.transcribe(audio)

                    # transcription successful, reset backoff
                    self._transcriber_failures = 0
                    logger.debug("Transcription done (text_queue size: %d)", self._text_queue.qsize())
                except Exception as e:
                    logger.error("Transcription failed: %s — %s", type(e).__name__, e)

                    should_retry, self._transcriber_failures = self._schedule_recovery("Transcriber", self._transcriber_failures)
                    if not should_retry:
                        break
                    try:
                        with self._transcriber_lock:
                            self._transcriber = Transcriber(
                                self._model_path,
                                self._audio_queue,
                                self._text_queue,
                            )
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

        Lifecycle summary for maintainers:
        - Worker primes the recorder stream once at startup. This removes device
          startup latency that can clip first words on short hotkey presses.
        - While hotkey is not active, recorder keeps only a small rolling pre-roll
          window (bounded memory) inside AudioRecorder.
        - On hotkey press/release we only toggle intent (`_recording_event`);
          this worker performs actual `start()` / `stop()` calls.
        - Stream is fully released via `recorder.close()` in worker shutdown.

        :raises Exception: If audio recording start or stop fails after recovery attempts.
        :raises Exception: If cleanup stop fails during shutdown.
        """
        logger.debug("Audio worker started")
        is_recording = False
        try:
            # Prime stream once so short utterances are not clipped by device startup latency.
            while not self._stop_event.is_set():
                try:
                    self._recorder.prime()
                    self._audio_failures = 0
                    break
                except Exception as e:
                    logger.error("Audio prime failed: %s - %s", type(e).__name__, e)
                    should_retry, self._audio_failures = self._schedule_recovery("Audio", self._audio_failures)
                    if not should_retry:
                        return

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

                self._audio_control_event.wait(timeout=self._QUEUE_POLL_TIMEOUT)
                self._audio_control_event.clear()
        finally:
            if is_recording:
                try:
                    self._recorder.stop()
                except Exception as e:
                    logger.exception("Audio cleanup stop failed during shutdown: %s - %s", type(e).__name__, e)
            try:
                self._recorder.close()
            except Exception as e:
                logger.exception("Audio stream close failed during shutdown: %s - %s", type(e).__name__, e)
            logger.debug("Audio worker stopped")

    def _on_tray_settings(self) ->None:
        try:
            self._settings_win.show()
        except Exception as e:
            logger.error("Failed to show settings window: %s", e)

    def _on_tray_quit(self) -> None:
        self.shutdown()

    def _on_tray_open_logs_folder(self, path: Path) -> Any:
        _shell = get_shell()

        try:
            _shell.open_folder(path)
        except Exception as e:
            logger.error("Failed to open logs folder: %s", e)

    def apply_settings(self, hotkey: str, autostart: bool, model: str) -> str | None:
        """
        Applies settings such as the hotkey, autostart preference, and model configuration. This method validates
        the provided settings and updates the internal configuration. If any errors occur during validation or
        application of the settings, an error message is accumulated and returned. The configuration
        is flushed to disc in any case to preserve whatever changes were made.

        :param hotkey: The new hotkey to be set.
        :type hotkey: str
        :param autostart: A boolean value indicating whether the application should start automatically.
        :type autostart: bool
        :param model: The name of the model to be applied.
        :type model: str
        :return: An error message if any validation checks fail; otherwise, None.
        :rtype: str | None
        """
        errors_message = ""

        hotkey_error = self.reinitialize_hotkey(hotkey)
        if hotkey_error:
            errors_message += hotkey_error + "\n"
        else:
            self._config.set(CONFIG_KEY_HOTKEY, hotkey)

        model_error = self.set_model(model)
        if model_error:
            errors_message += model_error + "\n"
        else:
            self._config.set(CONFIG_KEY_MODEL, model)

        autostart_error = self.set_autostart(autostart)
        if autostart_error:
            errors_message += autostart_error
        else:
            self._config.set(CONFIG_KEY_AUTOSTART, autostart)

        has_successful_change = not hotkey_error or not model_error or not autostart_error
        if has_successful_change:
            self._config.save()

        if errors_message:
            return errors_message
        return None

    def set_model(self, model: str) -> str | None:
        """
        Sets the transcription model for the application. If the given model is already set,
        no changes are made. If the model does not exist locally, it attempts to download it, showing the blocking dialog.
        The method initializes the transcriber with the specified model in case of success and sets config value in mem, and in case of
        failure, reverts to the previous transcriber.

        :param model: Name of the transcription model to be set.
        :type model: str
        :return: A message indicating failure to download or initialize the model, or None if
                 the operation is successful.
        :rtype: str | None
        """
        old_model = self._config.get(CONFIG_KEY_MODEL)
        if old_model == model:
            return None

        if not model_manager.exists(model):
            return f"Model {model} is not downloaded."

        old_model_path = self._model_path
        model_path = model_manager.get_model_root() / model
        self._release_transcriber()
        try:
            new_transcriber = Transcriber(model_path, self._audio_queue, self._text_queue)
        except Exception as e:
            logger.error("Failed to initialize transcriber: %s", e)
            self._restore_transcriber(old_model_path)
            return f"Failed to initialize {model} model. Falling back to old one."
        with self._transcriber_lock:
            self._model_path = model_path
            self._transcriber = new_transcriber
        return None

    def _release_transcriber(self) -> None:
        """Release the current transcriber before loading a replacement model."""
        with self._transcriber_lock:
            current = self._transcriber
            self._transcriber = None
        if current is not None:
            del current
            # Force cleanup before loading another model so we do not keep two large
            # Whisper models in memory during a model switch.
            gc.collect()

    def _restore_transcriber(self, model_path: Path) -> None:
        """Best-effort restoration of the previous transcriber after a failed swap."""
        try:
            restored = Transcriber(model_path, self._audio_queue, self._text_queue)
        except Exception as exc:
            logger.critical("Failed to restore previous transcriber: %s: %s", type(exc).__name__, exc)
            with self._transcriber_lock:
                self._model_path = model_path
                self._transcriber = None
            return
        with self._transcriber_lock:
            self._model_path = model_path
            self._transcriber = restored

    def set_autostart(self, autostart: bool) -> str | None:
        """
        Sets the autostart setting for the application, enabling or disabling it
        as specified. If the new value is the same as the current one, no action
        is performed.

        :param autostart: The new autostart setting. If True, enables autostart;
            if False, disables autostart.
        :type autostart: bool
        :return: A message indicating failure if the autostart setting could not
            be changed, or None if it was successfully changed or already matched
            the existing value.
        :rtype: str | None
        """
        old_value = self._config.get(CONFIG_KEY_AUTOSTART)
        if old_value == autostart:
            return None
        # try to set new value
        try:
           autostart_settings = get_autostart()
           if autostart:
               autostart_settings.enable(sys.executable)
           else:
               autostart_settings.disable()
           logger.info("Autostart set to %s",autostart)
        except Exception as e:
            logger.error("Failed to set autostart: %s", e)
            return f"Failed to set autostart to {'enabled' if autostart else 'disabled'}."

    def reinitialize_hotkey(self, hotkey: str) -> str | None:
        """
        Reinitializes the hotkey, attempting to set a new hotkey combination and handle fallback
        scenarios gracefully in case of failure.

        This method stops the currently active hotkey manager, tries to create a new hotkey manager
        with the provided hotkey combination, and reactivates it. In case of an error during the
        process, it logs the error, restores the previous hotkey, and ensures the application can
        recover from the failure.

        :param hotkey: A string representing the new hotkey combination to set.
        :return: A string message detailing the outcome of the reinitialization attempt, or None in
            case of success.
        """
        new_combo = hotkey
        old_hotkey = self._hotkey
        self._hotkey_manager.stop()

        try:
            self._hotkey_manager = get_hotkey_manager(new_combo, self.on_hotkey_press, self.on_hotkey_release)
            self._hotkey_manager.start()
            self._hotkey = new_combo
            self._injector._hotkey_uses_alt = "alt" in new_combo.lower()
            logger.debug("Updated injector hotkey_uses_alt=%s", self._injector._hotkey_uses_alt)
        except HotkeyError as e:
            logger.error("Failed to reinitialize hotkey: %s, falling back to old hotkey %s. Error: %s", new_combo, old_hotkey, e)
            self._hotkey_manager = get_hotkey_manager(old_hotkey, self.on_hotkey_press, self.on_hotkey_release)
            self._hotkey_manager.start()
            self._config.set(CONFIG_KEY_HOTKEY, old_hotkey)
            return f"Failed to reinitialize hotkey to {new_combo}. Falling back to old hotkey {old_hotkey}."
        except Exception as e:
            logger.error("Unexpected error reinitializing hotkey %s: %s — %s", new_combo, type(e).__name__, e)

            try:
                self._hotkey_manager = get_hotkey_manager(old_hotkey, self.on_hotkey_press, self.on_hotkey_release)
                self._hotkey_manager.start()
                self._config.set(CONFIG_KEY_HOTKEY, old_hotkey)
                return f"Failed to reinitialize hotkey to {new_combo}. Fell back to old hotkey {old_hotkey}."
            except Exception as restore_exc:
                logger.error("Failed to restore hotkey manager: %s", restore_exc)
                self._config.set(CONFIG_KEY_HOTKEY, old_hotkey)
                return f"Failed to restore hotkey manager to {old_hotkey}."



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

    def start_tray(self):
        self._tray_controller.start()

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
