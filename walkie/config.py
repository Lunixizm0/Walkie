import logging
import os
import secrets
import socket
import string
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULTS = {
    "network": {
        "discovery_port": 50000,
        "chat_port": 50001,
        "voice_port": 50002,
        "hello_interval": 2.0,
        "peer_timeout": 10.0,
    },
    "audio": {
        "sample_rate": 48000,
        "channels": 1,
        "frame_duration_ms": 20,
        "bitrate": 24000,
    },
    "voice_activity_detection": {
        "enabled": False,
        "rms_threshold": 50,
    },
    "general_room": {
        "encryption_key": "",
        "salt": "",
    },
    "rooms": [
        {"id": 0, "name": "General", "password": ""},
        {"id": 1, "name": "Private 1", "password": ""},
        {"id": 2, "name": "Private 2", "password": ""},
    ],
    "gui": {
        "tray_icon_color": "#1a1a24",
    },
}


def _deep_merge(base: dict, overrides: dict) -> dict:
    result = base.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate(cfg: dict) -> dict:
    net = cfg.get("network", {})
    if not isinstance(net.get("discovery_port"), int):
        raise ValueError("network.discovery_port must be an integer")
    if not isinstance(net.get("chat_port"), int):
        raise ValueError("network.chat_port must be an integer")
    if not isinstance(net.get("voice_port"), int):
        raise ValueError("network.voice_port must be an integer")

    audio = cfg.get("audio", {})
    if not isinstance(audio.get("sample_rate"), int):
        raise ValueError("audio.sample_rate must be an integer")

    rooms = cfg.get("rooms", [])
    if not rooms:
        raise ValueError("At least one room must be defined")
    for room in rooms:
        if "id" not in room or "name" not in room:
            raise ValueError(f"Room must have 'id' and 'name': {room}")

    gr = cfg.get("general_room", {})
    if not gr.get("salt"):
        raise ValueError(
            "Config not found or incomplete. Run 'walkie gen' to generate one."
        )
    if not gr.get("encryption_key"):
        raise ValueError(
            "Config not found or incomplete. Run 'walkie gen' to generate one."
        )

    return cfg


def _load_toml(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        log.info(f"Config file not found: {path}, using defaults")
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        log.info(f"Config file loaded: {path}")
        return data
    except Exception as e:
        log.error(f"Failed to read config file: {e}")
        return {}


def load_config(path: str | Path | None = None) -> dict:
    if path is None:
        env_path = os.environ.get("WALKIE_CONFIG")
        if env_path:
            path = env_path
        else:
            path = Path.home() / ".config" / "walkie" / "walkie_config.toml"
    cfg = _deep_merge(_DEFAULTS, _load_toml(path))
    return _validate(cfg)


def _generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_config(path: str | Path | None = None) -> dict:
    # Generate a config file with secure random salt, key, and room passwords
    if path is None:
        path = Path.home() / ".config" / "walkie" / "walkie_config.toml"
    salt = secrets.token_hex(32)
    encryption_key = secrets.token_hex(32)
    password_teachers = _generate_password(20)
    password_thinktank = _generate_password(20)

    cfg = {
        "network": _DEFAULTS["network"].copy(),
        "audio": _DEFAULTS["audio"].copy(),
        "voice_activity_detection": _DEFAULTS["voice_activity_detection"].copy(),
        "general_room": {
            "encryption_key": encryption_key,
            "salt": salt,
        },
        "rooms": [
            {"id": 0, "name": "General", "password": ""},
            {"id": 1, "name": "Private 1", "password": password_teachers},
            {"id": 2, "name": "Private 2", "password": password_thinktank},
        ],
        "gui": _DEFAULTS["gui"].copy(),
    }

    def _toml_val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        return repr(v)

    path = Path(path)
    lines = []
    lines.append("[network]")
    for k, v in cfg["network"].items():
        lines.append(f"{k} = {_toml_val(v)}")
    lines.append("")
    lines.append("[audio]")
    for k, v in cfg["audio"].items():
        lines.append(f"{k} = {_toml_val(v)}")
    lines.append("")
    lines.append("[voice_activity_detection]")
    for k, v in cfg["voice_activity_detection"].items():
        lines.append(f"{k} = {_toml_val(v)}")
    lines.append("")
    lines.append("[general_room]")
    for k, v in cfg["general_room"].items():
        lines.append(f'{k} = "{v}"')
    lines.append("")
    for room in cfg["rooms"]:
        lines.append("[[rooms]]")
        lines.append(f'id = {room["id"]}')
        lines.append(f'name = "{room["name"]}"')
        lines.append(f'password = "{room["password"]}"')
        lines.append("")
    lines.append("[gui]")
    for k, v in cfg["gui"].items():
        lines.append(f'{k} = "{v}"')
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Config generated: {path}")
    return cfg


EXCHANGE_PORT = 50100


def exchange_give(target_ip: str, config_path: str | Path | None = None):
    # Send a config file to the target IP over TCP
    if config_path is None:
        config_path = Path.home() / ".config" / "walkie" / "walkie_config.toml"
    path = Path(config_path)
    if not path.exists():
        log.error(f"Config file not found: {path}")
        return False

    data = path.read_bytes()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((target_ip, EXCHANGE_PORT))

        sock.sendall(len(data).to_bytes(4, "big"))
        sock.sendall(data)

        response = sock.recv(32)
        if response == b"OK":
            log.info(f"Config sent to {target_ip}:{EXCHANGE_PORT}")
            return True
        else:
            log.error(f"Error: {target_ip} did not respond")
            return False
    except Exception as e:
        log.error(f"Failed to send config: {e}")
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def exchange_get(config_path: str | Path | None = None):
    # Listen for a config file from another client and save it
    if config_path is None:
        config_path = Path.home() / ".config" / "walkie" / "walkie_config.toml"
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", EXCHANGE_PORT))
    server.listen(1)
    server.settimeout(300.0)

    print(f"Waiting for config (port {EXCHANGE_PORT})...")
    print("Other client: python main.py give <this_ip>")

    try:
        conn, addr = server.accept()
        log.info(f"Connection received from {addr[0]}:{addr[1]}")

        size_bytes = conn.recv(4)
        if len(size_bytes) < 4:
            log.error("Could not read size header")
            return False

        size = int.from_bytes(size_bytes, "big")
        if size > 10 * 1024 * 1024:
            log.error("Config file too large (max 10MB)")
            return False

        received = b""
        while len(received) < size:
            chunk = conn.recv(min(65536, size - len(received)))
            if not chunk:
                log.error("Connection closed prematurely")
                return False
            received += chunk

        conn.sendall(b"OK")
        conn.close()

        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(received)
        log.info(f"Config saved: {path}")
        print(f"Config received and saved: {path}")
        return True
    except socket.timeout:
        log.error("Timeout: no connection received within 300s")
        return False
    except Exception as e:
        log.error(f"Failed to receive config: {e}")
        return False
    finally:
        try:
            server.close()
        except Exception:
            pass


_config: dict | None = None


def get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_network_config() -> dict:
    return get_config()["network"]


def get_audio_config() -> dict:
    return get_config()["audio"]


def get_vad_config() -> dict:
    return get_config()["voice_activity_detection"]


def get_general_room_config() -> dict:
    return get_config()["general_room"]


def get_rooms() -> list[dict]:
    return get_config()["rooms"]


def get_room_names() -> dict[int, str]:
    return {r["id"]: r["name"] for r in get_rooms()}


def get_room_passwords() -> dict[int, str]:
    return {r["id"]: r["password"] for r in get_rooms() if r.get("password")}
