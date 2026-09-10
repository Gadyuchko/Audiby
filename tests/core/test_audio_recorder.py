"""Behavior-focused tests for AudioRecorder.

Tests validate recording lifecycle, queue output, default device handling,
and PortAudioError -> AudioError propagation. Hardware is fully mocked.
"""
import queue

import numpy as np
import pytest
import sounddevice as sd

from audiby.constants import AUDIO_DEVICE_AUTO_LABEL, DEFAULT_SAMPLE_RATE
from audiby.core.audio_recorder import (
    AudioInputDevice,
    AudioRecorder,
    describe_device,
    list_input_devices,
)
from audiby.exceptions import AudioDeviceError, AudioError, MicPermissionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(frames: int = 1024) -> np.ndarray:
    """Return a float32 mono chunk as sounddevice would deliver it."""
    return np.zeros((frames, 1), dtype="float32")


def _simulate_recording(recorder: AudioRecorder, chunks: list[np.ndarray]) -> None:
    """Drive callback with synthetic chunks, then stop/close."""
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
        recorder.close()

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
        recorder.close()

    def test_double_start_is_idempotent(self, mocker):
        """Calling start() twice should not open a second stream."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.start()
        assert sd.InputStream.call_count == 1
        recorder.stop()
        recorder.close()


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
        recorder.close()

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
        recorder.close()

        result = q.get_nowait()
        assert len(result) == 256 + 512 + 128

    def test_stop_clears_recording_flag(self, mocker):
        """_recording event must be cleared after stop()."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.stop()
        assert not recorder._recording.is_set()
        recorder.close()

    def test_stop_keeps_stream_primed(self, mocker):
        """stop() should keep stream open to avoid startup clipping on next burst."""
        mock_stream = mocker.MagicMock()
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.stop()

        mock_stream.stop.assert_not_called()
        mock_stream.close.assert_not_called()

        recorder.close()
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()

    def test_no_queue_push_when_no_audio_captured(self, mocker):
        """Stopping immediately after start (no chunks) must not push to queue."""
        mocker.patch("sounddevice.InputStream")
        q = queue.Queue()
        recorder = AudioRecorder(audio_queue=q)
        recorder.start()
        recorder.stop()
        recorder.close()
        assert q.empty()


# ---------------------------------------------------------------------------
# Default device used when no device id configured
# ---------------------------------------------------------------------------

class TestDefaultDevice:
    def test_no_device_id_passes_none_to_input_stream(self, mocker):
        """device=None must be passed to InputStream when not configured."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue())
        recorder.start()
        recorder.stop()
        recorder.close()
        _, kwargs = sd.InputStream.call_args
        assert kwargs.get("device") is None

    def test_explicit_device_id_forwarded_to_input_stream(self, mocker):
        """A configured device_id must be forwarded as device= parameter."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=3)
        recorder.start()
        recorder.stop()
        recorder.close()
        _, kwargs = sd.InputStream.call_args
        assert kwargs["device"] == 3


# ---------------------------------------------------------------------------
# Error handling - PortAudioError -> AudioError
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_permission_error_on_stream_open_raises_mic_permission_error(self, mocker):
        """Permission-denied open failures must raise MicPermissionError with cause."""
        original = sd.PortAudioError("Error opening InputStream: access denied")
        mocker.patch(
            "sounddevice.InputStream",
            side_effect=original,
        )
        recorder = AudioRecorder(audio_queue=queue.Queue())
        with pytest.raises(MicPermissionError) as exc_info:
            recorder.start()
        assert exc_info.value.__cause__ is original

    def test_permission_error_on_stream_start_raises_mic_permission_error(self, mocker):
        """Permission-denied start failures must raise MicPermissionError with cause."""
        original = sd.PortAudioError("Microphone permission denied")
        mock_stream = mocker.MagicMock()
        mock_stream.start.side_effect = original
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)

        recorder = AudioRecorder(audio_queue=queue.Queue())
        with pytest.raises(MicPermissionError) as exc_info:
            recorder.start()

        assert exc_info.value.__cause__ is original
        assert recorder._stream is None
        mock_stream.close.assert_called_once()

    def test_port_audio_error_on_start_raises_audio_device_error(self, mocker):
        """Generic sounddevice.PortAudioError during start must raise AudioDeviceError."""
        original = sd.PortAudioError("device unavailable")
        mocker.patch("sounddevice.InputStream", side_effect=original)
        recorder = AudioRecorder(audio_queue=queue.Queue())
        with pytest.raises(AudioDeviceError) as exc_info:
            recorder.start()
        assert exc_info.value.__cause__ is original

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
        assert caplog.records

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
        with pytest.raises(AudioDeviceError):
            recorder.start()

        assert not recorder._recording.is_set()
        assert recorder._stream is None
        mock_stream.close.assert_called_once()

    def test_close_failure_is_wrapped_as_audio_error(self, mocker):
        """PortAudioError from stream close remains generic AudioError during shutdown."""
        mock_stream = mocker.MagicMock()
        mock_stream.stop.side_effect = sd.PortAudioError("stop failed")
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)

        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=9)
        recorder.start()
        recorder.stop()
        with pytest.raises(AudioError):
            recorder.close()

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

        big_chunk = np.zeros((1_000_000, 1), dtype="float32")
        recorder._callback(big_chunk, 1_000_000, None, None)
        recorder._callback(big_chunk, 1_000_000, None, None)
        recorder._callback(big_chunk, 1_000_000, None, None)
        recorder.stop()
        recorder.close()

        result = q.get_nowait()
        assert len(result) <= DEFAULT_SAMPLE_RATE * 120


