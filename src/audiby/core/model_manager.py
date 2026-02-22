"""Model lifecycle helpers for faster-whisper downloads and local presence checks.

Privacy guardrail: logs must never include audio or transcript payload data.
Only model lifecycle metadata (name/path/success-failure) may be logged.
"""

import logging
from pathlib import Path

from faster_whisper import WhisperModel

from audiby.config import get_appdata_path
from audiby.constants import SUPPORTED_MODELS
from audiby.exceptions import ModelError

logger = logging.getLogger(__name__)


def get_model_root() -> Path:
    """Return the canonical local directory used to store Whisper models."""
    app_data_directory = get_appdata_path()
    model_root = app_data_directory / "models"
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
    """Return True if the expected local model directory already exists."""
    normalized = _normalize_model_name(model_name)
    model_path = get_model_root() / normalized
    return model_path.exists() and model_path.is_dir()


def download(model_name: str) -> Path:
    """Download a Whisper model via faster-whisper and return its local path."""
    normalized = _normalize_model_name(model_name)
    download_root = get_model_root()
    model_path = download_root / normalized

    logger.info("Downloading model %s to %s", normalized, download_root)

    # faster-whisper downloads models as a side effect of model initialization.
    try:
        WhisperModel(normalized, download_root=str(download_root))
    except (RuntimeError, OSError, ValueError) as exc:
        logger.error("Failed to download model %s: %s", normalized, exc)
        raise ModelError(f"Failed to download model {normalized}: {exc}") from exc

    if not model_path.exists() or not model_path.is_dir():
        raise ModelError(f"Model {normalized} not found in {model_path}")

    logger.info("Model %s is available at %s", normalized, model_path)
    return model_path
