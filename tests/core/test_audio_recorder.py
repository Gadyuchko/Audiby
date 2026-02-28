"""Behavior-focused tests for AudioRecorder.

Tests validate recording lifecycle, queue output, default device handling,
and PortAudioError → AudioError propagation. Hardware is fully mocked.
"""
import queue
import numpy as np
import pytest
import sounddevice as sd

from audiby.core.audio_recorder import AudioRecorder
from audiby.exceptions import AudioError
from audiby.constants import DEFAULT_SAMPLE_RATE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(frames: int = 1024) -> np.ndarray:
    """Return a float32 mono chunk as sounddevice would deliver it.
    We use zeros for tests because we don't care about contents, just the shape and type
    """
    return np.zeros((frames, 1), dtype="float32")


def _simulate_recording(recorder: AudioRecorder, chunks: list) -> None:
    """
    Drive recorder's internal callback with synthetic chunks, then stop.
    Used to avoid real hardware while exercising the full data path.
    """
    recorder.start()
    for chunk in chunks:
        recorder._callback(chunk, len(chunk), None, None)
    recorder.stop()


# ---------------------------------------------------------------------------
# Recording starts at 16kHz mono float32
# ---------------------------------------------------------------------------

class TestRecordingStart:
    def test_start_opens_input_stream_with_correct_params(self, mocker):
        """InputStream must be opened at DEFAULT_SAMPLE_RATE, channels=1, dtype=float32."""
        mock_stream = mocker.MagicMock()
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)

        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.stop()

        sd.InputStream.assert_called_once_with(
            samplerate=DEFAULT_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=None,
            callback=recorder._callback,
        )
        mock_stream.start.assert_called_once()

    def test_start_sets_recording_flag(self, mocker):
        """_recording event must be set when start() is called."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        assert recorder._recording.is_set()
        recorder.stop()

    def test_double_start_is_idempotent(self, mocker):
        """Calling start() twice should not open a second stream."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.start()  # second call — should be a no-op
        assert sd.InputStream.call_count == 1
        recorder.stop()


# ---------------------------------------------------------------------------
# On stop, complete numpy buffer placed on transcription queue
# ---------------------------------------------------------------------------

