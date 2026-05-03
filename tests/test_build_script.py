"""Unit tests for PyInstaller build command construction."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build


def test_build_config_rejects_unsupported_platform(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build.build_config("linux")

    assert exc_info.value.code == 2
    assert "Unsupported platform for Audiby packaging: linux" in capsys.readouterr().err


def test_windows_build_command_uses_onefile_options(tmp_path):
    root = tmp_path
    (root / "assets").mkdir()
    (root / "assets" / "icon.ico").touch()
    (root / "build" / "models" / "base").mkdir(parents=True)

    config = build.build_config("win32")
    command = build.pyinstaller_command(config, root)

    assert "--onefile" in command
    assert "--noconsole" in command
    assert "--specpath" in command
    assert str(root / "build" / "pyinstaller") in command
    assert "--name" in command
    assert "Audiby" in command
    assert "--icon" in command
    assert str(root / "assets" / "icon.ico") in command
    assert f"{root / 'build' / 'models' / 'base'}{build.os.pathsep}models/base" in command


def test_macos_build_command_uses_spec_file(tmp_path):
    root = tmp_path
    (root / "Audiby.spec").touch()

    config = build.build_config("darwin")
    command = build.pyinstaller_command(config, root)

    assert command == [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(root / "Audiby.spec"),
    ]


def test_run_invokes_subprocess_with_argument_list(monkeypatch, tmp_path):
    calls = {}

    def fake_prepare_model(root: Path) -> Path:
        model_dir = root / "build" / "models" / "base"
        model_dir.mkdir(parents=True)
        return model_dir

    def fake_run(command, cwd, check):
        calls["command"] = command
        calls["cwd"] = cwd
        calls["check"] = check
        (cwd / "dist").mkdir()
        (cwd / "dist" / "Audiby.exe").touch()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build, "ensure_packaging_icons", lambda root: None)
    monkeypatch.setattr(build, "prepare_bundled_base_model", fake_prepare_model)
    monkeypatch.setattr(build.subprocess, "run", fake_run)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "icon.ico").touch()

    assert build.run("win32") == 0
    assert isinstance(calls["command"], list)
    assert calls["cwd"] == tmp_path
    assert calls["check"] is True


def test_run_codesigns_and_zips_macos_app(monkeypatch, tmp_path):
    calls = []

    def fake_prepare_model(root: Path) -> Path:
        model_dir = root / "build" / "models" / "base"
        model_dir.mkdir(parents=True)
        return model_dir

    def fake_run(command, cwd, check):
        calls.append(command)
        if command[:4] == [sys.executable, "-m", "PyInstaller", "--clean"]:
            (cwd / "dist" / "Audiby.app").mkdir(parents=True)
        if command[0] == "ditto":
            (cwd / "dist" / "Audiby-macos.zip").touch()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(build, "ensure_packaging_icons", lambda root: None)
    monkeypatch.setattr(build, "prepare_bundled_base_model", fake_prepare_model)
    monkeypatch.setattr(build.subprocess, "run", fake_run)
    (tmp_path / "Audiby.spec").touch()

    assert build.run("darwin") == 0
    assert [
        "codesign",
        "--force",
        "--deep",
        "--sign",
        "-",
        str(tmp_path / "dist" / "Audiby.app"),
    ] in calls
    assert [
        "ditto",
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
        str(tmp_path / "dist" / "Audiby.app"),
        str(tmp_path / "dist" / "Audiby-macos.zip"),
    ] in calls
