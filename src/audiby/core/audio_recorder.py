"""Audio capture module - wraps sounddevice for the Audiby recording pipeline."""
import logging
import queue
import threading
from collections import deque
from typing import NamedTuple

import numpy as np
import sounddevice as sd

from audiby.constants import AUDIO_DEVICE_AUTO_LABEL, DEFAULT_SAMPLE_RATE
from audiby.exceptions import AudioDeviceError, AudioError, MicPermissionError

logger = logging.getLogger(__name__)


class AudioInputDevice(NamedTuple):
    """One selectable capture device. `device_id=None` means follow OS default."""

    device_id: int | None
    label: str


# Windows exposes the same physical microphone once per host API (MME,
# DirectSound, WASAPI, WDM-KS) and MME truncates names at 31 chars, so exact
# name matching cannot collapse the duplicates. Comparing a normalized prefix
# groups "Microphone (Razer BlackShark V2" with the full WASAPI name.
_DEDUPE_KEY_LENGTH = 24

# Host-API aliases that merely re-point at whatever the OS default is. They
# would duplicate the explicit "System default" entry, so they are hidden.
_DEFAULT_ALIAS_PREFIXES = (
    "microsoft sound mapper",
    "primary sound capture driver",
)


def _clean_label(name: str) -> str:
    """Collapse whitespace - some driver names embed CR/LF and break the picker."""
    return " ".join(name.split())


def _dedupe_key(name: str) -> str:
    """Reduce a device name to a prefix key that survives MME truncation."""
    normalized = "".join(char for char in name.lower() if char.isalnum())
    return normalized[:_DEDUPE_KEY_LENGTH]


def _is_default_alias(name: str) -> bool:
    """Return True for pseudo-devices that just forward to the OS default."""
    lowered = name.strip().lower()
    return lowered.startswith(_DEFAULT_ALIAS_PREFIXES)


def _supports_capture_format(device_id: int) -> bool:
    """Return True if the device accepts the format the recorder opens with.

    Windows exposes WDM-KS kernel-streaming endpoints that advertise input
    channels but reject 16 kHz mono float32. Listing them hands the user
    choices that fail on selection with PaErrorCode -9996/-9997, so they are
    validated up front against the very settings `_open_and_start_stream` uses.
    """
    try:
        sd.check_input_settings(
            device=device_id,
            samplerate=DEFAULT_SAMPLE_RATE,
            channels=1,
            dtype="float32",
        )
    except Exception:
        return False
    return True


def list_input_devices() -> list[AudioInputDevice]:
    """Enumerate selectable capture devices, one row per physical microphone.

    The first entry is always the OS-default sentinel (`device_id=None`).
    Never raises - on enumeration failure the caller still gets the default
    entry so the settings picker stays usable.
    """
    devices = [AudioInputDevice(None, AUDIO_DEVICE_AUTO_LABEL)]
    try:
        queried = sd.query_devices()
        default_hostapi = sd.default.hostapi
    except Exception as err:
        logger.error("Could not enumerate audio input devices: %s", err)
        return devices

    # Collapse per-host-API duplicates: keep an id on the default host API when
    # one exists, and keep the longest name variant as the display label.
    collapsed: dict[str, tuple[int, str, bool]] = {}
    for index, info in enumerate(queried):
        if info.get("max_input_channels", 0) < 1:
            continue
        name = _clean_label(info.get("name") or "")
        if not name or _is_default_alias(name):
            continue

        if not _supports_capture_format(index):
            logger.debug("Skipping device %d (%s): unsupported capture format", index, name)
            continue

        on_default_api = info.get("hostapi") == default_hostapi
        key = _dedupe_key(name)
        existing = collapsed.get(key)
        if existing is None:
            collapsed[key] = (index, name, on_default_api)
            continue

        existing_id, existing_label, existing_on_default = existing
        collapsed[key] = (
            index if on_default_api and not existing_on_default else existing_id,
            name if len(name) > len(existing_label) else existing_label,
            existing_on_default or on_default_api,
        )

    for device_id, label, _ in sorted(collapsed.values(), key=lambda entry: entry[0]):
        devices.append(AudioInputDevice(device_id, label))
    return devices


def describe_device(device_id: int | None) -> str:
    """Resolve a log-friendly name for a device id, including the OS default."""
    if device_id is None:
        try:
            resolved = sd.default.device[0]
            name = sd.query_devices(resolved)["name"]
        except Exception:
            return f"{AUDIO_DEVICE_AUTO_LABEL} (unresolved)"
        return f"{AUDIO_DEVICE_AUTO_LABEL} -> {name} (index {resolved})"
    try:
        return f"{sd.query_devices(device_id)['name']} (index {device_id})"
    except Exception:
        return f"unknown device (index {device_id})"


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
        # Tracks whether a warm stream is wanted. Distinct from `_stream is not
        # None`, which is also False after a failed open - in that case the
        # stream must still be reopened, not left cold until the next press.
        self._prime_requested = False

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
        self._prime_requested = True
        if self._stream is not None:
            return
        self._open_and_start_stream()
        logger.info("Audio stream primed on %s", describe_device(self._device_id))

    def set_device(self, device_id: int | None) -> None:
        """Switch capture device, reopening the stream so the change takes effect.

        The stream is opened once at startup and reused, so simply updating the
        id would leave capture pinned to the previously opened device.
        """
        if device_id == self._device_id:
            return

        logger.info(
            "Switching audio device: %s -> %s",
            describe_device(self._device_id),
            describe_device(device_id),
        )
        should_prime = self._prime_requested
        self._close_stream()

        # Stale pre-roll belongs to the previous device - drop it.
        with self._lock:
            self._pre_roll_chunks.clear()
            self._pre_roll_samples = 0

        self._device_id = device_id
        if should_prime:
            self.prime()

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
        self._prime_requested = False
        self._close_stream()

    def _close_stream(self) -> None:
        """Tear down the stream while leaving the prime intent untouched."""
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
