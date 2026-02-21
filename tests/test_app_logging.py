import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from audiby.app import setup_logging
from audiby.config import Config
from audiby.constants import (
    LOG_BACKUP_COUNT,
    LOG_DIRNAME,
    LOG_FILENAME,
    LOG_FORMAT,
    LOG_MAX_BYTES,
)


def test_setup_logging_configures_rotating_handler(tmp_path) -> None:
    """Logging configures rotating file handler."""
    logger = logging.getLogger()

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    config = Config(config_dir=tmp_path)
    setup_logging(config)

    assert len(logger.handlers) >= 1

    rotating_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]

    assert len(rotating_handlers) == 1
    file_handler = rotating_handlers[0]

    assert file_handler.maxBytes == LOG_MAX_BYTES
    assert file_handler.backupCount == LOG_BACKUP_COUNT
    assert file_handler.formatter is not None
    assert file_handler.formatter._fmt == LOG_FORMAT

    module_logger = logging.getLogger("audiby.config")
    module_logger.info("Test log message")
    sample_transcript = "THIS SHOULD NEVER BE LOGGED"
    module_logger.info("Transcription completed chars=%d", len(sample_transcript))
    file_handler.flush()

    log_file_path = Path(file_handler.baseFilename)
    assert log_file_path.exists()
    assert log_file_path.parent.exists()
    assert log_file_path.is_file()

    assert log_file_path.parent.name == LOG_DIRNAME
    assert log_file_path.name == LOG_FILENAME

    content = log_file_path.read_text(encoding="utf-8")
    assert "Test log message" in content
    assert "Transcription completed chars=" in content
    assert sample_transcript not in content


def test_setup_logging_is_idempotent(tmp_path) -> None:
    """Calling setup_logging multiple times is idempotent."""
    logger = logging.getLogger()
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    config = Config(config_dir=tmp_path)

    setup_logging(config)
    handlers_1 = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]

    setup_logging(config)
    handlers_2 = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]

    assert len(handlers_1) == 1
    assert len(handlers_2) == 1
    assert handlers_1[0] is handlers_2[0]
