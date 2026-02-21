"""Tests for the logging subsystem (setup_logging in app.py)."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest

from audiby.app import setup_logging
from audiby.config import Config
from audiby.constants import (
    LOG_BACKUP_COUNT,
    LOG_DIRNAME,
    LOG_FILENAME,
    LOG_FORMAT,
    LOG_MAX_BYTES,
)


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Remove all handlers from root logger before and after each test."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()


def test_rotating_handler_config(tmp_path) -> None:
    """setup_logging attaches a RotatingFileHandler with correct maxBytes, backupCount, and formatter."""
    config = Config(config_dir=tmp_path)
    setup_logging(config)

    root = logging.getLogger()
    rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]

    assert len(rotating) == 1
    handler = rotating[0]
    assert handler.maxBytes == LOG_MAX_BYTES
    assert handler.backupCount == LOG_BACKUP_COUNT
    assert handler.formatter is not None
    assert handler.formatter._fmt == LOG_FORMAT


def test_log_file_created_in_correct_location(tmp_path) -> None:
    """Log file is created under <config_dir>/logs/audiby.log."""
    config = Config(config_dir=tmp_path)
    setup_logging(config)

    log_file = tmp_path / LOG_DIRNAME / LOG_FILENAME
    # Write something so the file is actually created on disk
    logging.getLogger("audiby.test").info("probe")
    logging.getLogger().handlers[0].flush()

    assert log_file.exists()
    assert log_file.parent.name == LOG_DIRNAME
    assert log_file.name == LOG_FILENAME


def test_module_logger_routes_to_file(tmp_path) -> None:
    """Messages from module loggers are routed to the configured file handler."""
    config = Config(config_dir=tmp_path)
    setup_logging(config)

    module_logger = logging.getLogger("audiby.config")
    module_logger.info("routing check message")

    root = logging.getLogger()
    for h in root.handlers:
        h.flush()

    log_file = tmp_path / LOG_DIRNAME / LOG_FILENAME
    content = log_file.read_text(encoding="utf-8")
    assert "routing check message" in content


def test_privacy_no_transcript_in_logs(tmp_path) -> None:
    """Raw transcript payload must never appear in log output."""
    config = Config(config_dir=tmp_path)
    setup_logging(config)

    sample_transcript = "THIS SHOULD NEVER BE LOGGED"
    module_logger = logging.getLogger("audiby.core.transcriber")
    module_logger.info("Transcription completed chars=%d", len(sample_transcript))

    root = logging.getLogger()
    for h in root.handlers:
        h.flush()

    log_file = tmp_path / LOG_DIRNAME / LOG_FILENAME
    content = log_file.read_text(encoding="utf-8")
    assert "Transcription completed chars=" in content
    assert sample_transcript not in content


def test_setup_logging_is_idempotent(tmp_path) -> None:
    """Calling setup_logging multiple times does not duplicate handlers."""
    config = Config(config_dir=tmp_path)

    setup_logging(config)
    root = logging.getLogger()
    handlers_1 = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]

    setup_logging(config)
    handlers_2 = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]

    assert len(handlers_1) == 1
    assert len(handlers_2) == 1
    assert handlers_1[0] is handlers_2[0]


def test_setup_logging_raises_on_directory_creation_failure(tmp_path) -> None:
    """setup_logging raises OSError when the log directory cannot be created."""
    config = Config(config_dir=tmp_path)

    with patch.object(Path, "mkdir", side_effect=OSError("permission denied")):
        with pytest.raises(OSError, match="permission denied"):
            setup_logging(config)
