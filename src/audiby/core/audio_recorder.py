"""Audio capture module — wraps sounddevice for the Audiby recording pipeline."""
import logging
import queue
import threading

import numpy as np
import sounddevice as sd

from audiby.constants import DEFAULT_SAMPLE_RATE
from audiby.exceptions import AudioError

logger = logging.getLogger(__name__)


class AudioRecorder:
    """Records audio from the selected input device using sounddevice.

    Manages recording lifecycle and delivers a float32 mono numpy buffer
    to the transcription queue on stop.

    """

    MAX_DURATION_SAMPLES = DEFAULT_SAMPLE_RATE * 120  # 2 min cap

    def __init__(self, audio_queue: queue.Queue, device_id: int | None = None):
        self._audio_queue = audio_queue
        self._device_id = device_id
        self._recording = threading.Event()
        self._chunks: list[np.ndarray] = []
        self._accumulated_samples = 0  # running counter — avoids O(n) sum on every callback
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        """Open sounddevice InputStream and begin capturing audio."""
        if self._recording.is_set():
            return

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
            raise AudioError(f"Could not open audio device: {err}") from err

        self._recording.set()
        try:
            self._stream.start()
        except sd.PortAudioError as err:
            self._recording.clear()
            try:
                self._stream.close()
            finally:
                self._stream = None
            logger.error("Could not start audio stream on device %s: %s", self._device_id, err)
            raise AudioError(f"Could not start audio stream: {err}") from err
        logger.info("Recording started (device=%s)", self._device_id)

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        """Accumulate incoming audio chunks up to the max duration cap."""
        if not self._recording.is_set():
            return
        if status:
            logger.warning("Audio stream status (device=%s): %s", self._device_id, status)
        if self._accumulated_samples >= self.MAX_DURATION_SAMPLES:
            return  # cap reached, discard further input

        # Trim the chunk so the buffer never exceeds the cap
        remaining = self.MAX_DURATION_SAMPLES - self._accumulated_samples
        chunk = indata[:remaining].copy()  # sounddevice reuses the buffer — must copy
        self._chunks.append(chunk)
        self._accumulated_samples += len(chunk)

    def stop(self) -> None:
        """Stop recording, close the stream, and push audio buffer to queue."""
        self._recording.clear()

        if self._stream is not None:
            stream = self._stream
            self._stream = None
            try:
                stream.stop()
                stream.close()
            except sd.PortAudioError as err:
                logger.error("Could not stop audio stream on device %s: %s", self._device_id, err)
                self._chunks = []
                self._accumulated_samples = 0
                raise AudioError(f"Could not stop audio stream: {err}") from err

        if self._chunks:
            audio = np.concatenate(self._chunks).flatten()
            self._audio_queue.put(audio)
            logger.info(
                "Recording stopped (samples=%d, device=%s)",
                len(audio),
                self._device_id,
            )

        self._chunks = []
        self._accumulated_samples = 0