class TestPrimeAndPreroll:
    def test_prime_opens_stream_without_recording(self, mocker):
        """prime() should open/start stream but not set recording flag."""
        mock_stream = mocker.MagicMock()
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)
        recorder = AudioRecorder(audio_queue=queue.Queue())

        recorder.prime()

        assert not recorder._recording.is_set()
        mock_stream.start.assert_called_once()
        recorder.close()

    def test_start_seeds_audio_with_preroll(self, mocker):
        """Recent pre-roll audio should be included at recording start."""
        mocker.patch("sounddevice.InputStream", return_value=mocker.MagicMock())
        q = queue.Queue()
        recorder = AudioRecorder(audio_queue=q)

        recorder.prime()
        recorder._callback(_make_chunk(160), 160, None, None)
        recorder.start()
        recorder._callback(_make_chunk(160), 160, None, None)
        recorder.stop()
        recorder.close()

        result = q.get_nowait()
        assert len(result) >= 320


# ---------------------------------------------------------------------------
# Device enumeration for the settings picker
# ---------------------------------------------------------------------------

# Mirrors real Windows enumeration: every physical mic appears once per host
# API, MME truncates names at 31 chars, and two entries are default-aliases.
_FAKE_DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
    {"name": "Microphone Array (Realtek(R) Au", "max_input_channels": 2, "hostapi": 0},
    {"name": "Microphone (Razer BlackShark V2", "max_input_channels": 1, "hostapi": 0},
    {"name": "Speakers (Realtek(R) Audio)", "max_input_channels": 0, "hostapi": 0},
    {"name": "Primary Sound Capture Driver", "max_input_channels": 2, "hostapi": 1},
    {"name": "Microphone Array (Realtek(R) Audio)", "max_input_channels": 2, "hostapi": 2},
    {"name": "Microphone (Razer BlackShark V2 Pro 2.4)", "max_input_channels": 1, "hostapi": 2},
]


def _patch_enumeration(
    mocker, devices, default_hostapi=0, default_device=(1, 4), unsupported=()
):
    """Patch sounddevice enumeration with a synthetic device table.

    `unsupported` lists device indices that must fail capture-format
    validation, standing in for Windows WDM-KS endpoints.
    """
    mocker.patch("audiby.core.audio_recorder.sd.query_devices", return_value=devices)
    mocker.patch(
        "audiby.core.audio_recorder.sd.default",
        mocker.MagicMock(hostapi=default_hostapi, device=list(default_device)),
    )

    rejected = set(unsupported)

    def _check(device=None, **_kwargs):
        if device in rejected:
            raise sd.PortAudioError("Invalid sample rate [PaErrorCode -9997]")

    return mocker.patch(
        "audiby.core.audio_recorder.sd.check_input_settings", side_effect=_check
    )


