"""Audiby entry point - local voice-to-text with push-to-talk."""

import multiprocessing
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from audiby.app import run_app
from audiby.config import Config
from audiby.constants import APP_NAME
from audiby.core import model_manager
from audiby.exceptions import ModelError

try:
    _VERSION = _pkg_version("audiby")
except PackageNotFoundError:
    _VERSION = "dev"


def _parse_setup_model(args: list[str]) -> str | None:
    """Extract model name from --setup-model or --setup-model=<name> in args.

    Returns the model name string, an empty string if the flag is present but
    the value is missing, or None if the flag is absent.
    """
    for i, arg in enumerate(args):
        if arg == "--setup-model":
            return args[i + 1] if i + 1 < len(args) else ""
        if arg.startswith("--setup-model="):
            return arg.split("=", 1)[1]
    return None


def _run_multiprocessing_child_if_requested() -> None:
    """Serve as a multiprocessing helper when launched as one, then exit.

    Inside the PyInstaller bundle ``sys.executable`` is Audiby itself. When a
    library starts a multiprocessing helper (the resource tracker on the first
    transcription, for example) it launches ``<exe> -c "<bootstrap code>"``
    expecting a bare interpreter. Without this check the bootloader runs the
    app instead, and a second Audiby with its own hotkey listener appears.
    """
    multiprocessing.freeze_support()
    args = sys.argv[1:]
    if "-c" not in args:
        return
    code_index = args.index("-c") + 1
    if code_index >= len(args):
        return
    code = args[code_index]
    if not code.lstrip().startswith("from multiprocessing"):
        return
    sys.argv = [sys.argv[0], *args[code_index + 1:]]
    exec(code, {"__name__": "__main__"})
    sys.exit(0)


def main() -> int:
    """Application entry point."""
    _run_multiprocessing_child_if_requested()
    setup_model = _parse_setup_model(sys.argv[1:])

    if setup_model is not None:
        if not setup_model:
            print("Missing model name after --setup-model")
            return 1

        try:
            model_path = model_manager.download(setup_model)
        except ModelError as exc:
            print(f"Model setup failed: {exc}")
            return 1

        print(f"Model downloaded to {model_path}")
        return 0

    print(f"{APP_NAME} v{_VERSION} - starting up...")
    config = Config()
    exit_code = run_app(config)
    if exit_code == 0:
        print(f"Config loaded from {config.config_dir}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
