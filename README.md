# Audiby

Local voice-to-text for Windows with push-to-talk and active window injection. Runs entirely on your machine — no cloud APIs, no audio or text ever leaves your device.

## What It Does

Hold a hotkey → speak → release → transcribed text appears at your cursor in any active window (VS Code, browser, chat apps — anything). Powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) for fast, offline speech recognition with automatic GPU acceleration when available.

### How It Works

```
Hotkey held → Mic captures audio (16kHz mono)
                  ↓
            faster-whisper transcribes locally
                  ↓
            Text injected via clipboard paste into active window
```

Audio is kept in memory only — never written to disk. Clipboard contents are backed up before injection and restored after.

## Tech Stack

- **Python 3.11–3.12** (3.13+ not supported — CTranslate2 constraint)
- **faster-whisper** — Whisper via CTranslate2 backend (~4x faster than vanilla Whisper)
- **sounddevice** — audio capture
- **pynput** — global hotkeys + paste simulation
- **pystray + Pillow** — system tray icon
- **tkinter** — settings UI (ships with Python)
- **uv** — package manager

## Getting Started

### Prerequisites

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/) package manager

### Install & Run

```bash
# Install dependencies
uv sync

# Download a Whisper model (required before first use)
uv run python -m audiby --setup-model base
# Options: tiny | base | small | medium | large-v3

# Run the app
uv run python -m audiby
```

### Development Mode

Set `AUDIBY_DEV_APPDATA=1` to redirect all runtime data (config, models, logs) to `.tmp-appdata/` in the repo root instead of `%APPDATA%`:

```bash
AUDIBY_DEV_APPDATA=1 uv run python -m audiby
```

### Optional: Enable NVIDIA GPU Acceleration

Audiby can run fully on CPU. GPU is optional, but faster.

Use this only if you have an NVIDIA GPU and want acceleration.
The commands below are PowerShell examples for Windows. On Linux/macOS, use equivalent shell commands and platform-specific install paths.

Recommended working combo:
- CUDA Toolkit: `12.x` (for example `12.9`)
- cuDNN: `9.x` built for CUDA 12 (for example `9.19` with `12.9` backend)

Why these components:
- NVIDIA Driver: lets Windows/apps communicate with GPU hardware.
- CUDA Toolkit: provides GPU compute runtime and libraries.
- cuDNN: optimized deep-learning runtime used by Whisper inference.

1. Check driver status:

```powershell
nvidia-smi
```

- If it works, your NVIDIA driver is installed.
- If it fails, install/update the NVIDIA driver first.
- Driver download: https://www.nvidia.com/Download/index.aspx

2. Install CUDA Toolkit 12.x.
- CUDA downloads: https://developer.nvidia.com/cuda-downloads
3. Install cuDNN 9 for CUDA 12.
- cuDNN downloads: https://developer.nvidia.com/cudnn
- CUDA Windows install guide: https://docs.nvidia.com/cuda/cuda-installation-guide-microsoft-windows/index.html
- cuDNN Windows install guide: https://docs.nvidia.com/deeplearning/cudnn/installation/latest/windows.html
4. Ensure these folders are in `Path`:

```text
C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin
C:\Program Files\NVIDIA\CUDNN\v9.19\bin\12.9\x64
```

You can also use `%CUDA_PATH%\bin` instead of a hardcoded CUDA version if `%CUDA_PATH%` points to CUDA 12.

5. Fully restart your IDE/terminal after editing environment variables.

6. Open a new terminal and verify required DLLs:

```powershell
python -c "import ctypes; ctypes.WinDLL('cublas64_12.dll'); print('cublas OK')"
python -c "import ctypes; ctypes.WinDLL('cudnn64_9.dll'); print('cudnn OK')"
```

If both commands print `OK`, GPU runtime is ready.

If you see `cublas64_12.dll is not found` or `cudnn64_9.dll is not found`, CUDA/cuDNN is not installed correctly or not on `PATH`.

Troubleshooting:
- If full-path DLL loading works but name-based loading fails, the process is using stale/missing `Path`. Restart IDE/terminal (or sign out/in) and recheck.

Note: when GPU runtime is unavailable, Audiby automatically falls back to CPU mode so dictation still works.

### Run Tests

```bash
uv run pytest
```

## Project Structure

```
src/audiby/
  __main__.py       # CLI entry point
  app.py            # pipeline orchestrator
  config.py         # JSON config (~%APPDATA%/Audiby/config.json)
  constants.py      # shared constants
  exceptions.py     # custom exception hierarchy
  core/             # audio recorder, transcriber, text injector, model manager
  platform/         # Win32 clipboard, hotkey manager, autostart
  ui/               # system tray, settings window, download dialog
tests/              # mirrors src/ structure
```

## Configuration

Settings live at `%APPDATA%\Audiby\config.json` (auto-created on first run):

| Setting | Default | Description |
|---------|---------|-------------|
| `push_to_talk_key` | `alt+z` | Hotkey combo for recording |
| `audio_device_id` | `null` | System default mic |
| `model_size` | `base` | Whisper model size |
| `start_on_boot` | `false` | Launch on Windows startup |

### Runtime Data

```
%APPDATA%\Audiby\
├── config.json
├── models\         # downloaded Whisper model files
└── logs\           # rotating logs (up to 5 × 1 MB)
```

## License

[MIT](LICENSE)
