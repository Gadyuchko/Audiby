"""Behavior tests for cross-platform runtime data path resolution."""

from pathlib import Path

import pytest

from audiby.constants import APP_NAME, CONFIG_FILENAME, LOG_DIRNAME
from audiby.platform import paths as paths_module


@pytest.fixture
def isolated_home(monkeypatch, tmp_path) -> Path:
    """Force Path.home() to a deterministic location for non-Windows branches."""
    monkeypatch.setattr(paths_module.Path, "home", lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# app_data_dir
# ---------------------------------------------------------------------------


def test_app_data_dir_windows_uses_appdata_env(monkeypatch, tmp_path):
    """Windows branch composes from %APPDATA% / APP_NAME."""
    appdata_root = tmp_path / "Roaming"
    monkeypatch.setattr(paths_module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata_root))

    result = paths_module.app_data_dir()

    assert result == appdata_root / APP_NAME
    assert result.exists()
    assert result.is_dir()


def test_app_data_dir_windows_falls_back_to_home_when_appdata_missing(monkeypatch, tmp_path):
    """Windows branch falls back to home when %APPDATA% is unset."""
    monkeypatch.setattr(paths_module.sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(paths_module.Path, "home", lambda: tmp_path)

    result = paths_module.app_data_dir()

    assert result == tmp_path / APP_NAME
    assert result.exists()


def test_app_data_dir_darwin_uses_library_application_support(monkeypatch, isolated_home):
    """macOS branch uses ~/Library/Application Support/Audiby."""
    monkeypatch.setattr(paths_module.sys, "platform", "darwin")

    result = paths_module.app_data_dir()

    assert result == isolated_home / "Library" / "Application Support" / APP_NAME
    assert result.exists()
    assert result.is_dir()


def test_app_data_dir_linux_fallback_uses_local_share(monkeypatch, isolated_home):
    """Non-windows / non-darwin platforms use ~/.local/share/Audiby."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    result = paths_module.app_data_dir()

    assert result == isolated_home / ".local" / "share" / APP_NAME
    assert result.exists()


def test_app_data_dir_returns_pathlib_path(monkeypatch, isolated_home):
    """Helper returns pathlib.Path, not str."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    result = paths_module.app_data_dir()

    assert isinstance(result, Path)


def test_app_data_dir_idempotent_when_directory_already_exists(monkeypatch, isolated_home):
    """Calling helper twice does not fail when directory already exists."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    first = paths_module.app_data_dir()
    second = paths_module.app_data_dir()

    assert first == second
    assert first.exists()


# ---------------------------------------------------------------------------
# models_dir
# ---------------------------------------------------------------------------


def test_models_dir_composes_from_app_data_dir(monkeypatch, isolated_home):
    """models_dir() == app_data_dir() / 'models'."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    result = paths_module.models_dir()

    expected = isolated_home / ".local" / "share" / APP_NAME / "models"
    assert result == expected
    assert result.exists()
    assert result.is_dir()


def test_models_dir_returns_pathlib_path(monkeypatch, isolated_home):
    """models_dir() returns pathlib.Path."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    assert isinstance(paths_module.models_dir(), Path)


# ---------------------------------------------------------------------------
# config_path
# ---------------------------------------------------------------------------


def test_config_path_returns_file_inside_app_data_dir(monkeypatch, isolated_home):
    """config_path() == app_data_dir() / CONFIG_FILENAME."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    result = paths_module.config_path()

    expected = isolated_home / ".local" / "share" / APP_NAME / CONFIG_FILENAME
    assert result == expected


def test_config_path_creates_parent_directory(monkeypatch, isolated_home):
    """config_path() ensures the parent app data directory exists."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    result = paths_module.config_path()

    assert result.parent.exists()
    assert result.parent.is_dir()


def test_config_path_does_not_create_the_file_itself(monkeypatch, isolated_home):
    """config_path() resolves the path only and does not create the JSON file."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    result = paths_module.config_path()

    assert not result.exists()


# ---------------------------------------------------------------------------
# logs_dir
# ---------------------------------------------------------------------------


def test_logs_dir_composes_from_app_data_dir(monkeypatch, isolated_home):
    """logs_dir() == app_data_dir() / LOG_DIRNAME."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    result = paths_module.logs_dir()

    expected = isolated_home / ".local" / "share" / APP_NAME / LOG_DIRNAME
    assert result == expected
    assert result.exists()
    assert result.is_dir()


def test_logs_dir_returns_pathlib_path(monkeypatch, isolated_home):
    """logs_dir() returns pathlib.Path."""
    monkeypatch.setattr(paths_module.sys, "platform", "linux")

    assert isinstance(paths_module.logs_dir(), Path)


# ---------------------------------------------------------------------------
# Cross-helper consistency
# ---------------------------------------------------------------------------


def test_helpers_share_same_root_on_each_platform(monkeypatch, isolated_home):
    """All helpers compose on top of the same app_data_dir() result."""
    monkeypatch.setattr(paths_module.sys, "platform", "darwin")

    root = paths_module.app_data_dir()

    assert paths_module.models_dir().parent == root
    assert paths_module.config_path().parent == root
    assert paths_module.logs_dir().parent == root
