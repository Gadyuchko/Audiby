"""Integration tests for model_manager — perform real network downloads.

These tests are skipped by default. Run with:
    pytest --run-integration

Only the "tiny" model is tested to minimise download time (~75 MB).
"""

from pathlib import Path

import pytest

from audiby.core import model_manager

pytestmark = pytest.mark.integration

_MODEL_BIN = "model.bin"


@pytest.fixture
def isolated_model_root(monkeypatch, tmp_path) -> Path:
    """Redirect model storage to a temp directory so real AppData is never touched."""
    fake_appdata = tmp_path / "Audiby"

    def fake_models_dir() -> Path:
        directory = fake_appdata / "models"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    monkeypatch.setattr(
        "audiby.core.model_manager.models_dir",
        fake_models_dir,
    )
    return fake_appdata


@pytest.mark.parametrize("model_name", ["tiny"])
def test_exists_returns_false_before_download(model_name, isolated_model_root):
    """exists() returns False when no model has been downloaded yet."""
    assert model_manager.exists(model_name) is False


@pytest.mark.parametrize("model_name", ["tiny"])
def test_download_returns_correct_path(model_name, isolated_model_root):
    """download() returns a Path pointing to the correct local model directory."""
    expected = isolated_model_root / "models" / model_name

    result = model_manager.download(model_name)

    assert result == expected


@pytest.mark.parametrize("model_name", ["tiny"])
def test_download_creates_model_binary(model_name, isolated_model_root):
    """download() results in model.bin present inside the model directory."""
    result = model_manager.download(model_name)

    assert (result / _MODEL_BIN).is_file()


@pytest.mark.parametrize("model_name", ["tiny"])
def test_exists_returns_true_after_download(model_name, isolated_model_root):
    """exists() returns True immediately after a successful download."""
    model_manager.download(model_name)

    assert model_manager.exists(model_name) is True


@pytest.mark.parametrize("model_name", ["tiny"])
def test_download_and_exists_full_roundtrip(model_name, isolated_model_root):
    """Full lifecycle: not present → download → present, path consistent."""
    assert not model_manager.exists(model_name)

    path = model_manager.download(model_name)

    assert path.is_dir()
    assert (path / _MODEL_BIN).is_file()
    assert model_manager.exists(model_name)
    assert path == isolated_model_root / "models" / model_name
