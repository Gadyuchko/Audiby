# Audiby

Local voice-to-text with push-to-talk and active-window injection. Audiby runs on your machine: no cloud APIs, no telemetry, and no audio or transcribed text leaves your device.

## Download

Download the latest release from GitHub:

- Windows: `Audiby.exe`
- macOS: `Audiby-macos.zip`

Release artifacts are built by `.github/workflows/build.yml`. Pushes and pull requests validate the build matrix; version tags matching `v*.*.*` publish the GitHub Release artifacts.

## Quickstart

### Windows

1. Download `Audiby.exe` from the latest GitHub Release.
2. Double-click `Audiby.exe`.
3. If Windows SmartScreen appears, click **More info** -> **Run anyway**.
4. Allow microphone access if prompted.
5. Hold `ctrl+space`, speak, then release. The transcribed text appears at your cursor.

### macOS

1. Download `Audiby-macos.zip` from the latest GitHub Release.
2. Unzip it and open `Audiby.app`.
3. If macOS blocks the app, right-click `Audiby.app` and choose **Open**.
4. Allow Microphone and Input Monitoring permissions if prompted.
5. Hold `ctrl+space`, speak, then release. The transcribed text appears at your cursor.

Audiby v1.0 artifacts are unsigned. Windows may show SmartScreen, and macOS may show the standard unidentified-developer prompt.

## What It Does

Hold a hotkey, speak, release, and Audiby inserts the transcription into the active window.

```text
Hotkey held -> Mic captures audio (16kHz mono)
                 |
                 v
       faster-whisper transcribes locally
                 |
                 v
   Text injected via clipboard paste into active window
```

Audio is kept in memory only and is never written to disk. Clipboard contents are backed up before injection and restored after.

## Privacy

- Audio stays local and in memory.
- Transcribed text is used only for the active paste flow.
- No telemetry, analytics, or phone-home behavior.
- The default release artifact includes the base Whisper model, so first launch does not need a model download.

## Uninstall

### Windows

Delete `Audiby.exe`, then remove runtime data if you want a full cleanup:

```text
%APPDATA%\Audiby\
```

### macOS

Delete `Audiby.app`, then remove runtime data if you want a full cleanup:

```text
~/Library/Application Support/Audiby/
```

## Runtime Data

Audiby stores config, optional downloaded models, and logs in per-user app data:

```text
Windows:
%APPDATA%\Audiby\
  config.json
  models\
  logs\

macOS:
~/Library/Application Support/Audiby/
  config.json
  models/
  logs/

Linux/dev fallback:
~/.local/share/Audiby/
  config.json
  models/
  logs/
```

## Development

### Tech Stack

- Python 3.11-3.12
- faster-whisper
- sounddevice
- pynput
- pystray + Pillow
- tkinter
- uv
- PyInstaller

### Setup

```bash
uv sync
uv run python -m audiby
```

Download or switch a Whisper model manually:

```bash
uv run python -m audiby --setup-model base
```

Supported models: `tiny`, `base`, `small`, `medium`, `large-v3`.

### Build

```bash
uv run python scripts/build.py
```

On Windows this produces `dist/Audiby.exe`. On macOS this produces `dist/Audiby.app`, ad-hoc signs it, and packages `dist/Audiby-macos.zip`.

### Development Mode

Set `AUDIBY_DEV_APPDATA=1` to redirect runtime data to repo-local `.tmp-appdata/Audiby`:

```bash
AUDIBY_DEV_APPDATA=1 uv run python -m audiby
```

### Run Tests

```bash
uv run pytest
```

## Optional GPU Acceleration

Audiby runs fully on CPU. GPU is optional.

Use this only if you have an NVIDIA GPU and want acceleration. The commands below are PowerShell examples for Windows.

Recommended combo:

- CUDA Toolkit: `12.x`
- cuDNN: `9.x` built for CUDA 12

Check driver status:

```powershell
nvidia-smi
```

If it fails, install or update the NVIDIA driver first:

```text
https://www.nvidia.com/Download/index.aspx
```

Install CUDA Toolkit and cuDNN:

```text
https://developer.nvidia.com/cuda-downloads
https://developer.nvidia.com/cudnn
```

Ensure these folders are in `Path`:

```text
C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin
C:\Program Files\NVIDIA\CUDNN\v9.x\bin\12.x\x64
```

Restart your terminal or IDE after editing environment variables, then verify DLL loading:

```powershell
python -c "import ctypes; ctypes.WinDLL('cublas64_12.dll'); print('cublas OK')"
python -c "import ctypes; ctypes.WinDLL('cudnn64_9.dll'); print('cudnn OK')"
```

When GPU runtime is unavailable, Audiby falls back to CPU mode.

## Project Structure

```text
src/audiby/
  __main__.py       # CLI entry point
  app.py            # pipeline orchestrator
  config.py         # JSON config load/save
  constants.py      # shared constants
  exceptions.py     # custom exception hierarchy
  core/             # audio recorder, transcriber, text injector, model manager
  platform/         # platform backends + factories
  ui/               # system tray, settings window, download dialog
tests/              # mirrors src/ structure
```

## License

[MIT](LICENSE)
