"""Tests for frozen and source resource path resolution."""

import sys
from pathlib import Path

from audiby import resources


def test_resource_path_uses_meipass_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resources.resource_path("models/base") == tmp_path / "models" / "base"


def test_resource_path_uses_repo_root_in_source_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert resources.resource_path("assets/audiby_tray_icon.png") == (
        Path(resources.__file__).resolve().parents[2] / "assets" / "audiby_tray_icon.png"
    )
