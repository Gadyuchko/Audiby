"""Behavior-focused tests for Transcriber.

Tests validate queue-driven transcription flow, text normalization,
error handling, privacy guardrails, and device mode policy.
Hardware and faster-whisper are fully mocked.
"""
import logging
import queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audiby.constants import (
    AUDIO_MAX_GAIN,
    AUDIO_TARGET_PEAK,
    DEFAULT_SAMPLE_RATE,
    TRANSCRIPTION_BEAM_SIZE,
)
from audiby.core.transcriber import Transcriber
from audiby.exceptions import ModelError, TranscriptionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audio(duration_sec: float = 1.0, amplitude: float = 0.5) -> np.ndarray:
    """Return an audible float32 mono 16kHz buffer (1-D) of the given duration.

    A tone rather than zeros: the transcriber drops near-silent buffers before
    they reach the model, so a zero buffer would never exercise the model path.
    """
    samples = int(DEFAULT_SAMPLE_RATE * duration_sec)
    time_axis = np.arange(samples, dtype="float32") / DEFAULT_SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 440.0 * time_axis)).astype("float32")


def _make_silence(duration_sec: float = 1.0) -> np.ndarray:
    """Return a float32 mono buffer at the level a muted/idle mic produces."""
    samples = int(DEFAULT_SAMPLE_RATE * duration_sec)
    return np.zeros(samples, dtype="float32")


def _make_segment(text: str) -> MagicMock:
    """Create a mock transcription segment with the given text."""
    seg = MagicMock()
    seg.text = text
    return seg


@pytest.fixture
def make_transcriber():
    """Factory fixture creating a Transcriber with WhisperModel mocked.

    Returns (transcriber, mock_model, text_queue). Patches stay active until
    test teardown.
    """
    patches = []

    def _factory(segments=None, text_queue=None):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(segments or []), None)
        patcher = patch("audiby.core.transcriber.WhisperModel", return_value=mock_model)
        patcher.start()
        patches.append(patcher)

        from audiby.core.transcriber import Transcriber

        tq = text_queue or queue.Queue()
        transcriber = Transcriber(
            audio_queue=queue.Queue(), text_queue=tq, model_path="/fake/model"
        )
        return transcriber, mock_model, tq

    yield _factory

    for patcher in patches:
        patcher.stop()


# ---------------------------------------------------------------------------
# Accept audio buffers and call WhisperModel.transcribe()
# ---------------------------------------------------------------------------

class TestTranscriberInit:
    """Transcriber loads the model once at construction time."""

    def test_model_loaded_once_at_init(self):
        """WhisperModel must be instantiated exactly once during Transcriber init."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            mock_cls.assert_called_once()

    def test_model_path_forwarded_to_whisper_model(self):
        """The model_path must be passed as the first positional arg to WhisperModel."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            args, _ = mock_cls.call_args
            assert args[0] == "/fake/model"


class TestTranscribeCall:
    """transcribe() calls WhisperModel.transcribe with deterministic defaults."""

    def test_transcribe_calls_model_with_beam_size(self):
        """WhisperModel.transcribe must be called with beam_size from constants."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = (iter([_make_segment("hello")]), None)
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            audio = _make_audio(1.0)
            t.transcribe(audio)

            _, kwargs = mock_model.transcribe.call_args
            assert kwargs["beam_size"] == TRANSCRIPTION_BEAM_SIZE

    def test_transcribe_passes_audio_array_directly(self):
        """The raw numpy array must be passed to model.transcribe, not a file path."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = (iter([_make_segment("hi")]), None)
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            audio = _make_audio(0.5)
            t.transcribe(audio)

            args, _ = mock_model.transcribe.call_args
            assert isinstance(args[0], np.ndarray)
            assert np.array_equal(args[0], audio)

    def test_transcribe_rejects_non_float32_buffer(self):
        """Passing an int16 buffer must raise TranscriptionError immediately."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            bad_audio = np.zeros(16000, dtype="int16")
            with pytest.raises(TranscriptionError, match="float32"):
                t.transcribe(bad_audio)

    def test_transcribe_rejects_multi_dimensional_buffer(self):
        """Passing a 2-D buffer must raise TranscriptionError."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            bad_audio = np.zeros((16000, 2), dtype="float32")
            with pytest.raises(TranscriptionError, match="1-D"):
                t.transcribe(bad_audio)


