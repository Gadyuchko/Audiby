"""Model lifecycle helpers for faster-whisper downloads and local presence checks."""

import logging
from pathlib import Path

from faster_whisper import download_model

from audiby.constants import SUPPORTED_MODELS
from audiby.exceptions import ModelError
from audiby.platform.paths import models_dir

logger = logging.getLogger(__name__)

_MODEL_BINARY = "model.bin"


def get_model_root() -> Path:
    """Return the canonical local directory used to store Whisper models."""
    model_root = models_dir()
    logger.debug("Resolved model root directory: %s", model_root)
    return model_root


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
    model_path = get_model_root() / normalized
    return (model_path / _MODEL_BINARY).is_file()


def download(model_name: str) -> Path:
    """Download a Whisper model via faster-whisper and return its local path."""
    normalized = _normalize_model_name(model_name)
    model_path = get_model_root() / normalized

    logger.info("Downloading model %s to %s", normalized, model_path)

    try:
        download_model(normalized, output_dir=str(model_path))
    except (OSError, ValueError) as exc:
        logger.error("Failed to download model %s: %s", normalized, exc)
        raise ModelError(f"Failed to download model {normalized}: {exc}") from exc

    if not (model_path / _MODEL_BINARY).is_file():
        raise ModelError(
            f"Model {normalized} download incomplete: {_MODEL_BINARY} missing in {model_path}"
        )

    logger.info("Model %s is available at %s", normalized, model_path)
    return model_path
