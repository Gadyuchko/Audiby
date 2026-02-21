import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from audiby.app import setup_logging

from audiby.config import Config
from audiby.constants import LOG_BACKUP_COUNT, LOG_FORMAT, LOG_MAX_BYTES, LOG_FILENAME, LOG_DIRNAME


def test_setup_logging_configures_rotating_handler(tmp_path) -> None:
    """Logging configures rotating file handler."""
    _logger = logging.getLogger()

    "Clean up logger if something already was there"
    for handler in list(_logger.handlers):
        _logger.removeHandler(handler)
        handler.close()

    "Bootstrap logging"
    _config = Config(config_dir=tmp_path)
    setup_logging(_config)

    assert len(_logger.handlers) >= 1

    rotating_handlers = [h for h in _logger.handlers if isinstance(h, RotatingFileHandler)]

    assert len(rotating_handlers) == 1
    _fileHandler = rotating_handlers[0]

    assert _fileHandler.maxBytes == LOG_MAX_BYTES
    assert _fileHandler.backupCount == LOG_BACKUP_COUNT
    assert _fileHandler.formatter is not None
    assert _fileHandler.formatter._fmt == LOG_FORMAT

    _moduleLogger = logging.getLogger("audiby.config")
    _moduleLogger.info("Test log message")
    _fileHandler.flush()

    _logFilePath = Path(_fileHandler.baseFilename)
    assert _logFilePath.exists()
    assert _logFilePath.parent.exists()
    assert _logFilePath.is_file()

    assert _logFilePath.parent.name == LOG_DIRNAME
    assert _logFilePath.name == LOG_FILENAME


def test_setup_logging_is_idempotent(tmp_path) -> None:
    """Calling setup_logging multiple times is idempotent."""
    _logger = logging.getLogger()
    for handler in list(_logger.handlers):
        _logger.removeHandler(handler)
        handler.close()

    config = Config(config_dir=tmp_path)

    setup_logging(config)
    handlers_1 = [h for h in _logger.handlers if isinstance(h, RotatingFileHandler)]

    setup_logging(config)
    handlers_2 = [h for h in _logger.handlers if isinstance(h, RotatingFileHandler)]

    assert len(handlers_1) == 1
    assert len(handlers_2) == 1
    assert handlers_1[0] is handlers_2[0]