# ---------------------------------------------------------------------------
# Join segment text, normalize whitespace, and push to the text queue
# ---------------------------------------------------------------------------

class TestTextNormalizationAndQueueOutput:
    """transcribe() joins segments, normalizes whitespace, pushes to text queue."""

    def test_multiple_segments_joined_into_single_string(self):
        """Multiple segments must be concatenated into one text queue entry."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = (
                iter([_make_segment(" Hello "), _make_segment(" world ")]),
                None,
            )
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
            )
            t.transcribe(_make_audio())

            result = text_q.get_nowait()
            assert result == "Hello world"

    def test_whitespace_collapsed_and_stripped(self):
        """Leading/trailing whitespace stripped, internal runs collapsed to single space."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = (
                iter([_make_segment("  Hello   "), _make_segment("   world  ")]),
                None,
            )
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
            )
            t.transcribe(_make_audio())

            result = text_q.get_nowait()
            assert result == "Hello world"

    def test_empty_segments_produce_no_queue_entry(self):
        """If all segments are whitespace-only, nothing must be pushed to queue."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = (
                iter([_make_segment("   "), _make_segment("")]),
                None,
            )
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
            )
            t.transcribe(_make_audio())

            assert text_q.empty()

    def test_no_segments_produce_no_queue_entry(self):
        """Zero segments from model must result in empty queue."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = (iter([]), None)
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
            )
            t.transcribe(_make_audio())

            assert text_q.empty()

    def test_word_split_across_segments_preserved(self):
        """A word split at a segment boundary must not get a space injected mid-word."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            # Whisper split "hello" across two segments
            mock_model.transcribe.return_value = (
                iter([_make_segment("hel"), _make_segment("lo world")]),
                None,
            )
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
            )
            t.transcribe(_make_audio())

            result = text_q.get_nowait()
            assert result == "hello world"

    def test_single_queue_put_per_transcription(self):
        """Each transcribe() call must produce at most one queue entry, not one per segment."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            # Realistic Whisper output — segments carry their own spacing
            mock_model.transcribe.return_value = (
                iter([_make_segment(" First"), _make_segment(" second"), _make_segment(" third")]),
                None,
            )
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
            )
            t.transcribe(_make_audio())

            assert text_q.qsize() == 1
            assert text_q.get_nowait() == "First second third"


# ---------------------------------------------------------------------------
# Error handling: wrap exceptions, log metadata, and stay recoverable
# ---------------------------------------------------------------------------

