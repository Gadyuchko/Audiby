"""Behavior tests for model manager path resolution and existence checks."""

from pathlib import Path

import pytest

from audiby.core import model_manager
from audiby.exceptions import ModelError

_MODEL_BIN = "model.bin"


@pytest.fixture
def fake_model_appdata(monkeypatch, tmp_path) -> Path:
    """Patch the platform.paths.models_dir helper to a deterministic test path.

    Returns the simulated app-data root; the models directory itself sits at
    ``<root>/models`` to mirror the real layout.
    """
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


# ---------------------------------------------------------------------------
# get_model_root
# ---------------------------------------------------------------------------


def test_get_model_root_returns_path(fake_model_appdata):
    """get_model_root() returns a pathlib.Path object."""
    result = model_manager.get_model_root()

    assert isinstance(result, Path)


def test_get_model_root_appends_models_directory(fake_model_appdata):
    """get_model_root() appends the canonical models directory name."""
    result = model_manager.get_model_root()

    assert result == fake_model_appdata / "models"


def test_get_model_root_uses_platform_models_dir(monkeypatch, tmp_path):
    """get_model_root() composes from audiby.platform.paths.models_dir()."""
    fake_models_root = tmp_path / "Audiby" / "models"
    calls = {"count": 0}

    def fake_models_dir() -> Path:
        calls["count"] += 1
        fake_models_root.mkdir(parents=True, exist_ok=True)
        return fake_models_root

    monkeypatch.setattr(
        "audiby.core.model_manager.models_dir",
        fake_models_dir,
    )

    result = model_manager.get_model_root()

    assert result == fake_models_root
    assert calls["count"] == 1


def test_get_model_root_creates_models_directory(fake_model_appdata):
    """get_model_root() ensures the models directory exists per platform.paths contract."""
    result = model_manager.get_model_root()

    assert result == fake_model_appdata / "models"
    assert result.exists()
    assert result.is_dir()


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


def test_exists_returns_true_when_model_binary_present(fake_model_appdata):
    """exists() returns True when model.bin exists inside the model directory."""
    model_dir = fake_model_appdata / "models" / "base"
    model_dir.mkdir(parents=True)
    (model_dir / _MODEL_BIN).touch()

    assert model_manager.exists("base") is True


def test_exists_returns_false_when_model_directory_is_missing(fake_model_appdata):
    """exists() returns False when the expected model directory is absent."""
    assert model_manager.exists("base") is False


def test_exists_returns_false_when_directory_exists_but_model_bin_missing(fake_model_appdata):
    """exists() returns False when the model directory exists but model.bin is absent."""
    (fake_model_appdata / "models" / "base").mkdir(parents=True)

    assert model_manager.exists("base") is False


def test_exists_does_not_create_model_subdirectory(fake_model_appdata):
    """exists() does not create the per-model subdirectory inside models/."""
    model_dir = fake_model_appdata / "models" / "base"

    assert model_manager.exists("base") is False
    assert not model_dir.exists()


def test_exists_normalizes_supported_model_name(fake_model_appdata):
    """exists() sanitizes supported model names (trim/case-normalize)."""
    model_dir = fake_model_appdata / "models" / "base"
    model_dir.mkdir(parents=True)
    (model_dir / _MODEL_BIN).touch()

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


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


def _make_fake_download_model(fake_model_appdata, calls: dict, *, create_bin: bool = True):
    """Return a fake download_model that simulates the faster-whisper download side effect."""

    def fake_download_model(model_size_or_path, output_dir=None, **kwargs):
        calls["model"] = model_size_or_path
        calls["output_dir"] = output_dir
        if output_dir is not None:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            if create_bin:
                (Path(output_dir) / _MODEL_BIN).touch()

    return fake_download_model


def test_download_uses_download_model_with_output_dir(monkeypatch, fake_model_appdata):
    """download() delegates to faster-whisper download_model using output_dir."""
    calls = {}
    monkeypatch.setattr(
        model_manager,
        "download_model",
        _make_fake_download_model(fake_model_appdata, calls),
        raising=False,
    )

    result = model_manager.download("base")

    assert calls["model"] == "base"
    assert calls["output_dir"] == str(fake_model_appdata / "models" / "base")
    assert result == fake_model_appdata / "models" / "base"


def test_download_normalizes_supported_model_name(monkeypatch, fake_model_appdata):
    """download() reuses the same model-name validation/sanitization behavior."""
    calls = {}
    monkeypatch.setattr(
        model_manager,
        "download_model",
        _make_fake_download_model(fake_model_appdata, calls),
        raising=False,
    )

    result = model_manager.download(" Base ")

    assert calls["model"] == "base"
    assert result == fake_model_appdata / "models" / "base"


def test_download_wraps_library_errors_in_model_error(monkeypatch, fake_model_appdata):
    """download() surfaces library OSError as ModelError."""

    def fake_download_model(model_size_or_path, output_dir=None, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(model_manager, "download_model", fake_download_model, raising=False)

    with pytest.raises(ModelError):
        model_manager.download("base")


def test_download_raises_model_error_if_model_bin_missing_after_library_call(
    monkeypatch, fake_model_appdata
):
    """download() must not report success if model.bin is absent after the library call."""
    calls = {}
    monkeypatch.setattr(
        model_manager,
        "download_model",
        _make_fake_download_model(fake_model_appdata, calls, create_bin=False),
        raising=False,
    )

    with pytest.raises(ModelError):
        model_manager.download("base")


def test_download_raises_model_error_for_empty_model_name(fake_model_appdata):
    """download() rejects empty model names."""
    with pytest.raises(ModelError):
        model_manager.download("   ")


def test_download_raises_model_error_for_path_traversal_like_name(fake_model_appdata):
    """download() rejects unsafe path-like model names."""
    with pytest.raises(ModelError):
        model_manager.download("../base")


def test_download_raises_model_error_for_unsupported_model(fake_model_appdata):
    """download() rejects model names not in the supported allowlist."""
    with pytest.raises(ModelError):
        model_manager.download("not-a-model")
