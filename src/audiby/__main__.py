"""Audiby entry point - local voice-to-text with push-to-talk."""

import sys

from audiby.app import run_app
from audiby.config import Config
from audiby.constants import APP_NAME


def main() -> int:
    """Application entry point."""
    print(f"{APP_NAME} v0.1.0 - starting up...")
    config = Config()
    run_app(config)
    print(f"Config loaded from {config.config_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