class TestTranscriptionErrorHandling:
    """Transcription failures are wrapped, logged with metadata only, and recoverable."""

    def test_model_transcribe_runtime_error_wrapped_as_transcription_error(self):
        """RuntimeError from model.transcribe must surface as TranscriptionError."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            mock_model.transcribe.side_effect = RuntimeError("decode failed")
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            with pytest.raises(TranscriptionError):
                t.transcribe(_make_audio())

    def test_model_transcribe_exception_preserves_original_cause(self):
        """Wrapped TranscriptionError must chain the original exception via __cause__."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            original = RuntimeError("ctranslate2 crash")
            mock_model.transcribe.side_effect = original
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            with pytest.raises(TranscriptionError) as exc_info:
                t.transcribe(_make_audio())
            assert exc_info.value.__cause__ is original

    def test_runtime_cuda_dll_failure_falls_back_to_cpu_and_recovers(self):
        """Auto mode should recover on cublas DLL runtime failure by switching to CPU once."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 1

            cuda_model = MagicMock()
            cuda_model.transcribe.side_effect = RuntimeError(
                "Library cublas64_12.dll is not found or cannot be loaded"
            )
            cpu_model = MagicMock()
            cpu_model.transcribe.return_value = (iter([_make_segment(" recovered")]), None)
            mock_cls.side_effect = [cuda_model, cpu_model]
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
                device_mode="auto",
            )

            t.transcribe(_make_audio())

            assert mock_cls.call_count == 2
            _, fallback_kwargs = mock_cls.call_args
            assert fallback_kwargs["device"] == "cpu"
            assert text_q.get_nowait() == "recovered"

    def test_model_load_failure_wrapped_as_model_error(self):
        """Exception during WhisperModel() init must raise ModelError."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 0
            mock_cls.side_effect = RuntimeError("failed to load model")
            from audiby.core.transcriber import Transcriber

            with pytest.raises(ModelError):
                Transcriber(
                    audio_queue=queue.Queue(),
                    text_queue=queue.Queue(),
                    model_path="/fake/model",
                    device_mode="cpu",
                )

    def test_transcriber_recovers_after_failed_transcription(self):
        """After a transcription failure, the next valid call must succeed."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()
            # First call fails, second succeeds
            mock_model.transcribe.side_effect = [
                RuntimeError("transient failure"),
                (iter([_make_segment(" recovered text")]), None),
            ]
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            text_q = queue.Queue()
            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=text_q,
                model_path="/fake/model",
            )

            # First call fails
            with pytest.raises(TranscriptionError):
                t.transcribe(_make_audio())

            # Second call recovers
            t.transcribe(_make_audio())
            assert text_q.get_nowait() == "recovered text"

    def test_error_during_segment_iteration_wrapped(self):
        """Exception raised while iterating segments must be caught and wrapped."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls:
            mock_model = MagicMock()

            def _exploding_segments():
                yield _make_segment(" ok")
                raise RuntimeError("segment decode error")

            mock_model.transcribe.return_value = (_exploding_segments(), None)
            mock_cls.return_value = mock_model
            from audiby.core.transcriber import Transcriber

            t = Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            with pytest.raises(TranscriptionError):
                t.transcribe(_make_audio())


# ---------------------------------------------------------------------------
# Tasks 1.5–1.7 — Device mode policy: auto, cuda, cpu
# ---------------------------------------------------------------------------

class TestDeviceModePolicy:
    """WhisperModel constructor args depend on device_mode and GPU availability."""

    def test_auto_mode_uses_cuda_when_gpu_available(self):
        """auto mode with GPU present must pass device='cuda', compute_type='float16'."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 1
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
                device_mode="auto",
            )
            _, kwargs = mock_cls.call_args
            assert kwargs["device"] == "cuda"
            assert kwargs["compute_type"] == "float16"

    def test_auto_mode_falls_back_to_cpu_when_no_gpu(self):
        """auto mode without GPU must fall back to device='cpu' with cpu-safe compute type."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 0
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
                device_mode="auto",
            )
            _, kwargs = mock_cls.call_args
            assert kwargs["device"] == "cpu"
            assert kwargs["compute_type"] != "float16"

    def test_auto_mode_falls_back_on_cuda_init_failure(self):
        """auto mode must fall back to CPU if WhisperModel raises on CUDA load."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 1
            # First call (CUDA) fails, second call (CPU fallback) succeeds
            mock_cls.side_effect = [RuntimeError("CUDA OOM"), MagicMock()]
            from audiby.core.transcriber import Transcriber

            Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
                device_mode="auto",
            )
            assert mock_cls.call_count == 2
            _, fallback_kwargs = mock_cls.call_args
            assert fallback_kwargs["device"] == "cpu"

    def test_cpu_mode_forces_cpu(self):
        """cpu mode must always use device='cpu' regardless of GPU availability."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 2  # GPUs present but ignored
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
                device_mode="cpu",
            )
            _, kwargs = mock_cls.call_args
            assert kwargs["device"] == "cpu"

    def test_cuda_mode_fails_fast_when_no_gpu(self):
        """Forced cuda mode with no GPU must raise ModelError immediately."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 0
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            with pytest.raises(ModelError):
                Transcriber(
                    audio_queue=queue.Queue(),
                    text_queue=queue.Queue(),
                    model_path="/fake/model",
                    device_mode="cuda",
                )

    def test_cuda_mode_no_silent_cpu_downgrade(self):
        """Forced cuda mode must NOT silently fall back to CPU on CUDA failure."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 1
            mock_cls.side_effect = RuntimeError("CUDA broken")
            from audiby.core.transcriber import Transcriber

            with pytest.raises(ModelError):
                Transcriber(
                    audio_queue=queue.Queue(),
                    text_queue=queue.Queue(),
                    model_path="/fake/model",
                    device_mode="cuda",
                )
            # Must NOT have retried with CPU
            assert mock_cls.call_count == 1

    def test_default_device_mode_is_auto(self):
        """Omitting device_mode must default to auto behavior."""
        with patch("audiby.core.transcriber.WhisperModel") as mock_cls, \
             patch("audiby.core.transcriber.ctranslate2") as mock_ct2:
            mock_ct2.get_cuda_device_count.return_value = 0
            mock_cls.return_value = MagicMock()
            from audiby.core.transcriber import Transcriber

            Transcriber(
                audio_queue=queue.Queue(),
                text_queue=queue.Queue(),
                model_path="/fake/model",
            )
            _, kwargs = mock_cls.call_args
            assert kwargs["device"] == "cpu"


