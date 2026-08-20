import collections
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
    addrs = ["<broadcast>"]

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            parts = ip.split(".")
            if parts[0] != "127":
                broadcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                if broadcast not in addrs:
                    addrs.append(broadcast)
    except Exception as e:
        log.debug(f"Error calculating broadcast addresses: {e}")

    log.info(f"Broadcast addresses: {addrs}")
    return addrs


def _make_broadcast_socket(port: int, bind: bool = False) -> socket.socket:
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


def _build_peer_packet(msg_type: bytes, room_ids: set[int], username: str) -> bytes:
    room_list = sorted(room_ids)
    payload = msg_type + struct.pack("B", len(room_list))
    for rid in room_list:
        payload += struct.pack("B", rid)
    payload += username.encode("utf-8")
    return payload


def _parse_peer_packet(data: bytes) -> tuple[set[int], str] | None:
    if len(data) < 3:
        return None

    count = data[1]
    if count == 0 or len(data) < 2 + count:
        return None

    room_ids = set()
    for i in range(count):
        room_ids.add(data[2 + i])

    username = data[2 + count:].decode("utf-8", errors="replace")
    return room_ids, username


class _Deduplicator:
    """Tracks recent packet hashes to filter out duplicates from multiple rooms."""

    def __init__(self, max_size: int = 200):
        self._seen: collections.deque = collections.deque(maxlen=max_size)
        self._seen_set: set[int] = set()

    def is_duplicate(self, data: bytes) -> bool:
        h = hash(data)
        if h in self._seen_set:
            return True
        if len(self._seen) == self._seen.maxlen:
            old = self._seen[0]
            self._seen_set.discard(old)
        self._seen.append(h)
        self._seen_set.add(h)
        return False

    def clear(self):
        self._seen.clear()
        self._seen_set.clear()


class PeerDiscovery:

    def __init__(self, username: str, active_rooms: set[int] = None, on_peers_changed=None):
        self.username = username
        self.active_rooms = active_rooms or {0}
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.peers: dict[str, tuple[str, float, set[int]]] = {}
        self.on_peers_changed = on_peers_changed
        self._running = False
        self._lock = threading.Lock()
        self._pending_byes: set[int] = set()
        log.info(f"PeerDiscovery started for user '{username}' (Rooms: {self.active_rooms})")

    def set_active_rooms(self, rooms: set[int]):
        new_rooms = set(rooms)
        removed_rooms = self.active_rooms - new_rooms
        self.active_rooms = new_rooms

        with self._lock:
            to_remove = []
            for ip, (name, ts, peer_rooms) in self.peers.items():
                remaining = peer_rooms - removed_rooms
                if not remaining:
                    to_remove.append(ip)
                    log.info(f"Peer removed (no shared rooms): '{name}' - {ip}")
                else:
                    self.peers[ip] = (name, ts, remaining)
            for ip in to_remove:
                del self.peers[ip]

        if removed_rooms and self._running:
            with self._lock:
                self._pending_byes.update(removed_rooms)

        if self.on_peers_changed:
            self.on_peers_changed(self._get_peer_list())
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
            if self.active_rooms:
                payload = _build_peer_packet(MSG_BYE, self.active_rooms, self.username)
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
            log.debug(f"Error closing recv socket: {e}")
        log.info("PeerDiscovery stopped")

    def _is_local(self, ip: str) -> bool:
        return ip in self.local_ips

    def _broadcast_loop(self):
        log.debug("Discovery broadcast loop started")
        while self._running:
            try:
                with self._lock:
                    byes_to_send = set(self._pending_byes)
                    self._pending_byes.clear()

                if byes_to_send:
                    payload = _build_peer_packet(MSG_BYE, byes_to_send, self.username)
                    for addr in self.broadcast_addrs:
                        try:
                            self._send_sock.sendto(payload, (addr, DISCOVERY_PORT))
                        except Exception:
                            pass
                    log.debug(f"Sent BYE for rooms: {byes_to_send}")

                if self.active_rooms:
                    payload = _build_peer_packet(MSG_HELLO, self.active_rooms, self.username)
                    for addr in self.broadcast_addrs:
                        try:
                            self._send_sock.sendto(payload, (addr, DISCOVERY_PORT))
                        except Exception:
                            pass
            except Exception as e:
                log.warning(f"Failed to send discovery broadcast: {e}")
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
                    parsed = _parse_peer_packet(data)
                    if parsed is None:
                        continue

                    room_ids, name = parsed
                    common_rooms = room_ids & self.active_rooms
                    if not common_rooms:
                        continue

                    changed = False
                    with self._lock:
                        if ip not in self.peers:
                            self.peers[ip] = (name, time.time(), set(common_rooms))
                            log.info(f"New peer discovered: '{name}' - {ip} (Rooms: {common_rooms})")
                            changed = True
                        else:
                            existing_name, existing_ts, existing_rooms = self.peers[ip]
                            updated_rooms = existing_rooms | common_rooms
                            if updated_rooms != existing_rooms:
                                self.peers[ip] = (name, time.time(), updated_rooms)
                                log.debug(f"Peer rooms updated: '{name}' - {ip} (Rooms: {updated_rooms})")
                                changed = True
                            else:
                                self.peers[ip] = (existing_name, time.time(), existing_rooms)

                    if changed and self.on_peers_changed:
                        self.on_peers_changed(self._get_peer_list())

                elif data[0:1] == MSG_BYE:
                    parsed = _parse_peer_packet(data)
                    if parsed is None:
                        continue

                    room_ids, name = parsed
                    common_rooms = room_ids & self.active_rooms
                    if not common_rooms:
                        continue

                    changed = False
                    with self._lock:
                        if ip in self.peers:
                            existing_name, existing_ts, existing_rooms = self.peers[ip]
                            remaining_rooms = existing_rooms - common_rooms
                            if not remaining_rooms:
                                del self.peers[ip]
                                log.info(f"Peer left: '{name}' - {ip}")
                                changed = True
                            else:
                                self.peers[ip] = (existing_name, existing_ts, remaining_rooms)
                                log.debug(f"Peer rooms updated (BYE): '{name}' - {ip} (Remaining: {remaining_rooms})")
                                changed = True

                    if changed and self.on_peers_changed:
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
                    expired = [ip for ip, (_, ts, _) in self.peers.items() if now - ts > PEER_TIMEOUT]
                    for ip in expired:
                        name = self.peers[ip][0]
                        del self.peers[ip]
                        removed = True
                        log.info(f"Peer timed out: '{name}' - {ip}")
                if removed and self.on_peers_changed:
                    self.on_peers_changed(self._get_peer_list())
            except Exception as e:
                log.error(f"Peer cleanup error: {e}", exc_info=True)
        log.debug("Peer cleanup loop ended")

    def get_peers_for_room(self, room_id: int) -> list[tuple[str, str]]:
        with self._lock:
            return [(name, ip) for ip, (name, _, room_ids) in self.peers.items()
                    if room_id in room_ids]

    def _get_peer_list(self) -> list[tuple[str, str]]:
        with self._lock:
            return [(name, ip) for ip, (name, _, _) in self.peers.items()]


