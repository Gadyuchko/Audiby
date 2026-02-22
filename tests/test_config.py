"""Tests for the configuration system."""

import json

from audiby.config import APP_NAME, Config, DEFAULT_CONFIG, get_appdata_path
from audiby.constants import (
    CONFIG_FILENAME,
    CONFIG_KEY_AUDIO_DEVICE,
    CONFIG_KEY_AUTOSTART,
    CONFIG_KEY_HOTKEY,
    CONFIG_KEY_MODEL,
    DEFAULT_AUTOSTART,
    DEFAULT_HOTKEY,
    DEFAULT_MODEL_SIZE,
)


def test_default_config_created(tmp_path):
    """Config creates default file when none exists."""
    config = Config(config_dir=tmp_path)
    config_file = tmp_path / CONFIG_FILENAME
    assert config_file.exists()

    with open(config_file, encoding="utf-8") as f:
        data = json.load(f)

    assert data[CONFIG_KEY_HOTKEY] == DEFAULT_HOTKEY
    assert data[CONFIG_KEY_AUDIO_DEVICE] is None
    assert data[CONFIG_KEY_MODEL] == DEFAULT_MODEL_SIZE
    assert data[CONFIG_KEY_AUTOSTART] == DEFAULT_AUTOSTART


def test_config_directory_creation(tmp_path):
    """Testing config creates nested directories if they don't exist."""
    nested = tmp_path / "deep" / "nested"
    config = Config(config_dir=nested)
    assert (nested / CONFIG_FILENAME).exists()
    assert config.config_dir == nested


def test_config_loading_from_existing_file(tmp_path):
    """Test if config loads values from an existing JSON file that we pre create."""
    config_data = {
        CONFIG_KEY_HOTKEY: "alt+space",
        CONFIG_KEY_AUDIO_DEVICE: 3,
        CONFIG_KEY_MODEL: "small",
        CONFIG_KEY_AUTOSTART: True,
    }
    config_file = tmp_path / CONFIG_FILENAME
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

    config = Config(config_dir=tmp_path)
    assert config.get(CONFIG_KEY_HOTKEY) == "alt+space"
    assert config.get(CONFIG_KEY_AUDIO_DEVICE) == 3
    assert config.get(CONFIG_KEY_MODEL) == "small"
    assert config.get(CONFIG_KEY_AUTOSTART) is True


def test_get_returns_default_for_missing_key(tmp_path):
    """Test if get() returns default when key doesn't exist."""
    config = Config(config_dir=tmp_path)
    assert config.get("nonexistent") is None
    assert config.get("nonexistent", "fallback") == "fallback"


def test_set_and_save_persistence(tmp_path):
    """set() + save() persists changes across instances."""
    config = Config(config_dir=tmp_path)
    config.set(CONFIG_KEY_MODEL, "large-v3")
    config.save()

    config2 = Config(config_dir=tmp_path)
    assert config2.get(CONFIG_KEY_MODEL) == "large-v3"


def test_corrupted_json_resets_to_defaults(tmp_path):
    """Corrupted JSON file is handled gracefully — reset to defaults."""
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text("{invalid json!!!", encoding="utf-8")

    config = Config(config_dir=tmp_path)
    assert config.get(CONFIG_KEY_HOTKEY) == DEFAULT_HOTKEY
    assert config.get(CONFIG_KEY_MODEL) == DEFAULT_MODEL_SIZE

    # File should now contain valid defaults
    with open(config_file, encoding="utf-8") as f:
        data = json.load(f)
    assert data == DEFAULT_CONFIG


def test_forward_compatibility_missing_keys_merged(tmp_path):
    """Existing config with missing keys gets defaults merged in. Testing {**DEFAULT_CONFIG, **loaded}"""
    partial = {CONFIG_KEY_HOTKEY: "alt+space"}
    config_file = tmp_path / CONFIG_FILENAME
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(partial, f)

    config = Config(config_dir=tmp_path)
    assert config.get(CONFIG_KEY_HOTKEY) == "alt+space"
    assert config.get(CONFIG_KEY_MODEL) == DEFAULT_MODEL_SIZE
    assert config.get(CONFIG_KEY_AUDIO_DEVICE) is None
    assert config.get(CONFIG_KEY_AUTOSTART) == DEFAULT_AUTOSTART


def test_non_object_json_resets_to_defaults(tmp_path):
    """Valid non-object JSON payload is treated as invalid config shape."""
    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text('["not", "an", "object"]', encoding="utf-8")

    config = Config(config_dir=tmp_path)
    assert config.get(CONFIG_KEY_HOTKEY) == DEFAULT_HOTKEY
    assert config.get(CONFIG_KEY_MODEL) == DEFAULT_MODEL_SIZE

    with open(config_file, encoding="utf-8") as f:
        data = json.load(f)
    assert data == DEFAULT_CONFIG


def test_get_appdata_path_uses_local_dev_override_when_enabled(monkeypatch, tmp_path):
    """Explicit dev flag uses repo-local temporary appdata folder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUDIBY_DEV_APPDATA", "1")

    assert get_appdata_path() == (tmp_path / ".tmp-appdata" / APP_NAME)
