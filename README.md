# 📻 Walkie-Talkie LAN

A serverless, peer-to-peer walkie-talkie application for local area networks.

## Features

- **Auto-discovery** — peers on the same LAN find each other automatically
- **Real-time text chat** — broadcast messages to the channel
- **Push-to-talk voice** — hold **Shift + V** to broadcast your voice
- **End-to-end encryption** — all chat and voice data is AES-256-GCM encrypted
- **No server required** — works entirely over UDP broadcast

## Requirements

- Python 3.10+
- Windows / macOS / Linux
- All peers must be on the same LAN

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

1. Enter your **display name** and a **channel passphrase**
2. All peers using the **same passphrase** can communicate
3. Type messages in the chat and press **Enter** to send
4. Hold **Shift + V** to talk (release to stop)

> **Note:** Make sure your firewall allows UDP traffic on ports 50000-50002.

## How It Works

- **Discovery** (port 50000): UDP broadcast hello packets every 2 seconds
- **Chat** (port 50001): Encrypted text messages via UDP broadcast
- **Voice** (port 50002): Encrypted audio frames via UDP broadcast
- **Encryption**: Shared passphrase → PBKDF2 → AES-256-GCM

## Project Structure

```
main.py           — Entry point
gui.py            — tkinter GUI (dark theme)
network.py        — UDP broadcast networking
audio_engine.py   — Mic capture & playback (sounddevice)
crypto_utils.py   — AES-GCM encryption
```
