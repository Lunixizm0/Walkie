import argparse
import os
import re
import sys
import logging
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")

log = logging.getLogger(__name__)

_REDACT_PATTERNS = [
    (re.compile(r'(encryption_key\s*=\s*")([^"]+)(")'), r'\1***REDACTED***\3'),
    (re.compile(r'(salt\s*=\s*")([^"]+)(")'), r'\1***REDACTED***\3'),
    (re.compile(r'(password\s*=\s*")([^"]+)(")'), r'\1***REDACTED***\3'),
    (re.compile(r'(passphrase[=:]\s*\S+)', re.IGNORECASE), r'***REDACTED***'),
    (re.compile(r'(key[=:]\s*)\S+', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r"(Chat message sent \(Room \d+\): ')[^']+(')"), r"\1***REDACTED***\2"),
    (re.compile(r"(Chat received from )('[^']+')(\s\(.+?\)\s\(Room \d+\): )('[^']+')"), r"\1***\3***"),
    (re.compile(r"(Chat received from '\S+': ')[^']+(')"), r"\1***\2"),
]


class RedactingFilter(logging.Filter):
    def __init__(self):
        super().__init__()

    def filter(self, record):
        msg = record.getMessage()
        for pattern, replacement in _REDACT_PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()
        return True


def cmd_run(args):
    from .audio_engine import AudioEngine
    from .crypto_utils import derive_key, get_general_key
    from .gui import ROOM_NAMES, StartupDialog, WalkieTalkieGUI
    from .network import ChatTransport, PeerDiscovery, VoiceTransport

    log_dir = Path.home() / ".config" / "walkie"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"walkie_{timestamp}.log"

    fmt = "%(asctime)s [%(levelname)-8s] %(name)-20s  %(message)s"
    datefmt = "%H:%M:%S"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.DEBUG if args.debug else logging.INFO)
    stream_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    if not args.debug:
        file_handler.addFilter(RedactingFilter())
    root.addHandler(file_handler)

    log.info("Walkie-Talkie LAN application starting")
    log.info(f"Log file: {log_file}")

    try:
        dialog = StartupDialog()
        dialog.mainloop()

        if dialog.result is None:
            log.info("User cancelled the login dialog, exiting")
            sys.exit(0)

        username, rooms_passwords = dialog.result
        log.info(f"User '{username}' entered credentials")
    except Exception as e:
        log.error(f"Login dialog error: {e}", exc_info=True)
        sys.exit(1)

    try:
        encryption_keys = {}
        for room_id, passphrase in rooms_passwords.items():
            if room_id == 0:
                encryption_keys[0] = get_general_key()
                log.info("Using static key for General room")
            else:
                encryption_keys[room_id] = derive_key(passphrase)
                log.info(f"Key derived for room '{ROOM_NAMES.get(room_id)}'")
    except Exception as e:
        log.error(f"Failed to derive encryption keys: {e}", exc_info=True)
        sys.exit(1)

    try:
        active_rooms_set = set(encryption_keys.keys())

        log.info("Starting VoiceTransport...")
        voice_transport = VoiceTransport(
            username=username,
            encryption_keys=encryption_keys,
            active_rooms=active_rooms_set
        )

        log.info("Starting ChatTransport...")
        chat_transport = ChatTransport(
            username=username,
            encryption_keys=encryption_keys,
            active_rooms=active_rooms_set
        )

        log.info("Starting PeerDiscovery...")
        peer_discovery = PeerDiscovery(
            username=username,
            active_rooms=active_rooms_set
        )

        log.info("Starting AudioEngine...")
        audio_engine = AudioEngine(
            on_audio_captured=lambda data, room_id: voice_transport.send_voice(data, room_id)
        )

        voice_transport.on_voice = lambda sender, data, room_id: audio_engine.play_audio(data)

        def handle_rooms_toggled(rooms: set[int]):
            log.info(f"Active rooms changed to {rooms}")
            peer_discovery.set_active_rooms(rooms)
            chat_transport.set_active_rooms(rooms)
            voice_transport.set_active_rooms(rooms)

        log.info("Starting GUI...")
        active_rooms = list(encryption_keys.keys())
        gui = WalkieTalkieGUI(
            username=username,
            active_rooms=active_rooms,
            on_send_chat=lambda text, room_id: chat_transport.send_message(text, room_id),
            on_ptt_start=lambda enabled_rooms: audio_engine.start_capture(enabled_rooms),
            on_ptt_stop=lambda: audio_engine.stop_capture(),
            on_rooms_toggled=handle_rooms_toggled,
            on_vad_toggled=lambda enabled, enabled_rooms: audio_engine.set_vad_enabled(enabled, enabled_rooms),
            on_play_beep=lambda freq, dur: audio_engine.play_beep(freq, dur),
            on_close=lambda: shutdown(),
        )

        def on_peers_changed(peers):
            try:
                gui.update_peers(peers)
                log.debug(f"Peers updated: {[(name, ip) for name, ip in peers]}")
            except Exception as e:
                log.error(f"on_peers_changed callback error: {e}", exc_info=True)

        def on_chat_received(sender, message, room_id):
            try:
                gui.append_chat(sender, message, room_id, is_self=False)
                log.debug(f"Chat received from '{sender}': '{message[:50]}'")
            except Exception as e:
                log.error(f"on_chat_received callback error: {e}", exc_info=True)

        chat_transport.on_message = on_chat_received
        peer_discovery.on_peers_changed = on_peers_changed

    except Exception as e:
        log.error(f"Failed to start components: {e}", exc_info=True)
        sys.exit(1)

    def shutdown():
        try:
            log.info("Shutdown initiated, stopping all services")
            peer_discovery.stop()
            chat_transport.stop()
            voice_transport.stop()
            audio_engine.shutdown()
            log.info("All services stopped successfully")
        except Exception as e:
            log.error(f"Error during shutdown: {e}", exc_info=True)

    gui.on_close = shutdown

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

    gui.add_system_message("Application started")
    gui.add_system_message(f"Connected as {username} to: {[ROOM_NAMES[r] for r in active_rooms]}")

    log.info("Entering GUI main loop")
    gui.mainloop()

    log.info("Application exited")


