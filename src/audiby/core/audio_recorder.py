"""Audio capture module - wraps sounddevice for the Audiby recording pipeline."""
import logging
import queue
import threading
from collections import deque

import numpy as np
import sounddevice as sd

from audiby.constants import DEFAULT_SAMPLE_RATE
from audiby.exceptions import AudioDeviceError, AudioError, MicPermissionError

logger = logging.getLogger(__name__)


_MIC_PERMISSION_MARKERS = (
    "access denied",
    "permission denied",
    "permissions denied",
    "not authorized",
    "unauthorized",
    "privacy",
    "microphone permission",
)


def _is_microphone_permission_error(error: sd.PortAudioError) -> bool:
    """Return True when a PortAudio error looks like OS microphone denial."""
    message = str(error).lower()
    return any(marker in message for marker in _MIC_PERMISSION_MARKERS)


def _audio_open_exception(message: str, error: sd.PortAudioError) -> AudioError:
    """Map low-level PortAudio open/start failures to user-actionable errors."""
    if _is_microphone_permission_error(error):
        return MicPermissionError(message)
    return AudioDeviceError(message)


class AudioRecorder:
    """Records audio from the selected input device using sounddevice.

    Buffer model:
    - `_pre_roll_chunks` (deque): rolling short idle window (default 300 ms).
      This covers press/start latency so the first spoken word is not clipped.
    - `_chunks` (list): active session buffer while recording is ON.
      This is what gets emitted to `audio_queue` on `stop()`.
    - `_accumulated_samples`: counter for `_chunks` only, used to enforce
      `MAX_DURATION_SAMPLES` without repeatedly summing chunk lengths.

    Privacy/memory behavior:
    - After `prime()`, the pre-roll buffer updates continuously while the app runs.
      It does not grow over time: it always keeps only the latest short window
      (old chunks are overwritten/dropped as new chunks arrive).
    - Full session audio is retained only while recording is active, then cleared
      right after `stop()` pushes to the queue.
    """

    MAX_DURATION_SAMPLES = DEFAULT_SAMPLE_RATE * 120  # 2 min cap
    PRE_ROLL_MS = 300

    def __init__(self, audio_queue: queue.Queue, device_id: int | None = None):
        self._audio_queue = audio_queue
        self._device_id = device_id
        self._recording = threading.Event()
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._accumulated_samples = 0  # running counter - avoids O(n) sum on every callback
        self._pre_roll_chunks: deque[np.ndarray] = deque()
        self._pre_roll_samples = 0
        self._pre_roll_max_samples = int(DEFAULT_SAMPLE_RATE * self.PRE_ROLL_MS / 1000)
        self._stream: sd.InputStream | None = None

    def _open_and_start_stream(self) -> None:
        try:
            self._stream = sd.InputStream(
                samplerate=DEFAULT_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self._device_id,
                callback=self._callback,
            )
        except sd.PortAudioError as err:
            logger.error("Could not open audio device %s: %s", self._device_id, err)
            raise _audio_open_exception(f"Could not open audio device: {err}", err) from err

        try:
            self._stream.start()
        except sd.PortAudioError as err:
            try:
                self._stream.close()
            finally:
                self._stream = None
            logger.error("Could not start audio stream on device %s: %s", self._device_id, err)
            raise _audio_open_exception(f"Could not start audio stream: {err}", err) from err

    def prime(self) -> None:
        """Open/start stream ahead of first burst to remove device startup lag."""
        if self._stream is not None:
            return
        self._open_and_start_stream()
        logger.debug("Audio stream primed (device=%s)", self._device_id)

    def start(self) -> None:
        """Begin a new recording session, seeded with current pre-roll window."""
        if self._recording.is_set():
            return
        if self._stream is None:
            self._open_and_start_stream()

        with self._lock:
            self._chunks = []
            self._accumulated_samples = 0
            for chunk in self._pre_roll_chunks:
                remaining = self.MAX_DURATION_SAMPLES - self._accumulated_samples
                if remaining <= 0:
                    break
                seeded = chunk[:remaining].copy()
                self._chunks.append(seeded)
                self._accumulated_samples += len(seeded)

        self._recording.set()
        logger.info("Recording started (device=%s)", self._device_id)

    def _append_pre_roll(self, chunk: np.ndarray) -> None:
        """Add idle chunk to rolling pre-roll window and evict oldest overflow."""
        self._pre_roll_chunks.append(chunk)
        self._pre_roll_samples += len(chunk)
        while self._pre_roll_samples > self._pre_roll_max_samples and self._pre_roll_chunks:
            removed = self._pre_roll_chunks.popleft()
            self._pre_roll_samples -= len(removed)

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        """Route callback audio to idle pre-roll or active session buffer."""
        if status:
            logger.warning("Audio stream status (device=%s): %s", self._device_id, status)

        chunk = indata.copy()  # sounddevice reuses the buffer - must copy
        with self._lock:
            if not self._recording.is_set():
                self._append_pre_roll(chunk)
                return
            if self._accumulated_samples >= self.MAX_DURATION_SAMPLES:
                return  # cap reached, discard further input

            # Trim the chunk so the buffer never exceeds the cap
            remaining = self.MAX_DURATION_SAMPLES - self._accumulated_samples
            bounded = chunk[:remaining]
            self._chunks.append(bounded)
            self._accumulated_samples += len(bounded)

    def stop(self) -> None:
        """Finish current session and queue it; keep stream open for next burst."""
        self._recording.clear()

        with self._lock:
            if self._chunks:
                audio = np.concatenate(self._chunks).flatten()
            else:
                audio = None
            self._chunks = []
            self._accumulated_samples = 0

        if audio is not None:
            self._audio_queue.put(audio)
            logger.info(
                "Recording stopped (samples=%d, device=%s)",
                len(audio),
                self._device_id,
            )

    def close(self) -> None:
        """Fully release audio device (called during orchestrator shutdown)."""
        self._recording.clear()
        if self._stream is None:
            return

        stream = self._stream
        self._stream = None
        try:
            stream.stop()
            stream.close()
        except sd.PortAudioError as err:
            logger.error("Could not stop audio stream on device %s: %s", self._device_id, err)
            raise AudioError(f"Could not stop audio stream: {err}") from err
