"""Model lifecycle helpers for faster-whisper downloads and local presence checks."""

import logging
from pathlib import Path

from faster_whisper import download_model

from audiby.constants import DEFAULT_MODEL_SIZE, SUPPORTED_MODELS
from audiby.exceptions import ModelError
from audiby.platform.paths import models_dir
from audiby.resources import resource_path

logger = logging.getLogger(__name__)

MODEL_BINARY = "model.bin"


def get_model_root() -> Path:
    """Return the canonical local directory used to store Whisper models."""
    model_root = models_dir()
    logger.debug("Resolved model root directory: %s", model_root)
    return model_root


def bundled_model_path(model_name: str) -> Path:
    """Return the bundled model path for supported default models."""
    normalized = _normalize_model_name(model_name)
    return resource_path(Path("models") / normalized)


def resolve_model_path(model_name: str) -> Path:
    """Return the model path, preferring bundled base over user storage."""
    normalized = _normalize_model_name(model_name)
    bundled_path = bundled_model_path(normalized)
    if normalized == DEFAULT_MODEL_SIZE and (bundled_path / MODEL_BINARY).is_file():
        return bundled_path
    return get_model_root() / normalized


def _normalize_model_name(model_name: str) -> str:
    """Normalize and validate a model name for filesystem-safe local use."""
    normalized = model_name.strip().lower()

    if not normalized:
        raise ModelError("Model name cannot be empty")

    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise ModelError(f"Invalid model name: {model_name}")

    if normalized not in SUPPORTED_MODELS:
        raise ModelError(f"Unsupported model name: {model_name}")

    return normalized


def exists(model_name: str) -> bool:
    """Return True if a complete model download exists at the expected local path."""
    normalized = _normalize_model_name(model_name)
    model_path = resolve_model_path(normalized)
    return (model_path / MODEL_BINARY).is_file()


def download(model_name: str, root: Path | None = None) -> Path:
    """Download a Whisper model via faster-whisper and return its local path."""
    normalized = _normalize_model_name(model_name)
    model_root = Path(root) if root is not None else get_model_root()
    model_path = model_root / normalized

    logger.info("Downloading model %s to %s", normalized, model_path)

    try:
        download_model(normalized, output_dir=str(model_path))
    except (OSError, ValueError) as exc:
        logger.error("Failed to download model %s: %s", normalized, exc)
        raise ModelError(f"Failed to download model {normalized}: {exc}") from exc

    if not (model_path / MODEL_BINARY).is_file():
        raise ModelError(
            f"Model {normalized} download incomplete: {MODEL_BINARY} missing in {model_path}"
        )

    logger.info("Model %s is available at %s", normalized, model_path)
    return model_path