class ChatTransport:

    def __init__(self, username: str, encryption_keys: dict[int, bytes],
                 active_rooms: set[int] = None, on_message=None,
                 peer_discovery: PeerDiscovery = None):
        self.username = username
        self.keys = encryption_keys
        self.active_rooms = active_rooms or set()
        self.local_ips = _get_all_local_ips()
        self.on_message = on_message
        self.peer_discovery = peer_discovery
        self._running = False
        self._dedup = _Deduplicator()
        log.info(f"ChatTransport started for user '{username}' (Rooms: {self.active_rooms})")

    def set_active_rooms(self, rooms: set[int]):
        self.active_rooms = set(rooms)
        self._dedup.clear()
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
            log.debug(f"Error closing chat recv socket: {e}")
        log.info("ChatTransport stopped")

    def send_message(self, text: str, room_id: int):
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

            if self.peer_discovery:
                peers = self.peer_discovery.get_peers_for_room(room_id)
                for peer_name, ip in peers:
                    try:
                        self._send_sock.sendto(packet, (ip, CHAT_PORT))
                    except Exception:
                        pass
                log.debug(f"Chat sent (Room {room_id}) to {len(peers)} peers: '{text[:50]}'")
            else:
                for addr in _get_broadcast_addresses():
                    try:
                        self._send_sock.sendto(packet, (addr, CHAT_PORT))
                    except Exception:
                        pass
                log.debug(f"Chat broadcast (Room {room_id}): '{text[:50]}'")
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

                    if self._dedup.is_duplicate(plaintext):
                        log.debug(f"Chat duplicate dropped from '{sender}' ({ip}) (Room {room_id})")
                        continue

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

    def __init__(self, username: str, encryption_keys: dict[int, bytes],
                 active_rooms: set[int] = None, on_voice=None,
                 peer_discovery: PeerDiscovery = None):
        self.username = username
        self.keys = encryption_keys
        self.active_rooms = active_rooms or set()
        self.local_ips = _get_all_local_ips()
        self.on_voice = on_voice
        self.peer_discovery = peer_discovery
        self._running = False
        self._dedup = _Deduplicator()
        log.info(f"VoiceTransport started for user '{username}' (Rooms: {self.active_rooms})")

    def set_active_rooms(self, rooms: set[int]):
        self.active_rooms = set(rooms)
        self._dedup.clear()
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
            log.debug(f"Error closing voice recv socket: {e}")
        log.info("VoiceTransport stopped")

    def send_voice(self, audio_data: bytes, room_id: int):
        if room_id not in self.keys:
            return

        try:
            name_bytes = self.username.encode("utf-8")[:255]
            payload = struct.pack("B", len(name_bytes)) + name_bytes + audio_data

            encrypted = encrypt(payload, self.keys[room_id])

            room_byte = struct.pack("B", room_id)
            packet = MSG_VOICE + room_byte + encrypted

            if self.peer_discovery:
                peers = self.peer_discovery.get_peers_for_room(room_id)
                for peer_name, ip in peers:
                    try:
                        self._send_sock.sendto(packet, (ip, VOICE_PORT))
                    except Exception:
                        pass
            else:
                for addr in _get_broadcast_addresses():
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

                    if self._dedup.is_duplicate(plaintext):
                        continue

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
