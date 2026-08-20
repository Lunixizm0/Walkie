# Walkie-Talkie

Serverless peer-to-peer walkie-talkie application for LAN.

Automatic peer discovery, encrypted text chat, push-to-talk voice communication.

## Installation

```bash
pip install walkie
```

Or for development:

```bash
git clone https://github.com/Lunixizm0/walkie.git
cd walkie
uv sync
```

## Usage

```bash
# Generate config (creates random passwords, salt, and encryption key)
walkie gen

# Receive config from another client
walkie get

# Send config to another client
walkie give <target_ip>

# Start the application
walkie run
```

Or run directly:

```bash
python -m walkie run
python -m walkie gen
python -m walkie get
python -m walkie give 192.168.1.100
```

## Configuration

The app looks for `walkie_config.toml` in `~/.config/walkie/`.
You can override the path with the `WALKIE_CONFIG` environment variable.

## Features

- Automatic peer discovery via UDP broadcast (no server needed)
- AES-256-GCM encryption for voice and chat
- Low-latency voice with Opus codec
- Push-to-Talk (Shift+V) and Voice Activity Detection (VAD) modes
- Seamless playback with jitter buffer
- System tray minimization
- TOML-based configuration
- Config sharing over TCP (--get/--give)

## Requirements

- Python 3.11+
- Linux, Windows, or macOS
- Microphone and speakers

## License

MIT
