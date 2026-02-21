"""Application orchestrator placeholder for pipeline wiring."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from audiby.config import Config
from audiby.constants import (
    LOG_BACKUP_COUNT,
    LOG_DIRNAME,
    LOG_FILENAME,
    LOG_FORMAT,
    LOG_LEVEL,
    LOG_MAX_BYTES,
)

logger = logging.getLogger(__name__)


def run_app(config: Config) -> None:
    """Accept app config and reserve orchestration wiring for future stories."""
    log_file = setup_logging(config)
    logger.info(
        "Logging initialized at %s (maxBytes=%s, backupCount=%s)",
        log_file,
        LOG_MAX_BYTES,
        LOG_BACKUP_COUNT,
    )


def setup_logging(config: Config) -> Path:
    """Configure logging."""
    log_dir = config.config_dir / LOG_DIRNAME
    log_file = log_dir / LOG_FILENAME

    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()

    file_handler = None

    rotating_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
    for handler in rotating_handlers:
        if Path(handler.baseFilename) == log_file:
            file_handler = handler
            break

    if file_handler is None:
        file_handler = RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(file_handler)

    root_logger.setLevel(getattr(logging, LOG_LEVEL))

    return log_file
