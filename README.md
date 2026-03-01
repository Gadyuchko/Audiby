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
