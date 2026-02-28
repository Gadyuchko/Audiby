"""Transcriber — queue-driven speech-to-text using faster-whisper.

Loads a single WhisperModel instance and reuses it across transcriptions.
Logs operational metadata only — never raw transcript text.
"""

import logging
from pathlib import Path
from queue import Queue

import ctranslate2
import numpy as np
from faster_whisper import WhisperModel

from audiby.constants import TRANSCRIPTION_BEAM_SIZE, TRANSCRIPTION_DEVICE_AUTO
from audiby.exceptions import ModelError, TranscriptionError

logger = logging.getLogger(__name__)


class Transcriber:
    """Receives audio from the audio queue and transcribes it to text with a Faster Whisper model.

    Loads one WhisperModel instance at init and reuses it across transcriptions.
    Normalizes segment text and pushes non-empty results to the injection queue.

    @author Roman Hadiuchko
    """

    def __init__(
        self,
        model_path: Path,
        audio_queue: Queue,
        text_queue: Queue,
        device_mode: str = TRANSCRIPTION_DEVICE_AUTO,
    ) -> None:
        device, compute_type = self._resolve_device_config(device_mode)
        try:
            self._model = WhisperModel(model_path, device=device, compute_type=compute_type)
        except Exception as exc:
            if device_mode == "auto" and device == "cuda":
                # Auto mode: CUDA failed, fall back to CPU
                logger.warning("CUDA load failed, falling back to CPU: %s", exc)
                try:
                    self._model = WhisperModel(model_path, device="cpu", compute_type="int8")
                except Exception as fallback_exc:
                    raise ModelError(f"CPU fallback also failed: {fallback_exc}") from fallback_exc
            else:
                raise ModelError(f"Failed to load model: {exc}") from exc
        logger.info("Model loaded successfully: %s", model_path)
        self._audio_queue = audio_queue
        self._text_queue = text_queue

    def transcribe(self, audio: np.ndarray) -> None:
        """Validate audio buffer, transcribe, normalize text, and push to text queue."""
        if not isinstance(audio, np.ndarray) or audio.dtype != np.float32:
            raise TranscriptionError(
                f"Expected float32 numpy array, got {type(audio).__name__}"
                + (f" ({audio.dtype})" if hasattr(audio, "dtype") else "")
            )
        if audio.ndim != 1:
            raise TranscriptionError(
                f"Expected 1-D mono buffer, got {audio.ndim}-D shape {audio.shape}"
            )

        try:
            segments, info = self._model.transcribe(audio, beam_size=TRANSCRIPTION_BEAM_SIZE)
            # Join with "" to preserve words split across segment boundaries.
            raw = "".join(seg.text for seg in segments)
        except TranscriptionError:
            raise
        except Exception as exc:
            logger.error("Transcription failed: %s", type(exc).__name__)
            raise TranscriptionError(f"Transcription failed: {exc}") from exc

        text = " ".join(raw.split())
        if text:
            self._text_queue.put(text)
        logger.info("Transcription completed, text length: %d", len(text))

    @staticmethod
    def _resolve_device_config(device_mode: str) -> tuple[str, str]:
        """Return (device, compute_type) based on policy and GPU availability."""
        match device_mode:
            case "auto":
                if ctranslate2.get_cuda_device_count() > 0:
                    return "cuda", "float16"
                return "cpu", "int8"
            case "cpu":
                return "cpu", "int8"
            case "cuda":
                if ctranslate2.get_cuda_device_count() == 0:
                    raise ModelError("CUDA required but no compatible GPU found")
                return "cuda", "float16"
            case _:
                raise ModelError(f"Invalid device mode: {device_mode}")
