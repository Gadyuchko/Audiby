"""Behavior tests for model manager path resolution and existence checks."""

from pathlib import Path

import pytest

from audiby.core import model_manager
from audiby.exceptions import ModelError


@pytest.fixture
def fake_model_appdata(monkeypatch, tmp_path) -> Path:
    """Patch model_manager appdata resolver to a deterministic test path."""
    fake_appdata = tmp_path / "Audiby"

    monkeypatch.setattr(
        "audiby.core.model_manager.get_appdata_path",
        lambda: fake_appdata,
    )
    return fake_appdata


def test_get_model_root_returns_path(fake_model_appdata):
    """get_model_root() returns a pathlib.Path object."""
    result = model_manager.get_model_root()

    assert isinstance(result, Path)


def test_get_model_root_appends_models_directory(fake_model_appdata):
    """get_model_root() appends the canonical models directory name."""
    result = model_manager.get_model_root()

    assert result == fake_model_appdata / "models"


def test_get_model_root_uses_config_appdata_path(monkeypatch, tmp_path):
    """get_model_root() composes from audiby.config.get_appdata_path()."""
    fake_appdata = tmp_path / "Audiby"
    calls = {"count": 0}

    def fake_get_appdata_path() -> Path:
        calls["count"] += 1
        return fake_appdata

    monkeypatch.setattr(
        "audiby.core.model_manager.get_appdata_path",
        fake_get_appdata_path,
    )

    result = model_manager.get_model_root()

    assert result == fake_appdata / "models"
    assert calls["count"] == 1


def test_get_model_root_does_not_create_directory(fake_model_appdata):
    """get_model_root() resolves path only and does not create directories."""
    result = model_manager.get_model_root()

    assert result == fake_model_appdata / "models"
    assert not fake_model_appdata.exists()
    assert not result.exists()


def test_exists_returns_true_when_model_directory_exists(fake_model_appdata):
    """exists() returns True when the expected model directory is present."""
    (fake_model_appdata / "models" / "base").mkdir(parents=True)

    assert model_manager.exists("base") is True


def test_exists_returns_false_when_model_directory_is_missing(fake_model_appdata):
    """exists() returns False when the expected model directory is absent."""
    assert model_manager.exists("base") is False


def test_exists_does_not_create_model_directory(fake_model_appdata):
    """exists() performs a check only and does not create model directories."""
    model_dir = fake_model_appdata / "models" / "base"

    assert model_manager.exists("base") is False
    assert not model_dir.exists()


def test_exists_normalizes_supported_model_name(fake_model_appdata):
    """exists() sanitizes supported model names (trim/case-normalize)."""
    (fake_model_appdata / "models" / "base").mkdir(parents=True)

    assert model_manager.exists(" Base ") is True


def test_exists_raises_model_error_for_unsupported_model(fake_model_appdata):
    """exists() rejects unsupported model names for MVP allowlist."""
    with pytest.raises(ModelError):
        model_manager.exists("not-a-model")


def test_exists_raises_model_error_for_empty_model_name(fake_model_appdata):
    """exists() rejects empty model names after sanitization."""
    with pytest.raises(ModelError):
        model_manager.exists("   ")


def test_exists_raises_model_error_for_path_traversal_like_name(fake_model_appdata):
    """exists() rejects unsafe path-like model names."""
    with pytest.raises(ModelError):
        model_manager.exists("../base")


def test_download_uses_whisper_model_with_download_root(monkeypatch, fake_model_appdata):
    """download() delegates to faster-whisper using download_root under model root."""
    calls = {}

    class FakeWhisperModel:
        def __init__(self, model_size_or_path, **kwargs):
            calls["model"] = model_size_or_path
            calls["kwargs"] = kwargs
            # Simulate faster-whisper side effect: downloaded model directory now exists.
            Path(kwargs["download_root"]).mkdir(parents=True, exist_ok=True)
            (Path(kwargs["download_root"]) / model_size_or_path).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(model_manager, "WhisperModel", FakeWhisperModel, raising=False)

    result = model_manager.download("base")

    assert calls["model"] == "base"
    assert calls["kwargs"]["download_root"] == str(fake_model_appdata / "models")
    assert result == fake_model_appdata / "models" / "base"


def test_download_normalizes_supported_model_name(monkeypatch, fake_model_appdata):
    """download() reuses the same model-name validation/sanitization behavior."""
    calls = {}

    class FakeWhisperModel:
        def __init__(self, model_size_or_path, **kwargs):
            calls["model"] = model_size_or_path
            Path(kwargs["download_root"]).mkdir(parents=True, exist_ok=True)
            (Path(kwargs["download_root"]) / model_size_or_path).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(model_manager, "WhisperModel", FakeWhisperModel, raising=False)

    result = model_manager.download(" Base ")

    assert calls["model"] == "base"
    assert result == fake_model_appdata / "models" / "base"


def test_download_wraps_library_errors_in_model_error(monkeypatch, fake_model_appdata):
    """download() surfaces library failures as ModelError."""

    class FakeWhisperModel:
        def __init__(self, model_size_or_path, **kwargs):
            raise RuntimeError("download failed")

    monkeypatch.setattr(model_manager, "WhisperModel", FakeWhisperModel, raising=False)

    with pytest.raises(ModelError):
        model_manager.download("base")


def test_download_raises_model_error_if_model_still_missing_after_library_call(
    monkeypatch, fake_model_appdata
):
    """download() must not report success if expected model directory is still missing."""

    class FakeWhisperModel:
        def __init__(self, model_size_or_path, **kwargs):
            # Simulate library call returning without creating expected model dir.
            Path(kwargs["download_root"]).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(model_manager, "WhisperModel", FakeWhisperModel, raising=False)

    with pytest.raises(ModelError):
        model_manager.download("base")
