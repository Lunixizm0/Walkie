"""
Network layer for the Walkie-Talkie application.
Handles peer discovery, text chat, and voice transport over UDP broadcast.
"""

import socket
import struct
import threading
import time
import logging
from crypto_utils import encrypt, decrypt

log = logging.getLogger(__name__)

# Protocol ports
DISCOVERY_PORT = 50000
CHAT_PORT = 50001
VOICE_PORT = 50002

# Protocol constants
HELLO_INTERVAL = 2.0  # seconds between hello broadcasts
PEER_TIMEOUT = 10.0   # seconds before a peer is considered gone
BUFFER_SIZE = 65535    # max UDP datagram size

# Message type prefixes (single byte)
MSG_HELLO = b"\x01"
MSG_BYE = b"\x02"
MSG_CHAT = b"\x10"
MSG_VOICE = b"\x20"


def _get_local_ip() -> str:
    """Get the local LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        log.info(f"Local IP detected: {ip}")
        return ip
    except Exception as e:
        log.warning(f"Could not detect local IP, falling back to 127.0.0.1: {e}")
        return "127.0.0.1"


def _make_broadcast_socket(port: int, bind: bool = False) -> socket.socket:
    """Create a UDP broadcast socket."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if bind:
            sock.bind(("", port))
            log.debug(f"Bound UDP socket to port {port}")
        sock.settimeout(1.0)
        return sock
    except Exception as e:
        log.error(f"Failed to create broadcast socket on port {port}: {e}", exc_info=True)
        raise


class PeerDiscovery:
    """Discovers peers on the LAN via UDP broadcast."""

    def __init__(self, username: str, on_peers_changed=None):
        self.username = username
        self.local_ip = _get_local_ip()
        self.peers: dict[str, tuple[str, float]] = {}  # ip -> (username, last_seen)
        self.on_peers_changed = on_peers_changed
        self._running = False
        self._lock = threading.Lock()
        log.info(f"PeerDiscovery initialized for user '{username}' at {self.local_ip}")

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
        # Send BYE packet
        try:
            payload = MSG_BYE + self.username.encode("utf-8")
            self._send_sock.sendto(payload, ("<broadcast>", DISCOVERY_PORT))
            log.debug("BYE packet sent")
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

    def _broadcast_loop(self):
        log.debug("Discovery broadcast loop started")
        while self._running:
            try:
                payload = MSG_HELLO + self.username.encode("utf-8")
                self._send_sock.sendto(payload, ("<broadcast>", DISCOVERY_PORT))
                log.debug("HELLO broadcast sent")
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
                if ip == self.local_ip:
                    continue

                if data[0:1] == MSG_HELLO:
                    name = data[1:].decode("utf-8", errors="replace")
                    with self._lock:
                        was_new = ip not in self.peers
                        self.peers[ip] = (name, time.time())
                    if was_new:
                        log.info(f"New peer discovered: '{name}' at {ip}")
                        if self.on_peers_changed:
                            self.on_peers_changed(self._get_peer_list())

                elif data[0:1] == MSG_BYE:
                    with self._lock:
                        if ip in self.peers:
                            name = self.peers[ip][0]
                            del self.peers[ip]
                            log.info(f"Peer left: '{name}' at {ip}")
                    if self.on_peers_changed:
                        self.on_peers_changed(self._get_peer_list())

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Error in discovery listen loop: {e}", exc_info=True)
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
                        log.info(f"Peer timed out: '{name}' at {ip}")
                if removed and self.on_peers_changed:
                    self.on_peers_changed(self._get_peer_list())
            except Exception as e:
                log.error(f"Error in peer cleanup loop: {e}", exc_info=True)
        log.debug("Peer cleanup loop ended")

    def _get_peer_list(self) -> list[tuple[str, str]]:
        """Returns list of (username, ip)."""
        with self._lock:
            return [(name, ip) for ip, (name, _) in self.peers.items()]


class ChatTransport:
    """Sends and receives encrypted text chat messages via UDP broadcast."""

    def __init__(self, username: str, encryption_key: bytes, on_message=None):
        self.username = username
        self.key = encryption_key
        self.local_ip = _get_local_ip()
        self.on_message = on_message  # callback(sender_name, message_text)
        self._running = False
        log.info(f"ChatTransport initialized for user '{username}'")

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

    def send_message(self, text: str):
        """Broadcast an encrypted chat message."""
        try:
            # Pack: username_len (1 byte) + username + message
            name_bytes = self.username.encode("utf-8")[:255]
            msg_bytes = text.encode("utf-8")
            payload = struct.pack("B", len(name_bytes)) + name_bytes + msg_bytes
            encrypted = encrypt(payload, self.key)
            packet = MSG_CHAT + encrypted
            self._send_sock.sendto(packet, ("<broadcast>", CHAT_PORT))
            log.debug(f"Chat message sent: '{text[:50]}...' ({len(packet)} bytes)")
        except Exception as e:
            log.error(f"Failed to send chat message: {e}", exc_info=True)

    def _listen_loop(self):
        log.debug("Chat listen loop started")
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]
                if ip == self.local_ip:
                    continue

                if data[0:1] == MSG_CHAT:
                    encrypted = data[1:]
                    plaintext = decrypt(encrypted, self.key)
                    if plaintext is None:
                        log.debug(f"Received chat from {ip} but decryption failed (wrong key?)")
                        continue
                    name_len = plaintext[0]
                    sender = plaintext[1:1 + name_len].decode("utf-8", errors="replace")
                    message = plaintext[1 + name_len:].decode("utf-8", errors="replace")
                    log.debug(f"Chat received from '{sender}' at {ip}: '{message[:50]}'")
                    if self.on_message:
                        self.on_message(sender, message)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Error in chat listen loop: {e}", exc_info=True)
                else:
                    break
        log.debug("Chat listen loop ended")


class VoiceTransport:
    """Sends and receives encrypted voice audio frames via UDP broadcast."""

    def __init__(self, username: str, encryption_key: bytes, on_voice=None):
        self.username = username
        self.key = encryption_key
        self.local_ip = _get_local_ip()
        self.on_voice = on_voice  # callback(sender_name, audio_bytes)
        self._running = False
        log.info(f"VoiceTransport initialized for user '{username}'")

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

    def send_voice(self, audio_data: bytes):
        """Broadcast an encrypted voice frame."""
        try:
            name_bytes = self.username.encode("utf-8")[:255]
            payload = struct.pack("B", len(name_bytes)) + name_bytes + audio_data
            encrypted = encrypt(payload, self.key)
            packet = MSG_VOICE + encrypted
            self._send_sock.sendto(packet, ("<broadcast>", VOICE_PORT))
        except Exception as e:
            log.error(f"Failed to send voice frame: {e}", exc_info=True)

    def _listen_loop(self):
        log.debug("Voice listen loop started")
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]
                if ip == self.local_ip:
                    continue

                if data[0:1] == MSG_VOICE:
                    encrypted = data[1:]
                    plaintext = decrypt(encrypted, self.key)
                    if plaintext is None:
                        log.debug(f"Received voice from {ip} but decryption failed")
                        continue
                    name_len = plaintext[0]
                    sender = plaintext[1:1 + name_len].decode("utf-8", errors="replace")
                    audio = plaintext[1 + name_len:]
                    if self.on_voice:
                        self.on_voice(sender, audio)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Error in voice listen loop: {e}", exc_info=True)
                else:
                    break
        log.debug("Voice listen loop ended")