class TestRecordingStop:
    def test_stop_pushes_float32_numpy_array_to_queue(self, mocker):
        """Queue must receive a single contiguous float32 1-D numpy array."""
        mocker.patch("sounddevice.InputStream")
        q = queue.Queue()
        recorder = AudioRecorder(audio_queue=q)

        chunks = [_make_chunk(512), _make_chunk(512)]
        _simulate_recording(recorder, chunks)

        assert not q.empty()
        result = q.get_nowait()
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32
        assert result.ndim == 1

    def test_stop_concatenates_all_chunks_into_single_array(self, mocker):
        """Buffer must combine all chunks; total length == sum of frame counts."""
        mocker.patch("sounddevice.InputStream")
        q = queue.Queue()
        recorder = AudioRecorder(audio_queue=q)

        chunks = [_make_chunk(256), _make_chunk(512), _make_chunk(128)]
        _simulate_recording(recorder, chunks)

        result = q.get_nowait()
        assert len(result) == 256 + 512 + 128

    def test_stop_clears_recording_flag(self, mocker):
        """_recording event must be cleared after stop()."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.stop()
        assert not recorder._recording.is_set()

    def test_stop_closes_stream(self, mocker):
        """InputStream.stop() and .close() must be called on recorder stop."""
        mock_stream = mocker.MagicMock()
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.stop()
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()

    def test_no_queue_push_when_no_audio_captured(self, mocker):
        """Stopping immediately after start (no chunks) must not push to queue."""
        mocker.patch("sounddevice.InputStream")
        q = queue.Queue()
        recorder = AudioRecorder(audio_queue=q)
        recorder.start()
        recorder.stop()
        assert q.empty()


# ---------------------------------------------------------------------------
# Default device used when no device id configured
# ---------------------------------------------------------------------------

class TestDefaultDevice:
    def test_no_device_id_passes_none_to_input_stream(self, mocker):
        """device=None must be passed to InputStream when not configured."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue())  # no device_id
        recorder.start()
        recorder.stop()
        _, kwargs = sd.InputStream.call_args
        assert kwargs.get("device") is None

    def test_explicit_device_id_forwarded_to_input_stream(self, mocker):
        """A configured device_id must be forwarded as device= parameter."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=3)
        recorder.start()
        recorder.stop()
        _, kwargs = sd.InputStream.call_args
        assert kwargs["device"] == 3


# ---------------------------------------------------------------------------
# Error handling — PortAudioError → AudioError
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_port_audio_error_on_start_raises_audio_error(self, mocker):
        """sounddevice.PortAudioError during start must raise AudioError."""
        mocker.patch(
            "sounddevice.InputStream",
            side_effect=sd.PortAudioError("device unavailable"),
        )
        recorder = AudioRecorder(audio_queue=queue.Queue())
        with pytest.raises(AudioError):
            recorder.start()

    def test_port_audio_error_logged_with_metadata(self, mocker, caplog):
        """AudioError must be logged with device/state metadata, not audio content."""
        mocker.patch(
            "sounddevice.InputStream",
            side_effect=sd.PortAudioError("device unavailable"),
        )
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=7)
        import logging
        with caplog.at_level(logging.ERROR, logger="audiby.core.audio_recorder"):
            with pytest.raises(AudioError):
                recorder.start()
        assert caplog.records  # at least one ERROR logged

    def test_audio_error_does_not_push_to_queue(self, mocker):
        """Queue must remain empty when start() fails with PortAudioError."""
        mocker.patch(
            "sounddevice.InputStream",
            side_effect=sd.PortAudioError("no device"),
        )
        q = queue.Queue()
        recorder = AudioRecorder(audio_queue=q)
        with pytest.raises(AudioError):
            recorder.start()
        assert q.empty()

    def test_stream_start_failure_is_wrapped_and_state_reset(self, mocker):
        """PortAudioError from InputStream.start() must be wrapped and recorder state reset."""
        mock_stream = mocker.MagicMock()
        mock_stream.start.side_effect = sd.PortAudioError("start failed")
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)

        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=4)
        with pytest.raises(AudioError):
            recorder.start()

        assert not recorder._recording.is_set()
        assert recorder._stream is None
        mock_stream.close.assert_called_once()

    def test_stop_failure_is_wrapped_as_audio_error(self, mocker):
        """PortAudioError from stream shutdown must surface as AudioError."""
        mock_stream = mocker.MagicMock()
        mock_stream.stop.side_effect = sd.PortAudioError("stop failed")
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)

        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=9)
        recorder.start()
        with pytest.raises(AudioError):
            recorder.stop()

        assert recorder._stream is None

# ---------------------------------------------------------------------------
# Max recording duration guard
# ---------------------------------------------------------------------------

class TestMaxDuration:
    def test_max_duration_truncates_buffer(self, mocker):
        """Recording exceeding ~2 min worth of samples must be capped."""
        mocker.patch("sounddevice.InputStream")
        q = queue.Queue()
        recorder = AudioRecorder(audio_queue=q)
        recorder.start()

        # Push more than 2 min of data (2*60*16000 = 1,920,000 frames)
        big_chunk = np.zeros((1_000_000, 1), dtype="float32")
        recorder._callback(big_chunk, 1_000_000, None, None)
        recorder._callback(big_chunk, 1_000_000, None, None)
        recorder._callback(big_chunk, 1_000_000, None, None)  # 3M frames > 2min cap
        recorder.stop()

        result = q.get_nowait()
        assert len(result) <= DEFAULT_SAMPLE_RATE * 120  # ≤ 2 min
