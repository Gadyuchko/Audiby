"""Cross-platform runtime data path resolution.

Single source of truth for where Audiby stores user-level runtime data
(config.json, downloaded models, log files). All consumers must compose
their paths from these helpers instead of branching on ``sys.platform``
themselves.
"""

import os
import sys
from pathlib import Path

from audiby.constants import APP_NAME, CONFIG_FILENAME, LOG_DIRNAME

_MODELS_SUBDIR = "models"


def app_data_dir() -> Path:
    """Return the per-user runtime data root for Audiby, creating it if missing.

    Layout:
        win32  -> ``%APPDATA%/Audiby`` (falls back to ``~/Audiby`` if APPDATA unset)
        darwin -> ``~/Library/Application Support/Audiby``
        other  -> ``~/.local/share/Audiby``
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        root = base / APP_NAME
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        root = Path.home() / ".local" / "share" / APP_NAME

    root.mkdir(parents=True, exist_ok=True)
    return root


def models_dir() -> Path:
    """Return the user-managed Whisper model directory, creating it if missing."""
    directory = app_data_dir() / _MODELS_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_path() -> Path:
    """Return the path to ``config.json``, ensuring the parent directory exists."""
    return app_data_dir() / CONFIG_FILENAME


def logs_dir() -> Path:
    """Return the rotating log directory, creating it if missing."""
    directory = app_data_dir() / LOG_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory
