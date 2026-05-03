"""Build Audiby onefile/app artifacts with PyInstaller."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from audiby.core import model_manager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Audiby"
DEFAULT_MODEL = "base"


@dataclass(frozen=True)
class BuildConfig:
    """Platform-specific PyInstaller output configuration."""

    platform: str
    artifact: Path


def build_config(platform: str = sys.platform) -> BuildConfig:
    """Return build configuration for supported platforms or exit clearly."""
    if platform == "win32":
        return BuildConfig(platform=platform, artifact=Path("dist") / "Audiby.exe")
    if platform == "darwin":
        return BuildConfig(platform=platform, artifact=Path("dist") / "Audiby.app")
    sys.stderr.write(f"Unsupported platform for Audiby packaging: {platform}\n")
    raise SystemExit(2)


def ensure_packaging_icons(project_root: Path = PROJECT_ROOT) -> None:
    """Generate platform package icons from the tracked tray icon if missing."""
    assets_dir = project_root / "assets"
    source_png = assets_dir / "audiby_tray_icon.png"
    icon_ico = assets_dir / "icon.ico"
    icon_icns = assets_dir / "icon.icns"

    if not source_png.is_file():
        raise FileNotFoundError(f"Missing source tray icon: {source_png}")

    image = Image.open(source_png).convert("RGBA")
    if not icon_ico.exists():
        image.save(icon_ico, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    if not icon_icns.exists():
        image.save(icon_icns)


def prepare_bundled_base_model(project_root: Path = PROJECT_ROOT) -> Path:
    """Populate build/models/base via the shared model manager download path."""
    build_models_root = project_root / "build" / "models"
    model_path = build_models_root / DEFAULT_MODEL
    if (model_path / model_manager.MODEL_BINARY).is_file():
        return model_path

    if model_path.exists():
        shutil.rmtree(model_path)
    return model_manager.download(DEFAULT_MODEL, root=build_models_root)


def _add_data_arg(source: Path, destination: str) -> str:
    """Return a PyInstaller --add-data value using the current OS separator."""
    return f"{source}{os.pathsep}{destination}"


def pyinstaller_command(config: BuildConfig, project_root: Path = PROJECT_ROOT) -> list[str]:
    """Build the PyInstaller command as an argument list."""
    if config.platform == "darwin":
        return [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(project_root / "Audiby.spec"),
        ]

    model_source = project_root / "build" / "models" / DEFAULT_MODEL
    tray_icon = project_root / "assets" / "audiby_tray_icon.png"
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--specpath",
        str(project_root / "build" / "pyinstaller"),
        "--onefile",
        "--noconsole",
        "--name",
        APP_NAME,
        "--icon",
        str(project_root / "assets" / "icon.ico"),
        "--paths",
        str(project_root / "src"),
        "--add-data",
        _add_data_arg(model_source, "models/base"),
        "--add-data",
        _add_data_arg(tray_icon, "assets"),
        str(project_root / "src" / "audiby" / "__main__.py"),
    ]


def run(platform: str = sys.platform) -> int:
    """Prepare generated build inputs and run PyInstaller."""
    config = build_config(platform)
    ensure_packaging_icons(PROJECT_ROOT)
    prepare_bundled_base_model(PROJECT_ROOT)
    command = pyinstaller_command(config, PROJECT_ROOT)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    artifact = PROJECT_ROOT / config.artifact
    if not artifact.exists():
        raise SystemExit(f"PyInstaller completed but artifact was not found: {artifact}")
    return 0


def main() -> int:
    """CLI entry point."""
    try:
        return run(sys.platform)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    raise SystemExit(main())
