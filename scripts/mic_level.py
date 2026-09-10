"""Measure input level per device - diagnostic helper for quiet-microphone reports.

Prints peak/rms for a capture device while you speak, alongside the silence-gate
thresholds the transcriber applies, so a "my mic is too low" report becomes a
number instead of an impression.

Usage (PowerShell, from the repo root):

    .venv\\Scripts\\python scripts/mic_level.py            # list devices
    .venv\\Scripts\\python scripts/mic_level.py 2          # measure device 2
    .venv\\Scripts\\python scripts/mic_level.py 2 --seconds 8
"""

import argparse
import sys
import time

import numpy as np
import sounddevice as sd

from audiby.constants import (
    DEFAULT_SAMPLE_RATE,
    SILENCE_PEAK_THRESHOLD,
    SILENCE_RMS_THRESHOLD,
)
from audiby.core.audio_recorder import list_input_devices

# Reference levels measured on real hardware, used to grade a reading.
_GOOD_PEAK = 0.20
_GOOD_RMS = 0.02
_METER_WIDTH = 40


def _print_devices() -> None:
    """List selectable capture devices with the ids the app understands."""
    print("Available input devices:\n")
    for device in list_input_devices():
        device_id = "default" if device.device_id is None else str(device.device_id)
        print(f"  {device_id:>7}  {device.label}")
    print("\nRe-run with a device id, e.g.: .venv\\Scripts\\python scripts/mic_level.py 2")


def _meter(peak: float) -> str:
    """Render a coarse bar so the level is readable at a glance."""
    filled = min(_METER_WIDTH, int(peak / _GOOD_PEAK * _METER_WIDTH))
    return "#" * filled + "-" * (_METER_WIDTH - filled)


def _grade(peak: float, rms: float) -> str:
    """Classify a reading against the gate and the healthy-level reference."""
    if peak < SILENCE_PEAK_THRESHOLD or rms < SILENCE_RMS_THRESHOLD:
        return "SILENT - this would be dropped before transcription"
    if peak < _GOOD_PEAK or rms < _GOOD_RMS:
        return "LOW - usable; the pipeline normalizes this, but closer decodes better"
    return "GOOD"


def measure(device_id: int | None, seconds: float) -> int:
    """Record from one device and report peak/rms for the whole take."""
    print(f"Recording {seconds:g}s from device {device_id if device_id is not None else 'default'}.")
    print("Speak normally now...\n")

    try:
        audio = sd.rec(
            int(seconds * DEFAULT_SAMPLE_RATE),
            samplerate=DEFAULT_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=device_id,
        )
    except sd.PortAudioError as err:
        print(f"Could not open device {device_id}: {err}")
        return 1

    # Live readout while the take runs, so a dead mic is obvious at once. Each
    # frame reports only the newest slice - a cumulative max would latch high
    # and stop reflecting what you are saying now.
    last_index = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.15)
        elapsed = seconds - max(0.0, deadline - time.monotonic())
        index = min(len(audio), int(elapsed * DEFAULT_SAMPLE_RATE))
        window = audio[last_index:index]
        last_index = index
        current = float(np.abs(window).max()) if window.size else 0.0
        print(f"\r  [{_meter(current)}] peak={current:.5f}", end="", flush=True)
    sd.wait()
    print()

    flat = audio.flatten()
    peak = float(np.abs(flat).max())
    rms = float(np.sqrt(np.mean(np.square(flat))))

    print()
    print(f"  peak = {peak:.5f}   (gate drops below {SILENCE_PEAK_THRESHOLD}, healthy >= {_GOOD_PEAK})")
    print(f"  rms  = {rms:.5f}   (gate drops below {SILENCE_RMS_THRESHOLD}, healthy >= {_GOOD_RMS})")
    print(f"  verdict: {_grade(peak, rms)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure microphone input level.")
    parser.add_argument(
        "device",
        nargs="?",
        help="device id from the listing, or 'default'; omit to list devices",
    )
    parser.add_argument("--seconds", type=float, default=5.0, help="take length (default: 5)")
    args = parser.parse_args(argv)

    if args.device is None:
        _print_devices()
        return 0

    device_id = None if args.device.lower() == "default" else int(args.device)
    return measure(device_id, args.seconds)


if __name__ == "__main__":
    sys.exit(main())
