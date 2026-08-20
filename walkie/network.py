import logging
import socket
import struct
import threading
import time

from .config import get_network_config
from .crypto_utils import decrypt, encrypt

log = logging.getLogger(__name__)

_cfg = get_network_config()
DISCOVERY_PORT = _cfg["discovery_port"]
CHAT_PORT = _cfg["chat_port"]
VOICE_PORT = _cfg["voice_port"]
HELLO_INTERVAL = _cfg["hello_interval"]
PEER_TIMEOUT = _cfg["peer_timeout"]
BUFFER_SIZE = 65535

# Message type prefixes (single byte)
MSG_HELLO = b"\x01"
MSG_BYE = b"\x02"
MSG_CHAT = b"\x10"
MSG_VOICE = b"\x20"


def _get_all_local_ips() -> set[str]:
    # Return all IP addresses on this machines network interfaces.
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass

    try:
        for iface_info in socket.getaddrinfo(socket.gethostname(), None):
            if iface_info[0] == socket.AF_INET:
                ips.add(iface_info[4][0])
    except Exception:
        pass

    ips.add("127.0.0.1")

    log.info(f"Detected local IPs: {ips}")
    return ips


def _get_broadcast_addresses() -> list[str]:
    """Return all subnet broadcast addresses for broadcasting."""
    addrs = ["<broadcast>"]  # default 255.255.255.255

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            # Calculate subnet broadcast address (simple /24 assumption)
            parts = ip.split(".")
            if parts[0] != "127":  # skip loopback
                broadcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                if broadcast not in addrs:
                    addrs.append(broadcast)
    except Exception as e:
        log.debug(f"Error calculating broadcast addresses: {e}")

    log.info(f"Broadcast addresses: {addrs}")
    _cached_broadcast_addrs = addrs
    return addrs


def _make_broadcast_socket(port: int, bind: bool = False) -> socket.socket:
    # Create a UDP broadcast socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if bind:
            sock.bind(("", port))
            log.debug(f"UDP socket bound to port {port}")
        sock.settimeout(1.0)
        return sock
    except Exception as e:
        log.error(f"Failed to create broadcast socket on port {port}: {e}", exc_info=True)
        raise


