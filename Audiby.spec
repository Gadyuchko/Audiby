# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller macOS bundle metadata for Audiby.

This spec is the source of Info.plist values used by scripts/build.py on macOS.
"""

from pathlib import Path


ROOT = Path(SPECPATH)
SRC = ROOT / "src"
MODEL_DIR = ROOT / "build" / "models" / "base"
TRAY_ICON = ROOT / "assets" / "audiby_tray_icon.png"
MAC_ICON = ROOT / "assets" / "icon.icns"

a = Analysis(
    [str(SRC / "audiby" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (str(MODEL_DIR), "models/base"),
        (str(TRAY_ICON), "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Audiby",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Audiby",
)
app = BUNDLE(
    coll,
    name="Audiby.app",
    icon=str(MAC_ICON),
    bundle_identifier="com.audiby.app",
    info_plist={
        "CFBundleName": "Audiby",
        "CFBundleDisplayName": "Audiby",
        "NSMicrophoneUsageDescription": "Audiby needs microphone access to transcribe your speech locally.",
        "NSInputMonitoringUsageDescription": "Audiby needs Input Monitoring access to detect the push-to-talk hotkey.",
    },
)
