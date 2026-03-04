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

    """

    def __init__(
        self,
        model_path: Path,
        audio_queue: Queue,
        text_queue: Queue,
        device_mode: str = TRANSCRIPTION_DEVICE_AUTO,
    ) -> None:
        self._model_path = Path(model_path)
        self._device_mode = device_mode
        self._runtime_cpu_fallback_attempted = False
        device, compute_type = self._resolve_device_config(device_mode)
        try:
            self._model = WhisperModel(str(model_path), device=device, compute_type=compute_type)
        except Exception as exc:
            if device_mode == "auto" and device == "cuda":
                # Auto mode: CUDA failed, fall back to CPU
                logger.warning("CUDA load failed, falling back to CPU: %s", exc)
                try:
                    self._model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
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
            if self._should_runtime_fallback_to_cpu(exc):
                logger.warning(
                    "CUDA runtime unavailable (%s). Falling back to CPU for transcription. "
                    "Check CUDA/cuBLAS runtime installation (for example missing cublas64_12.dll) "
                    "if GPU acceleration is expected.",
                    type(exc).__name__,
                )
                self._fallback_model_to_cpu()
                try:
                    segments, info = self._model.transcribe(audio, beam_size=TRANSCRIPTION_BEAM_SIZE)
                    raw = "".join(seg.text for seg in segments)
                except Exception as retry_exc:
                    logger.error("Transcription failed after CPU fallback: %s", type(retry_exc).__name__)
                    raise TranscriptionError(f"Transcription failed: {retry_exc}") from retry_exc
            else:
                logger.error("Transcription failed: %s", type(exc).__name__)
                raise TranscriptionError(f"Transcription failed: {exc}") from exc

        text = " ".join(raw.split())
        if text:
            self._text_queue.put(text)
        logger.info("Transcription completed, text length: %d", len(text))

    def _fallback_model_to_cpu(self) -> None:
        """Switch model instance to CPU once after CUDA runtime failure in auto mode."""
        try:
            self._model = WhisperModel(str(self._model_path), device="cpu", compute_type="int8")
            self._runtime_cpu_fallback_attempted = True
            logger.info("Runtime fallback to CPU model succeeded")
        except Exception as exc:
            raise TranscriptionError(f"CPU fallback failed: {exc}") from exc

    def _should_runtime_fallback_to_cpu(self, exc: Exception) -> bool:
        """Return True if this looks like CUDA runtime missing-library failure in auto mode."""
        if self._device_mode != TRANSCRIPTION_DEVICE_AUTO:
            return False
        if self._runtime_cpu_fallback_attempted:
            return False
        message = str(exc).lower()
        return any(token in message for token in ("cublas", "cudnn", "cuda"))

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