class PeerDiscovery:
    #Discovers peers on the LAN via UDP broadcast

    def __init__(self, username: str, active_rooms: set[int] = None, on_peers_changed=None):
        self.username = username
        self.active_rooms = active_rooms or {0}
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.peers: dict[str, tuple[str, float]] = {}  # ip -> (username, last_seen)
        self.on_peers_changed = on_peers_changed
        self._running = False
        self._lock = threading.Lock()
        log.info(f"PeerDiscovery started for user '{username}' (Rooms: {self.active_rooms})")

    def set_active_rooms(self, rooms: set[int]):
        self.active_rooms = set(rooms)
        with self._lock:
            self.peers.clear()
        if self.on_peers_changed:
            self.on_peers_changed([])
        log.debug(f"PeerDiscovery active rooms changed to {rooms}")

    def start(self):
        try:
            self._running = True
            self._send_sock = _make_broadcast_socket(DISCOVERY_PORT)
            self._recv_sock = _make_broadcast_socket(DISCOVERY_PORT, bind=True)

            self._send_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
            self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)

            self._send_thread.start()
            self._recv_thread.start()
            self._cleanup_thread.start()
            log.info(f"PeerDiscovery started on port {DISCOVERY_PORT}")
        except Exception as e:
            log.error(f"Failed to start PeerDiscovery: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("PeerDiscovery stopping...")
        self._running = False
        try:
            for rid in self.active_rooms:
                payload = MSG_BYE + struct.pack("B", rid) + self.username.encode("utf-8")
                for addr in self.broadcast_addrs:
                    try:
                        self._send_sock.sendto(payload, (addr, DISCOVERY_PORT))
                    except Exception:
                        pass
            log.debug("BYE packets sent")
        except Exception as e:
            log.warning(f"Failed to send BYE packet: {e}")
        try:
            self._send_sock.close()
        except Exception as e:
            log.debug(f"Error closing send socket: {e}")
        try:
            self._recv_sock.close()
        except Exception as e:
            log.debug(f"Error closing receive socket: {e}")
        log.info("PeerDiscovery stopped")

    def _is_local(self, ip: str) -> bool:
        """Check if the given IP belongs to this machine."""
        return ip in self.local_ips

    def _broadcast_loop(self):
        log.debug("Discovery broadcast loop started")
        while self._running:
            try:
                for rid in self.active_rooms:
                    payload = MSG_HELLO + struct.pack("B", rid) + self.username.encode("utf-8")
                    for addr in self.broadcast_addrs:
                        try:
                            self._send_sock.sendto(payload, (addr, DISCOVERY_PORT))
                        except Exception:
                            pass
            except Exception as e:
                log.warning(f"Failed to send HELLO broadcast: {e}")
            time.sleep(HELLO_INTERVAL)
        log.debug("Discovery broadcast loop ended")

    def _listen_loop(self):
        log.debug("Discovery listen loop started")
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]

                if self._is_local(ip):
                    continue

                if data[0:1] == MSG_HELLO:
                    if len(data) < 2: continue
                    room_id = data[1]
                    if room_id not in self.active_rooms: continue

                    name = data[2:].decode("utf-8", errors="replace")
                    with self._lock:
                        was_new = ip not in self.peers
                        self.peers[ip] = (name, time.time())
                    if was_new:
                        log.info(f"New peer discovered: '{name}' - {ip}")
                        if self.on_peers_changed:
                            self.on_peers_changed(self._get_peer_list())

                elif data[0:1] == MSG_BYE:
                    if len(data) < 2: continue
                    room_id = data[1]
                    if room_id not in self.active_rooms: continue

                    with self._lock:
                        if ip in self.peers:
                            name = self.peers[ip][0]
                            del self.peers[ip]
                            log.info(f"Peer left: '{name}' - {ip}")
                    if self.on_peers_changed:
                        self.on_peers_changed(self._get_peer_list())

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Discovery listen loop error: {e}", exc_info=True)
                else:
                    break
        log.debug("Discovery listen loop ended")

    def _cleanup_loop(self):
        log.debug("Peer cleanup loop started")
        while self._running:
            time.sleep(3.0)
            try:
                now = time.time()
                removed = False
                with self._lock:
                    expired = [ip for ip, (_, ts) in self.peers.items() if now - ts > PEER_TIMEOUT]
                    for ip in expired:
                        name = self.peers[ip][0]
                        del self.peers[ip]
                        removed = True
                        log.info(f"Peer timed out: '{name}' - {ip}")
                if removed and self.on_peers_changed:
                    self.on_peers_changed(self._get_peer_list())
            except Exception as e:
                log.error(f"Peer cleanup loop error: {e}", exc_info=True)
        log.debug("Peer cleanup loop ended")

    def _get_peer_list(self) -> list[tuple[str, str]]:
        """Return list of (username, ip) tuples."""
        with self._lock:
            return [(name, ip) for ip, (name, _) in self.peers.items()]


class ChatTransport:
    # Sends and receives encrypted text chat messages via UDP broadcast

    def __init__(self, username: str, encryption_keys: dict[int, bytes], active_rooms: set[int] = None, on_message=None):
        self.username = username
        self.keys = encryption_keys  # {room_id: key_bytes}
        self.active_rooms = active_rooms or set()
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.on_message = on_message  # callback(sender_name, message_text, room_id)
        self._running = False
        log.info(f"ChatTransport started for user '{username}' (Rooms: {self.active_rooms})")

    def set_active_rooms(self, rooms: set[int]):
        self.active_rooms = set(rooms)
        log.debug(f"ChatTransport active rooms changed to {rooms}")

    def start(self):
        try:
            self._running = True
            self._send_sock = _make_broadcast_socket(CHAT_PORT)
            self._recv_sock = _make_broadcast_socket(CHAT_PORT, bind=True)

            self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._recv_thread.start()
            log.info(f"ChatTransport started on port {CHAT_PORT}")
        except Exception as e:
            log.error(f"Failed to start ChatTransport: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("ChatTransport stopping...")
        self._running = False
        try:
            self._send_sock.close()
        except Exception as e:
            log.debug(f"Error closing chat send socket: {e}")
        try:
            self._recv_sock.close()
        except Exception as e:
            log.debug(f"Error closing chat receive socket: {e}")
        log.info("ChatTransport stopped")

    def send_message(self, text: str, room_id: int):
        """Broadcast an encrypted chat message to the specified room."""
        if room_id not in self.keys:
            log.warning(f"Cannot send chat message: no key for room {room_id}")
            return

        try:
            name_bytes = self.username.encode("utf-8")[:255]
            msg_bytes = text.encode("utf-8")
            payload = struct.pack("B", len(name_bytes)) + name_bytes + msg_bytes

            encrypted = encrypt(payload, self.keys[room_id])

            room_byte = struct.pack("B", room_id)
            packet = MSG_CHAT + room_byte + encrypted

            for addr in self.broadcast_addrs:
                try:
                    self._send_sock.sendto(packet, (addr, CHAT_PORT))
                except Exception:
                    pass
            log.debug(f"Chat message sent (Room {room_id}): '{text[:50]}' ({len(packet)} bytes)")
        except Exception as e:
            log.error(f"Failed to send chat message: {e}", exc_info=True)

    def _listen_loop(self):
        log.debug("Chat listen loop started")
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]
                if ip in self.local_ips:
                    continue

                if data[0:1] == MSG_CHAT:
                    if len(data) < 3:
                        continue

                    room_id = data[1]
                    if room_id not in self.active_rooms:
                        continue

                    if room_id not in self.keys:
                        continue

                    encrypted = data[2:]
                    plaintext = decrypt(encrypted, self.keys[room_id])

                    if plaintext is None:
                        log.debug(f"Received chat from {ip} but decryption failed (Room {room_id}, wrong key?)")
                        continue

                    name_len = plaintext[0]
                    sender = plaintext[1:1 + name_len].decode("utf-8", errors="replace")
                    message = plaintext[1 + name_len:].decode("utf-8", errors="replace")
                    log.debug(f"Chat received from '{sender}' ({ip}) (Room {room_id}): '{message[:50]}'")

                    if self.on_message:
                        self.on_message(sender, message, room_id)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Chat listen loop error: {e}", exc_info=True)
                else:
                    break
        log.debug("Chat listen loop ended")


