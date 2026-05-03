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

# Device mode policy for model loading
TRANSCRIPTION_DEVICE_AUTO = "auto"
TRANSCRIPTION_DEVICE_CUDA = "cuda"
TRANSCRIPTION_DEVICE_CPU = "cpu"

# Injection and clipboard constants
INJECTION_PASTE_DELAY = 0.1
