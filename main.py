"""
Walkie-Talkie LAN Application
==============================
Serverless, peer-to-peer walkie-talkie for LAN.
Features: auto-discovery, encrypted text chat, push-to-talk voice.

Entry point — wires all modules together and starts the app.
"""

import sys
import logging
from crypto_utils import derive_key
from network import PeerDiscovery, ChatTransport, VoiceTransport
from audio_engine import AudioEngine
from gui import StartupDialog, WalkieTalkieGUI

# ── Configure logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(name)-20s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("walkie_debug.log", mode="w", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def main():
    log.info("=" * 60)
    log.info("Walkie-Talkie LAN Application starting up")
    log.info("=" * 60)

    # ── Startup dialog to get username & passphrase ─────────
    try:
        dialog = StartupDialog()
        dialog.mainloop()

        if dialog.result is None:
            log.info("User cancelled startup dialog — exiting")
            sys.exit(0)

        username, passphrase = dialog.result
        log.info(f"User '{username}' entered credentials")
    except Exception as e:
        log.error(f"Error during startup dialog: {e}", exc_info=True)
        sys.exit(1)

    # ── Derive encryption key ───────────────────────────────
    try:
        encryption_key = derive_key(passphrase)
        log.info("Encryption key derived from passphrase")
    except Exception as e:
        log.error(f"Failed to derive encryption key: {e}", exc_info=True)
        sys.exit(1)

    # ── Initialize components ───────────────────────────────
    try:
        log.info("Initializing VoiceTransport...")
        voice_transport = VoiceTransport(
            username=username,
            encryption_key=encryption_key,
        )

        log.info("Initializing AudioEngine...")
        audio_engine = AudioEngine(
            on_audio_captured=lambda data: voice_transport.send_voice(data)
        )

        # Voice receive callback → play audio
        voice_transport.on_voice = lambda sender, data: audio_engine.play_audio(data)

        log.info("Initializing ChatTransport...")
        chat_transport = ChatTransport(
            username=username,
            encryption_key=encryption_key,
        )

        log.info("Initializing GUI...")
        gui = WalkieTalkieGUI(
            username=username,
            on_send_chat=lambda text: chat_transport.send_message(text),
            on_ptt_start=lambda: audio_engine.start_capture(),
            on_ptt_stop=lambda: audio_engine.stop_capture(),
            on_close=lambda: shutdown(),
        )
    except Exception as e:
        log.error(f"Failed to initialize components: {e}", exc_info=True)
        sys.exit(1)

    # ── Wire callbacks ──────────────────────────────────────
    def on_peers_changed(peers):
        try:
            gui.update_peers(peers)
            log.debug(f"Peers updated: {[(name, ip) for name, ip in peers]}")
        except Exception as e:
            log.error(f"Error in on_peers_changed callback: {e}", exc_info=True)

    def on_chat_received(sender, message):
        try:
            gui.add_chat_message(sender, message, is_self=False)
            log.debug(f"Chat received from '{sender}': '{message[:50]}'")
        except Exception as e:
            log.error(f"Error in on_chat_received callback: {e}", exc_info=True)

    chat_transport.on_message = on_chat_received

    try:
        log.info("Initializing PeerDiscovery...")
        peer_discovery = PeerDiscovery(
            username=username,
            on_peers_changed=on_peers_changed,
        )
    except Exception as e:
        log.error(f"Failed to initialize PeerDiscovery: {e}", exc_info=True)
        sys.exit(1)

    # ── Shutdown handler ────────────────────────────────────
    def shutdown():
        try:
            log.info("Shutdown initiated — stopping all services")
            peer_discovery.stop()
            chat_transport.stop()
            voice_transport.stop()
            audio_engine.shutdown()
            log.info("All services stopped successfully")
        except Exception as e:
            log.error(f"Error during shutdown: {e}", exc_info=True)

    gui.on_close = shutdown

    # ── Start everything ────────────────────────────────────
    try:
        log.info("Starting all network services...")
        peer_discovery.start()
        chat_transport.start()
        voice_transport.start()
        log.info("All services started successfully")
    except Exception as e:
        log.error(f"Failed to start services: {e}", exc_info=True)
        shutdown()
        sys.exit(1)

    gui.add_system_message("Connected to channel · End-to-end encrypted 🔒")
    gui.add_system_message(f"Logged in as {username} · Searching for peers…")

    log.info("Entering GUI main loop")
    # Start the GUI main loop (blocks until window is closed)
    gui.run()

    log.info("Application exited")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Unhandled exception in main: {e}", exc_info=True)
        sys.exit(1)