class VoiceTransport:
    # Sends and receives encrypted voice frames via UDP broadcast

    def __init__(self, username: str, encryption_keys: dict[int, bytes], active_rooms: set[int] = None, on_voice=None):
        self.username = username
        self.keys = encryption_keys  # {room_id: key_bytes}
        self.active_rooms = active_rooms or set()
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.on_voice = on_voice  # callback(sender_name, voice_bytes, room_id)
        self._running = False
        log.info(f"VoiceTransport started for user '{username}' (Rooms: {self.active_rooms})")

    def set_active_rooms(self, rooms: set[int]):
        self.active_rooms = set(rooms)
        log.debug(f"VoiceTransport active rooms changed to {rooms}")

    def start(self):
        try:
            self._running = True
            self._send_sock = _make_broadcast_socket(VOICE_PORT)
            self._recv_sock = _make_broadcast_socket(VOICE_PORT, bind=True)

            self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._recv_thread.start()
            log.info(f"VoiceTransport started on port {VOICE_PORT}")
        except Exception as e:
            log.error(f"Failed to start VoiceTransport: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("VoiceTransport stopping...")
        self._running = False
        try:
            self._send_sock.close()
        except Exception as e:
            log.debug(f"Error closing voice send socket: {e}")
        try:
            self._recv_sock.close()
        except Exception as e:
            log.debug(f"Error closing voice receive socket: {e}")
        log.info("VoiceTransport stopped")

    def send_voice(self, audio_data: bytes, room_id: int):
        """Broadcast an encrypted voice frame to the specified room."""
        if room_id not in self.keys:
            return

        try:
            name_bytes = self.username.encode("utf-8")[:255]
            payload = struct.pack("B", len(name_bytes)) + name_bytes + audio_data

            encrypted = encrypt(payload, self.keys[room_id])

            room_byte = struct.pack("B", room_id)
            packet = MSG_VOICE + room_byte + encrypted

            for addr in self.broadcast_addrs:
                try:
                    self._send_sock.sendto(packet, (addr, VOICE_PORT))
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Failed to send voice frame: {e}", exc_info=True)

    def _listen_loop(self):
        log.debug("Voice listen loop started")
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]
                if ip in self.local_ips:
                    continue

                if data[0:1] == MSG_VOICE:
                    if len(data) < 3:
                        continue

                    room_id = data[1]

                    if room_id not in self.active_rooms:
                        continue

                    if room_id not in self.keys:
                        continue

                    encrypted = data[2:]
                    plaintext = decrypt(encrypted, self.keys[room_id])

                    if plaintext is None:
                        continue

                    name_len = plaintext[0]
                    sender = plaintext[1:1 + name_len].decode("utf-8", errors="replace")
                    audio = plaintext[1 + name_len:]

                    if self.on_voice:
                        self.on_voice(sender, audio, room_id)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Voice listen loop error: {e}", exc_info=True)
                else:
                    break
        log.debug("Voice listen loop ended")