class TestListInputDevices:
    def test_first_entry_is_os_default_sentinel(self, mocker):
        """Picker must always offer 'follow the OS default' as device_id None."""
        _patch_enumeration(mocker, _FAKE_DEVICES)

        devices = list_input_devices()

        assert devices[0] == AudioInputDevice(None, AUDIO_DEVICE_AUTO_LABEL)

    def test_collapses_per_host_api_duplicates_to_one_row_per_mic(self, mocker):
        """The same mic exposed on several host APIs must appear only once."""
        _patch_enumeration(mocker, _FAKE_DEVICES)

        devices = list_input_devices()

        assert len(devices) == 3  # default sentinel + Realtek array + Razer

    def test_prefers_default_host_api_id_but_most_complete_name(self, mocker):
        """Keep the default-host-API index, and the untruncated display name."""
        _patch_enumeration(mocker, _FAKE_DEVICES)

        devices = list_input_devices()

        assert devices[1] == AudioInputDevice(1, "Microphone Array (Realtek(R) Audio)")
        assert devices[2] == AudioInputDevice(2, "Microphone (Razer BlackShark V2 Pro 2.4)")

    def test_uses_non_default_host_api_id_when_that_is_the_only_one(self, mocker):
        """A mic present only on a secondary host API must still be selectable."""
        _patch_enumeration(
            mocker,
            [{"name": "USB Podcast Mic", "max_input_channels": 1, "hostapi": 2}],
            default_hostapi=0,
        )

        devices = list_input_devices()

        assert devices[1] == AudioInputDevice(0, "USB Podcast Mic")

    def test_excludes_output_only_devices(self, mocker):
        """Devices with no input channels must not appear in a capture picker."""
        _patch_enumeration(mocker, _FAKE_DEVICES)

        labels = [device.label for device in list_input_devices()]

        assert "Speakers (Realtek(R) Audio)" not in labels

    def test_excludes_default_alias_pseudo_devices(self, mocker):
        """Host-API aliases for the default device would duplicate the sentinel."""
        _patch_enumeration(mocker, _FAKE_DEVICES)

        labels = [device.label for device in list_input_devices()]

        assert "Microsoft Sound Mapper - Input" not in labels
        assert "Primary Sound Capture Driver" not in labels

    def test_collapses_whitespace_in_driver_names(self, mocker):
        """Some Bluetooth drivers embed CR/LF, which breaks combobox rendering."""
        _patch_enumeration(
            mocker,
            [
                {
                    "name": "Headset (bthhfenum.sys,#2;\r\n(TUNE230NC))",
                    "max_input_channels": 1,
                    "hostapi": 0,
                }
            ],
        )

        label = list_input_devices()[1].label

        assert "\r" not in label and "\n" not in label
        assert label == "Headset (bthhfenum.sys,#2; (TUNE230NC))"

    def test_excludes_devices_that_reject_the_capture_format(self, mocker):
        """WDM-KS endpoints advertise inputs but fail to open - never list them.

        Regression guard: selecting one raised PaErrorCode -9996 and forced a
        rollback to the previous device.
        """
        _patch_enumeration(mocker, _FAKE_DEVICES, unsupported={1, 2, 5, 6})

        devices = list_input_devices()

        assert devices == [AudioInputDevice(None, AUDIO_DEVICE_AUTO_LABEL)]

    def test_validates_against_the_format_the_recorder_opens_with(self, mocker):
        """Validation must use the real capture settings, not looser ones."""
        check = _patch_enumeration(mocker, _FAKE_DEVICES)

        list_input_devices()

        kwargs = check.call_args.kwargs
        assert kwargs["samplerate"] == DEFAULT_SAMPLE_RATE
        assert kwargs["channels"] == 1
        assert kwargs["dtype"] == "float32"

    def test_keeps_a_mic_usable_on_one_host_api_when_another_rejects_it(self, mocker):
        """The same mic can be valid on WASAPI and invalid on WDM-KS."""
        _patch_enumeration(
            mocker,
            [
                {"name": "USB Mic", "max_input_channels": 1, "hostapi": 3},
                {"name": "USB Mic", "max_input_channels": 1, "hostapi": 0},
            ],
            unsupported={0},
        )

        devices = list_input_devices()

        assert devices[1] == AudioInputDevice(1, "USB Mic")

    def test_returns_default_only_when_enumeration_fails(self, mocker):
        """Picker must stay usable if the audio backend cannot be queried."""
        mocker.patch(
            "audiby.core.audio_recorder.sd.query_devices",
            side_effect=sd.PortAudioError("backend unavailable"),
        )

        devices = list_input_devices()

        assert devices == [AudioInputDevice(None, AUDIO_DEVICE_AUTO_LABEL)]


class TestDescribeDevice:
    def test_describes_explicit_device_with_name_and_index(self, mocker):
        """Logs must name the device, not just its opaque index."""
        mocker.patch(
            "audiby.core.audio_recorder.sd.query_devices",
            return_value={"name": "Microphone (Razer BlackShark V2 Pro 2.4)"},
        )

        assert describe_device(2) == "Microphone (Razer BlackShark V2 Pro 2.4) (index 2)"

    def test_resolves_what_the_os_default_actually_points_at(self, mocker):
        """device=None hides which mic is really in use - resolve it for logs."""
        _patch_enumeration(mocker, _FAKE_DEVICES, default_device=(1, 4))
        mocker.patch(
            "audiby.core.audio_recorder.sd.query_devices",
            return_value={"name": "Microphone Array (Realtek(R) Audio)"},
        )

        described = describe_device(None)

        assert described == "System default -> Microphone Array (Realtek(R) Audio) (index 1)"

    def test_falls_back_when_device_cannot_be_queried(self, mocker):
        """An unplugged device must not make logging raise."""
        mocker.patch(
            "audiby.core.audio_recorder.sd.query_devices",
            side_effect=sd.PortAudioError("no such device"),
        )

        assert describe_device(7) == "unknown device (index 7)"