# ---------------------------------------------------------------------------
# Silence gate: near-silent audio must never reach the model
# ---------------------------------------------------------------------------

class TestSilenceGate:
    """Whisper invents canned phrases from silence, so quiet audio is dropped.

    This is the regression guard for the observed failure: a muted/wrong
    microphone produced " Thank you." and " Bye." which were then pasted into
    the user's active window as if they had been dictated.
    """

    def test_silent_buffer_is_not_sent_to_the_model(self, make_transcriber):
        """A muted mic must cost zero model passes."""
        t, mock_model, _ = make_transcriber(segments=[_make_segment(" Thank you.")])

        t.transcribe(_make_silence())

        mock_model.transcribe.assert_not_called()

    def test_silent_buffer_queues_no_text(self, make_transcriber):
        """Nothing may be queued for injection when the mic captured silence."""
        t, _, text_queue = make_transcriber(segments=[_make_segment(" Thank you.")])

        t.transcribe(_make_silence())

        assert text_queue.empty()

    def test_empty_buffer_is_treated_as_silence(self, make_transcriber):
        """A zero-length buffer must be dropped, not crash on amplitude maths."""
        t, mock_model, text_queue = make_transcriber()

        t.transcribe(np.array([], dtype="float32"))

        mock_model.transcribe.assert_not_called()
        assert text_queue.empty()

    def test_room_noise_floor_is_treated_as_silence(self, make_transcriber):
        """Measured real-world idle level (peak ~0.0025) must not transcribe."""
        t, mock_model, text_queue = make_transcriber(segments=[_make_segment(" Bye.")])

        t.transcribe(_make_audio(amplitude=0.0025))

        mock_model.transcribe.assert_not_called()
        assert text_queue.empty()

    def test_vad_filter_is_enabled_for_the_decode_pass(self, make_transcriber):
        """Loud non-speech passes the amplitude gate, so VAD must strip it."""
        t, mock_model, _ = make_transcriber(segments=[_make_segment("words")])

        t.transcribe(_make_audio(amplitude=0.3))

        assert mock_model.transcribe.call_args.kwargs["vad_filter"] is True

    def test_audible_speech_still_transcribes(self, make_transcriber):
        """The gate must not swallow real dictation."""
        t, mock_model, text_queue = make_transcriber(segments=[_make_segment("hello there")])

        t.transcribe(_make_audio(amplitude=0.3))

        mock_model.transcribe.assert_called_once()
        assert text_queue.get_nowait() == "hello there"

    def test_quiet_but_audible_speech_still_transcribes(self, make_transcriber):
        """A soft speaker must not be mistaken for a dead microphone."""
        t, mock_model, text_queue = make_transcriber(segments=[_make_segment("quiet words")])

        t.transcribe(_make_audio(amplitude=0.05))

        mock_model.transcribe.assert_called_once()
        assert text_queue.get_nowait() == "quiet words"

    def test_logs_actionable_hint_when_audio_is_silent(self, make_transcriber, caplog):
        """The log must point at the microphone - this took a long time to diagnose."""
        t, _, _ = make_transcriber()

        with caplog.at_level(logging.INFO, logger="audiby.core.transcriber"):
            t.transcribe(_make_silence())

        assert "below silence threshold" in caplog.text
        assert "microphone" in caplog.text

    def test_logs_measured_levels_for_diagnosis(self, make_transcriber, caplog):
        """Amplitude must be observable in logs, not merely inferable."""
        t, _, _ = make_transcriber(segments=[_make_segment("audible")])

        with caplog.at_level(logging.DEBUG, logger="audiby.core.transcriber"):
            t.transcribe(_make_audio(amplitude=0.3))

        assert "peak=" in caplog.text
        assert "rms=" in caplog.text

    def test_silence_gate_never_logs_transcript_text(self, make_transcriber, caplog):
        """Privacy rule holds on the drop path too."""
        t, _, _ = make_transcriber(segments=[_make_segment(" Thank you.")])

        with caplog.at_level(logging.DEBUG, logger="audiby.core.transcriber"):
            t.transcribe(_make_silence())

        assert "Thank you" not in caplog.text


