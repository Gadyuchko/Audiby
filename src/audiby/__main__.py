"""Audiby entry point - local voice-to-text with push-to-talk."""

import sys

from audiby.app import run_app
from audiby.config import Config
from audiby.constants import APP_NAME
from audiby.core import model_manager
from audiby.exceptions import ModelError


def main() -> int:
    """Application entry point."""
    args = sys.argv[1:]

    if "--setup-model" in args:
        try:
            model_name = args[args.index("--setup-model") + 1]
        except IndexError:
            print("Missing model name after --setup-model")
            return 1

        try:
            model_path = model_manager.download(model_name)
        except ModelError as exc:
            print(f"Model setup failed: {exc}")
            return 1

        print(f"Model downloaded to {model_path}")
        return 0

    print(f"{APP_NAME} v0.1.0 - starting up...")
    config = Config()
    run_app(config)
    print(f"Config loaded from {config.config_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
