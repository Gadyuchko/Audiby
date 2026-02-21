# Audiby

Local voice-to-text with push-to-talk and active window injection. Runs entirely on your machine — no cloud APIs, no data leaves your device.

## What it does

Hold a hotkey, speak, release — your transcribed text is injected into whatever window is active. Powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2 backend) for fast, offline speech recognition.

## Tech stack

- **Python 3.11+** (3.13+ not supported — CTranslate2 constraint)
- **faster-whisper** — transcription engine
- **sounddevice** — audio capture
- **pynput** — global hotkeys + text injection
- **pystray + Pillow** — system tray icon
- **tkinter** — settings UI

## Getting started

```bash
# Install dependencies
uv sync

# Run the app
uv run python -m audiby
```

## Project structure

```
src/audiby/
  __main__.py       # entry point
  app.py            # orchestrator
  config.py         # JSON config (~%APPDATA%/Audiby/config.json)
  constants.py      # shared constants
  exceptions.py     # custom exceptions
  core/             # audio recording, transcription, text injection, model management
  platform/         # hotkeys, clipboard, autostart
  ui/               # system tray, settings window, download dialog
tests/              # mirrors src/ structure
```

## Configuration

Settings are stored at `%APPDATA%/Audiby/config.json` and created automatically on first run with sensible defaults:

| Setting | Default | Description |
|---------|---------|-------------|
| `push_to_talk_key` | `alt+z` | Hotkey combo for recording |
| `audio_device_id` | `null` | System default mic |
| `model_size` | `base` | Whisper model size |
| `start_on_boot` | `false` | Launch on Windows startup |

## License

[MIT](LICENSE)