# ---------------------------------------------------------------------------
# Capture gain: consistent level regardless of mic sensitivity or distance
# ---------------------------------------------------------------------------

class TestCaptureGain:
    """Quiet-but-valid audio is normalized before decoding.

    Regression guard: at normal talking distance a headset produced rms 0.0044
    and "how about now" decoded as "OH"; the same voice closer in produced rms
    0.011 and decoded perfectly. Whisper gets no automatic gain control, so the
    pipeline supplies it.
    """

    def test_quiet_audio_is_boosted_toward_the_target_peak(self):
        """A quiet buffer must reach the target level."""
        quiet = _make_audio(amplitude=0.04)

        boosted = Transcriber._apply_capture_gain(quiet, 0.04)

        assert float(np.abs(boosted).max()) == pytest.approx(AUDIO_TARGET_PEAK, rel=1e-3)

    def test_gain_is_capped_for_extremely_quiet_audio(self):
        """A hard cap stops a barely-audible buffer being blown up into noise."""
        very_quiet = _make_audio(amplitude=0.001)

        boosted = Transcriber._apply_capture_gain(very_quiet, 0.001)

        applied_gain = float(np.abs(boosted).max()) / 0.001
        assert applied_gain == pytest.approx(AUDIO_MAX_GAIN, rel=1e-3)

    def test_audio_at_or_above_target_is_passed_through_untouched(self):
        """A loud speaker must never be attenuated."""
        loud = _make_audio(amplitude=0.6)

        result = Transcriber._apply_capture_gain(loud, 0.6)

        assert result is loud

    def test_gain_preserves_float32_dtype(self):
        """faster-whisper requires float32 - scaling must not promote to float64."""
        boosted = Transcriber._apply_capture_gain(_make_audio(amplitude=0.04), 0.04)

        assert boosted.dtype == np.float32

    def test_zero_peak_buffer_is_returned_unchanged(self):
        """Guard the divide - a zero buffer must not produce inf or nan."""
        silence = _make_silence()

        result = Transcriber._apply_capture_gain(silence, 0.0)

        assert result is silence

    def test_model_receives_the_gained_buffer(self, make_transcriber):
        """The boost must actually reach the decoder, not just be computed."""
        t, mock_model, _ = make_transcriber(segments=[_make_segment("words")])

        t.transcribe(_make_audio(amplitude=0.04))

        decoded = mock_model.transcribe.call_args.args[0]
        assert float(np.abs(decoded).max()) == pytest.approx(AUDIO_TARGET_PEAK, rel=1e-3)

    def test_gain_runs_after_the_silence_gate(self, make_transcriber):
        """Silence must be dropped before gain, never amplified into speech."""
        t, mock_model, text_queue = make_transcriber(segments=[_make_segment(" Thank you.")])

        t.transcribe(_make_audio(amplitude=0.002))

        mock_model.transcribe.assert_not_called()
        assert text_queue.empty()

    def test_gain_is_logged_for_diagnosis(self, make_transcriber, caplog):
        """The applied gain must be visible when explaining a bad transcription."""
        t, _, _ = make_transcriber(segments=[_make_segment("words")])

        with caplog.at_level(logging.DEBUG, logger="audiby.core.transcriber"):
            t.transcribe(_make_audio(amplitude=0.04))

        assert "Applying capture gain" in caplog.text