# ---------------------------------------------------------------------------
# Switching capture device at runtime
# ---------------------------------------------------------------------------

class TestSetDevice:
    def test_reopens_stream_on_the_new_device(self, mocker):
        """The stream is opened once and reused, so it must be reopened on switch."""
        mock_stream = mocker.MagicMock()
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=None)
        recorder.prime()

        recorder.set_device(2)

        mock_stream.close.assert_called_once()
        assert sd.InputStream.call_args.kwargs["device"] == 2

    def test_is_a_noop_when_device_is_unchanged(self, mocker):
        """Re-saving settings without touching the mic must not drop the stream."""
        mock_stream = mocker.MagicMock()
        mocker.patch("sounddevice.InputStream", return_value=mock_stream)
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=2)
        recorder.prime()

        recorder.set_device(2)

        assert sd.InputStream.call_count == 1
        mock_stream.close.assert_not_called()

    def test_does_not_open_a_stream_that_was_never_primed(self, mocker):
        """Switching before startup must only record intent, not open hardware."""
        mocker.patch("sounddevice.InputStream")
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=None)

        recorder.set_device(2)

        sd.InputStream.assert_not_called()

    def test_discards_pre_roll_captured_from_the_previous_device(self, mocker):
        """Stale pre-roll audio belongs to the old mic and must not leak forward."""
        mocker.patch("sounddevice.InputStream", return_value=mocker.MagicMock())
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=None)
        recorder.prime()
        recorder._callback(_make_chunk(512), 512, None, None)
        assert recorder._pre_roll_samples > 0

        recorder.set_device(2)

        assert recorder._pre_roll_samples == 0
        assert len(recorder._pre_roll_chunks) == 0

    def test_records_from_the_configured_device(self, mocker):
        """A configured device id must reach sounddevice, not be silently dropped."""
        mocker.patch("sounddevice.InputStream", return_value=mocker.MagicMock())

        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=2)
        recorder.prime()

        assert sd.InputStream.call_args.kwargs["device"] == 2

    def test_recorder_recovers_on_next_start_after_failed_switch(self, mocker):
        """A mic that cannot be opened must not permanently kill capture.

        set_device leaves the stream closed when the new device fails to open;
        start() must lazily reopen it so the next hotkey press still records.
        """
        good_stream = mocker.MagicMock()
        mocker.patch(
            "sounddevice.InputStream",
            side_effect=[good_stream, sd.PortAudioError("cannot open"), good_stream],
        )
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=None)
        recorder.prime()

        with pytest.raises(AudioDeviceError):
            recorder.set_device(2)
        assert recorder._stream is None

        recorder.start()

        assert recorder._stream is good_stream

    def test_reprimes_after_a_previous_switch_failed_to_open(self, mocker):
        """A failed switch must not leave capture cold until the next press.

        Regression guard: selecting an unopenable device left the stream closed,
        and because the next switch only re-primed when a stream was already
        open, the following hotkey press paid the full device-open latency with
        an empty pre-roll buffer - clipping the first spoken word.
        """
        good = mocker.MagicMock()
        mocker.patch(
            "sounddevice.InputStream",
            side_effect=[good, sd.PortAudioError("invalid device"), good],
        )
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=None)
        recorder.prime()

        with pytest.raises(AudioDeviceError):
            recorder.set_device(22)
        assert recorder._stream is None

        recorder.set_device(2)

        assert recorder._stream is good

    def test_switching_keeps_the_stream_warm(self, mocker):
        """A successful switch must leave a running stream, not a cold one."""
        first, second = mocker.MagicMock(), mocker.MagicMock()
        mocker.patch("sounddevice.InputStream", side_effect=[first, second])
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=None)
        recorder.prime()

        recorder.set_device(2)

        assert recorder._stream is second
        second.start.assert_called_once()

    def test_shutdown_stops_a_later_switch_from_reopening_the_device(self, mocker):
        """close() is shutdown - a switch after it must not resurrect capture."""
        mocker.patch("sounddevice.InputStream", return_value=mocker.MagicMock())
        recorder = AudioRecorder(audio_queue=queue.Queue(), device_id=None)
        recorder.prime()
        recorder.close()

        recorder.set_device(2)

        assert recorder._stream is None
