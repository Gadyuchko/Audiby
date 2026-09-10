"""Behavior-focused tests for the mic_level diagnostic script.

Only the grading and rendering logic is covered - the recording path talks to
real hardware and is exercised manually.
"""

import numpy as np
import pytest

from audiby.constants import SILENCE_PEAK_THRESHOLD, SILENCE_RMS_THRESHOLD

from scripts.mic_level import _grade, _meter, main


class TestGrade:
    """A reading is graded against the gate first, then healthy reference."""

    def test_level_below_peak_gate_is_reported_as_silent(self):
        """Anything the transcriber would drop must be called out as silent."""
        verdict = _grade(peak=SILENCE_PEAK_THRESHOLD / 2, rms=0.02)

        assert verdict.startswith("SILENT")

    def test_level_below_rms_gate_is_reported_as_silent(self):
        """The gate fails on either threshold, so grading must match it."""
        verdict = _grade(peak=0.5, rms=SILENCE_RMS_THRESHOLD / 2)

        assert verdict.startswith("SILENT")

    def test_quiet_but_usable_level_is_reported_as_low(self):
        """The observed Realtek reading must land in LOW, not GOOD or SILENT."""
        verdict = _grade(peak=0.07745, rms=0.00472)

        assert verdict.startswith("LOW")

    def test_healthy_level_is_reported_as_good(self):
        """Normal dictation levels must not nag the user."""
        verdict = _grade(peak=0.3, rms=0.03)

        assert verdict == "GOOD"


class TestMeter:
    def test_silence_renders_an_empty_bar(self):
        assert set(_meter(0.0)) == {"-"}

    def test_healthy_level_fills_the_bar(self):
        assert set(_meter(0.5)) == {"#"}

    def test_bar_width_is_constant_across_levels(self):
        """A jittering width would make the live meter unreadable."""
        widths = {len(_meter(level)) for level in (0.0, 0.01, 0.077, 0.2, 5.0)}

        assert len(widths) == 1


class TestCli:
    def test_listing_devices_needs_no_device_argument(self, mocker, capsys):
        """Running with no args must show the ids, not start recording."""
        mocker.patch(
            "scripts.mic_level.list_input_devices",
            return_value=[mocker.MagicMock(device_id=None, label="System default")],
        )
        record = mocker.patch("scripts.mic_level.sd.rec")

        assert main([]) == 0
        record.assert_not_called()
        assert "System default" in capsys.readouterr().out

    def test_default_keyword_maps_to_the_os_default_device(self, mocker):
        """'default' must reach sounddevice as None, not the string."""
        measure = mocker.patch("scripts.mic_level.measure", return_value=0)

        main(["default"])

        assert measure.call_args.args[0] is None

    def test_numeric_argument_is_passed_as_a_device_id(self, mocker):
        measure = mocker.patch("scripts.mic_level.measure", return_value=0)

        main(["2"])

        assert measure.call_args.args[0] == 2

    def test_unopenable_device_exits_nonzero(self, mocker, capsys):
        """A wrong id must fail clearly rather than traceback."""
        import sounddevice as sd

        mocker.patch("scripts.mic_level.sd.rec", side_effect=sd.PortAudioError("bad id"))

        assert main(["99", "--seconds", "0.1"]) == 1
        assert "Could not open device 99" in capsys.readouterr().out
