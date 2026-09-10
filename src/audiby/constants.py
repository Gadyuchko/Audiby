"""Shared constants for application-wide values."""

import sys

# Application identity
APP_NAME = "Audiby"
CONFIG_FILENAME = "config.json"

# Config key constants (match JSON keys exactly)
CONFIG_KEY_HOTKEY = "push_to_talk_key"
CONFIG_KEY_AUDIO_DEVICE = "audio_device_id"
CONFIG_KEY_MODEL = "model_size"
CONFIG_KEY_AUTOSTART = "start_on_boot"
CONFIG_KEY_ALT_NEUTRALIZATION = "alt_neutralization_strategy"

# Default values
# Runtime data paths live in audiby.platform.paths — never duplicate the OS
# branching here.
DEFAULT_HOTKEY = "ctrl+space"

if sys.platform == "darwin":
    PASTE_CHORD = "cmd+v"
else:
    PASTE_CHORD = "ctrl+v"

DEFAULT_MODEL_SIZE = "base"
DEFAULT_AUDIO_DEVICE = None
DEFAULT_AUTOSTART = False
DEFAULT_ALT_NEUTRALIZATION_STRATEGY = "tap_alt"

ALT_NEUTRALIZATION_NONE = "none"
ALT_NEUTRALIZATION_TAP_ALT = "tap_alt"
ALT_NEUTRALIZATION_ESC = "esc"

# Audio constants
DEFAULT_SAMPLE_RATE = 16000

# Label shown in the settings device picker for "follow the OS default device".
AUDIO_DEVICE_AUTO_LABEL = "System default"

# Silence gate — Whisper hallucinates canned phrases (" Thank you.", " Bye.")
# when handed near-silent audio, so quiet buffers are dropped before they ever
# reach the model. Measured reference points on a real machine:
#   room silence  -> peak ~0.0025, rms ~0.0005
#   normal speech -> peak ~0.3,    rms ~0.03
# A buffer failing EITHER threshold is treated as silence.
SILENCE_PEAK_THRESHOLD = 0.01
SILENCE_RMS_THRESHOLD = 0.001

# Logging constants
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
LOG_LEVEL = "DEBUG"
LOG_FILENAME = "audiby.log"
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 5
LOG_DIRNAME = "logs"

SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v3")
MODEL_DISPLAY_SIZES = {
    "tiny": "74 MB",
    "base": "142 MB",
    "small": "466 MB",
    "medium": "1.5 GB",
    "large-v3": "2.9 GB",
}
MODEL_DOWNLOAD_STATUS_MESSAGE = (
    "This download runs in the background and may take a while depending on "
    "model size and network speed."
)

# Transcription constants
TRANSCRIPTION_BEAM_SIZE = 5

# Whisper receives the raw capture stream, with no automatic gain control of
# the kind comms apps apply. A mic that sounds perfectly normal elsewhere can
# still decode badly here, so peak amplitude is normalized toward a target -
# making accuracy independent of device sensitivity and talking distance.
# Measured: rms 0.0044 decoded "how about now" as "OH"; rms 0.011 was perfect.
AUDIO_TARGET_PEAK = 0.35
# Cap the boost so a near-silent buffer that squeaked past the gate cannot be
# amplified into something VAD mistakes for speech.
AUDIO_MAX_GAIN = 12.0

# Silero VAD strips non-speech regions before decoding. The amplitude gate
# above only catches quiet audio; VAD is what stops loud non-speech (keyboard
# noise, fan, music) from being turned into invented words.
TRANSCRIPTION_VAD_FILTER = True

# Device mode policy for model loading
TRANSCRIPTION_DEVICE_AUTO = "auto"
TRANSCRIPTION_DEVICE_CUDA = "cuda"
TRANSCRIPTION_DEVICE_CPU = "cpu"

# Injection and clipboard constants
INJECTION_PASTE_DELAY = 0.1

# Gap between pressing the paste modifier and tapping "v". Without it the
# target window can occasionally process the "v" before the modifier down
# event, injecting a bare "v" instead of pasting.
INJECTION_MODIFIER_SETTLE_DELAY = 0.02
