import collections
import logging
import os
import socket
import struct
import threading
import time

from .crypto_utils import decrypt, encrypt

log = logging.getLogger(__name__)

BUFFER_SIZE = 65535

MSG_HELLO = b"\x01"
MSG_BYE = b"\x02"
MSG_CHAT = b"\x10"
MSG_VOICE = b"\x20"

CHAT_FRAG_SIZE = 900
CHAT_FRAG_TIMEOUT = 5.0
CHAT_FRAG_MAX_PENDING = 50

_local_ips_cache: set[str] | None = None
_broadcast_addrs_cache: list[str] | None = None


def _get_all_local_ips() -> set[str]:
    global _local_ips_cache
    if _local_ips_cache is not None:
        return _local_ips_cache
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
    _local_ips_cache = ips
    log.info(f"Detected local IPs: {ips}")
    return ips


def _get_broadcast_addresses() -> list[str]:
    global _broadcast_addrs_cache
    if _broadcast_addrs_cache is not None:
        return _broadcast_addrs_cache
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
    _broadcast_addrs_cache = addrs
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

    def __init__(self, username: str, active_rooms: set[int] = None,
                 on_peers_changed=None, discovery_port: int = 50000,
                 hello_interval: float = 2.0, peer_timeout: float = 10.0):
        self.username = username
        self._active_rooms: tuple[int, ...] = tuple(active_rooms or {0})
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.peers: dict[str, tuple[str, float, set[int]]] = {}
        self.on_peers_changed = on_peers_changed
        self._running = False
        self._lock = threading.Lock()
        self._pending_byes: set[int] = set()
        self._port = discovery_port
        self._hello_interval = hello_interval
        self._peer_timeout = peer_timeout
        log.info(f"PeerDiscovery started for user '{username}' (Rooms: {self._active_rooms})")

    @property
    def active_rooms(self) -> set[int]:
        return set(self._active_rooms)

    def set_active_rooms(self, rooms: set[int]):
        old_rooms = set(self._active_rooms)
        new_rooms = set(rooms)
        removed_rooms = old_rooms - new_rooms
        self._active_rooms = tuple(new_rooms)

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
            self._send_sock = _make_broadcast_socket(self._port)
            self._recv_sock = _make_broadcast_socket(self._port, bind=True)

            self._send_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
            self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)

            self._send_thread.start()
            self._recv_thread.start()
            self._cleanup_thread.start()
            log.info(f"PeerDiscovery started on port {self._port}")
        except Exception as e:
            log.error(f"Failed to start PeerDiscovery: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("PeerDiscovery stopping...")
        self._running = False
        try:
            rooms = self.active_rooms
            if rooms:
                payload = _build_peer_packet(MSG_BYE, rooms, self.username)
                for addr in self.broadcast_addrs:
                    try:
                        self._send_sock.sendto(payload, (addr, self._port))
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
                            self._send_sock.sendto(payload, (addr, self._port))
                        except Exception:
                            pass
                    log.debug(f"Sent BYE for rooms: {byes_to_send}")

                rooms = self.active_rooms
                if rooms:
                    payload = _build_peer_packet(MSG_HELLO, rooms, self.username)
                    for addr in self.broadcast_addrs:
                        try:
                            self._send_sock.sendto(payload, (addr, self._port))
                        except Exception:
                            pass
            except Exception as e:
                log.warning(f"Failed to send discovery broadcast: {e}")
            time.sleep(self._hello_interval)
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
                    rooms = self.active_rooms
                    common_rooms = room_ids & rooms
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
                    rooms = self.active_rooms
                    common_rooms = room_ids & rooms
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
                    expired = [ip for ip, (_, ts, _) in self.peers.items() if now - ts > self._peer_timeout]
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


class Transport:

    def __init__(self, username: str, encryption_keys: dict[int, bytes],
                 active_rooms: set[int] = None, port: int = 50001,
                 message_type: bytes = MSG_CHAT, fragmented: bool = False,
                 on_receive=None, peer_discovery: PeerDiscovery = None):
        self.username = username
        self.keys = encryption_keys
        self._active_rooms: tuple[int, ...] = tuple(active_rooms or set())
        self.local_ips = _get_all_local_ips()
        self.on_receive = on_receive
        self.peer_discovery = peer_discovery
        self._running = False
        self._dedup = _Deduplicator()
        self._port = port
        self._msg_type = message_type
        self._fragmented = fragmented
        self._assembly: dict[int, dict] = {}
        self._assembly_lock = threading.Lock()
        log.info(f"Transport started for user '{username}' (type={message_type.hex()}, port={port}, Rooms: {self._active_rooms})")

    @property
    def active_rooms(self) -> set[int]:
        return set(self._active_rooms)

    def set_active_rooms(self, rooms: set[int]):
        self._active_rooms = tuple(rooms)
        self._dedup.clear()
        if self._fragmented:
            with self._assembly_lock:
                self._assembly.clear()
        log.debug(f"Transport active rooms changed to {rooms}")

    def start(self):
        try:
            self._running = True
            self._send_sock = _make_broadcast_socket(self._port)
            self._recv_sock = _make_broadcast_socket(self._port, bind=True)

            self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._recv_thread.start()
            log.info(f"Transport started on port {self._port}")
        except Exception as e:
            log.error(f"Failed to start Transport: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("Transport stopping...")
        self._running = False
        try:
            self._send_sock.close()
        except Exception as e:
            log.debug(f"Error closing send socket: {e}")
        try:
            self._recv_sock.close()
        except Exception as e:
            log.debug(f"Error closing recv socket: {e}")
        log.info("Transport stopped")

    def send(self, data: bytes, room_id: int):
        if room_id not in self.keys:
            log.warning(f"Cannot send: no key for room {room_id}")
            return

        try:
            name_bytes = self.username.encode("utf-8")[:255]
            payload = struct.pack("B", len(name_bytes)) + name_bytes + data
            aad = struct.pack("B", room_id)

            if self._fragmented:
                self._send_fragmented(payload, room_id, aad)
            else:
                self._send_unicast(payload, room_id, aad)
        except Exception as e:
            log.error(f"Failed to send: {e}", exc_info=True)

    def _send_unicast(self, payload: bytes, room_id: int, aad: bytes):
        encrypted = encrypt(payload, self.keys[room_id], aad=aad)
        if encrypted is None:
            return

        room_byte = struct.pack("B", room_id)
        packet = self._msg_type + room_byte + encrypted

        if self.peer_discovery:
            peers = self.peer_discovery.get_peers_for_room(room_id)
            for peer_name, ip in peers:
                try:
                    self._send_sock.sendto(packet, (ip, self._port))
                except Exception:
                    pass
        else:
            for addr in _get_broadcast_addresses():
                try:
                    self._send_sock.sendto(packet, (addr, self._port))
                except Exception:
                    pass

    def _send_fragmented(self, payload: bytes, room_id: int, aad: bytes):
        fragments = []
        for i in range(0, len(payload), CHAT_FRAG_SIZE):
            chunk = payload[i:i + CHAT_FRAG_SIZE]
            encrypted = encrypt(chunk, self.keys[room_id], aad=aad)
            if encrypted is None:
                return
            fragments.append(encrypted)

        total_frags = len(fragments)
        msg_id = struct.unpack("!H", os.urandom(2))[0]
        room_byte = struct.pack("B", room_id)

        for idx, enc_frag in enumerate(fragments):
            header = self._msg_type + room_byte + struct.pack("!H", msg_id) + struct.pack("B", idx) + struct.pack("B", total_frags)
            packet = header + enc_frag

            if self.peer_discovery:
                peers = self.peer_discovery.get_peers_for_room(room_id)
                for peer_name, ip in peers:
                    try:
                        self._send_sock.sendto(packet, (ip, self._port))
                    except Exception:
                        pass
            else:
                for addr in _get_broadcast_addresses():
                    try:
                        self._send_sock.sendto(packet, (addr, self._port))
                    except Exception:
                        pass

    def _assemble_fragment(self, msg_id: int, frag_idx: int, total_frags: int, encrypted: bytes) -> bytes | None:
        with self._assembly_lock:
            if len(self._assembly) >= CHAT_FRAG_MAX_PENDING and msg_id not in self._assembly:
                oldest_id = min(self._assembly, key=lambda k: self._assembly[k]["ts"])
                del self._assembly[oldest_id]

            if msg_id not in self._assembly:
                self._assembly[msg_id] = {
                    "frags": [None] * total_frags,
                    "received": 0,
                    "total": total_frags,
                    "ts": time.monotonic(),
                }

            entry = self._assembly[msg_id]
            if entry["total"] != total_frags:
                return None
            if frag_idx >= total_frags:
                return None
            if entry["frags"][frag_idx] is not None:
                return None

            entry["frags"][frag_idx] = encrypted
            entry["received"] += 1
            entry["ts"] = time.monotonic()

            if entry["received"] == entry["total"]:
                combined = b"".join(entry["frags"])
                del self._assembly[msg_id]
                return combined

        return None

    def _cleanup_stale_assembly(self):
        now = time.monotonic()
        with self._assembly_lock:
            stale = [mid for mid, e in self._assembly.items() if now - e["ts"] > CHAT_FRAG_TIMEOUT]
            for mid in stale:
                del self._assembly[mid]

    def _listen_loop(self):
        log.debug(f"Transport listen loop started (port={self._port})")
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]
                if ip in self.local_ips:
                    continue

                if data[0:1] != self._msg_type:
                    continue

                room_id = data[1]
                rooms = self.active_rooms
                if room_id not in rooms:
                    continue
                if room_id not in self.keys:
                    continue

                aad = struct.pack("B", room_id)

                if self._fragmented:
                    if len(data) < 7:
                        continue
                    msg_id = struct.unpack("!H", data[2:4])[0]
                    frag_idx = data[4]
                    total_frags = data[5]
                    encrypted = data[6:]

                    combined = self._assemble_fragment(msg_id, frag_idx, total_frags, encrypted)
                    if combined is None:
                        continue

                    plaintext = decrypt(combined, self.keys[room_id], aad=aad)
                else:
                    if len(data) < 3:
                        continue
                    encrypted = data[2:]
                    plaintext = decrypt(encrypted, self.keys[room_id], aad=aad)

                if plaintext is None:
                    continue

                name_len = plaintext[0]
                sender = plaintext[1:1 + name_len].decode("utf-8", errors="replace")
                payload = plaintext[1 + name_len:]

                if self._dedup.is_duplicate(plaintext):
                    continue

                if self.on_receive:
                    self.on_receive(sender, payload, room_id)

                if self._fragmented:
                    self._cleanup_stale_assembly()

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Transport listen loop error: {e}", exc_info=True)
                else:
                    break
        log.debug(f"Transport listen loop ended (port={self._port})")