def cmd_gen(args):
    from pathlib import Path

    from .config import generate_config
    path = args.output if args.output else str(Path.home() / ".config" / "walkie" / "walkie_config.toml")
    cfg = generate_config(path)
    rooms = cfg["rooms"]
    print(f"Config generated: {path}")
    print(f"  Salt:         {cfg['general_room']['salt'][:16]}...")
    print(f"  Key:          {cfg['general_room']['encryption_key'][:16]}...")
    for room in rooms:
        pw = room["password"]
        if pw:
            print(f"  {room['name']}:    {pw}")
        else:
            print(f"  {room['name']}:    (no password)")
    print()
    print("Send this file to all clients:")
    print("  python walkie give <target_ip>")
    print("  python walkie get   (on the other side)")


def cmd_get(args):
    from .config import exchange_get
    ok = exchange_get(args.output)
    if ok:
        print("Config received successfully.")
        print("Now start the app: python main.py run")
    else:
        print("Failed to receive config.")
        sys.exit(1)


def cmd_give(args):
    from .config import exchange_give
    ok = exchange_give(args.target, args.file)
    if ok:
        print(f"Config sent: {args.target}")
    else:
        print(f"Failed to send config: {args.target}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="walkie",
        description="Walkie-Talkie LAN application",
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Start the application")
    run_p.add_argument("-d", "--debug", action="store_true",
                       help="Enable debug output on stdout and unredacted log file")
    run_p.set_defaults(func=cmd_run)

    gen_p = sub.add_parser("gen", help="Generate a secure config file")
    gen_p.add_argument("-o", "--output", default=None,
                       help="Output file (default: ~/.config/walkie/walkie_config.toml)")
    gen_p.set_defaults(func=cmd_gen)

    get_p = sub.add_parser("get", help="Receive config from another client")
    get_p.add_argument("-o", "--output", default=None,
                       help="File to save (default: ~/.config/walkie/walkie_config.toml)")
    get_p.set_defaults(func=cmd_get)

    give_p = sub.add_parser("give", help="Send config to another client")
    give_p.add_argument("target", help="Target IP address")
    give_p.add_argument("-f", "--file", default=None,
                        help="File to send (default: ~/.config/walkie/walkie_config.toml)")
    give_p.set_defaults(func=cmd_give)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"Unhandled exception in main: {e}", exc_info=True)
        sys.exit(1)
