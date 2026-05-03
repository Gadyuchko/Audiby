"""Bundled resource lookup for source and PyInstaller-frozen runtime."""

import sys
from pathlib import Path


def resource_path(rel_path: str | Path) -> Path:
    """Return the absolute path for a repo or PyInstaller bundled resource."""
    relative = Path(rel_path)
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).resolve().parents[2] / relative
