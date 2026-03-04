"""Application configuration — load/save JSON settings."""

import json
import logging
import os
import sys
from pathlib import Path

from audiby.constants import (
    ALT_NEUTRALIZATION_TAP_ALT,
    APP_NAME,
    CONFIG_FILENAME,
    CONFIG_KEY_ALT_NEUTRALIZATION,
    CONFIG_KEY_AUDIO_DEVICE,
    CONFIG_KEY_AUTOSTART,
    CONFIG_KEY_HOTKEY,
    CONFIG_KEY_MODEL,
    DEFAULT_AUDIO_DEVICE,
    DEFAULT_AUTOSTART,
    DEFAULT_HOTKEY,
    DEFAULT_MODEL_SIZE,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict = {
    CONFIG_KEY_HOTKEY: DEFAULT_HOTKEY,
    CONFIG_KEY_AUDIO_DEVICE: DEFAULT_AUDIO_DEVICE,
    CONFIG_KEY_MODEL: DEFAULT_MODEL_SIZE,
    CONFIG_KEY_AUTOSTART: DEFAULT_AUTOSTART,
    CONFIG_KEY_ALT_NEUTRALIZATION: ALT_NEUTRALIZATION_TAP_ALT,
}


def get_appdata_path() -> Path:
    """Resolve the application data directory for config storage."""
    if os.environ.get("AUDIBY_DEV_APPDATA", "").lower() in {"1", "true", "yes", "on"}:
        return (Path.cwd() / ".tmp-appdata" / APP_NAME)

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path.home() / ".config"
    return base / APP_NAME


class Config:
    """Application configuration — load/save JSON settings."""

    def __init__(self, config_dir: Path | None = None) -> None:
        """Initialize config. If config_dir provided, use it (for testing)."""
        self._config_dir = config_dir or get_appdata_path()
        self._config_path = self._config_dir / CONFIG_FILENAME
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        """Load config from disk. Create defaults if missing or corrupted."""
        if not self._config_path.exists():
            logger.info("No config file found at %s — creating defaults", self._config_path)
            self._data = dict(DEFAULT_CONFIG)
            self._config_dir.mkdir(parents=True, exist_ok=True)
            self.save()
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupted config at %s (%s) — resetting to defaults", self._config_path, exc)
            self._data = dict(DEFAULT_CONFIG)
            self.save()
            return


        if not isinstance(loaded, dict):
            logger.warning(
                "Invalid config shape at %s (expected object, got %s) - resetting to defaults",
                self._config_path,
                type(loaded).__name__,
            )
            self._data = dict(DEFAULT_CONFIG)
            self.save()
            return
        # Merge missing keys from defaults (loaded keys take precedence)
        self._data = {**DEFAULT_CONFIG, **loaded}

    def get(self, key: str, default=None):
        """Read a config value."""
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        """Update a config value in memory."""
        self._data[key] = value

    def save(self) -> None:
        """Persist config to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    @property
    def config_dir(self) -> Path:
        """Return the config directory path."""
        return self._config_dir
