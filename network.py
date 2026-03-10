"""
Walkie-Talkie uygulaması için ağ katmanı.
UDP yayını üzerinden eş keşfi, metin sohbet ve ses aktarımını yönetir.
"""

import socket
import struct
import threading
import time
import logging
from crypto_utils import encrypt, decrypt

log = logging.getLogger(__name__)

# Protokol portları
DISCOVERY_PORT = 50000
CHAT_PORT = 50001
VOICE_PORT = 50002

# Protokol sabitleri
HELLO_INTERVAL = 2.0  # merhaba yayınları arasındaki saniye
PEER_TIMEOUT = 10.0   # bir eşin çevrimdışı sayılması için gereken saniye
BUFFER_SIZE = 65535    # maksimum UDP datagram boyutu

# Mesaj tipi önekleri (tek bayt)
MSG_HELLO = b"\x01"
MSG_BYE = b"\x02"
MSG_CHAT = b"\x10"
MSG_VOICE = b"\x20"


def _get_all_local_ips() -> set[str]:
    """Bu makinenin tüm ağ arayüzlerindeki IP adreslerini döndürür."""
    ips = set()
    try:
        # Varsayılan arayüz IP'si
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    try:
        # Hostname üzerinden tüm IP'leri al
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass

    try:
        # Tüm arayüzleri tarayarak ek IP'leri bul
        for iface_info in socket.getaddrinfo(socket.gethostname(), None):
            if iface_info[0] == socket.AF_INET:
                ips.add(iface_info[4][0])
    except Exception:
        pass

    # Loopback her zaman yerel
    ips.add("127.0.0.1")

    log.info(f"Tespit edilen yerel IP'ler: {ips}")
    return ips


def _get_broadcast_addresses() -> list[str]:
    """Yayın yapılacak tüm alt ağ yayın adreslerini döndürür."""
    addrs = ["<broadcast>"]  # varsayılan 255.255.255.255

    try:
        # Windows'ta tüm arayüzlerin yayın adreslerini bul
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            # Alt ağ yayın adresi hesapla (basit /24 varsayımı)
            parts = ip.split(".")
            if parts[0] != "127":  # loopback hariç
                broadcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                if broadcast not in addrs:
                    addrs.append(broadcast)
    except Exception as e:
        log.debug(f"Yayın adresleri hesaplanırken hata: {e}")

    log.info(f"Yayın adresleri: {addrs}")
    return addrs


def _make_broadcast_socket(port: int, bind: bool = False) -> socket.socket:
    """UDP yayın soketi oluşturur."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if bind:
            sock.bind(("", port))
            log.debug(f"UDP soket {port} portuna bağlandı")
        sock.settimeout(1.0)
        return sock
    except Exception as e:
        log.error(f"{port} portunda yayın soketi oluşturulamadı: {e}", exc_info=True)
        raise


class PeerDiscovery:
    """UDP yayını ile LAN üzerindeki eşleri keşfeder."""

    def __init__(self, username: str, active_room_id: int = 0, on_peers_changed=None):
        self.username = username
        self.active_room_id = active_room_id
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.peers: dict[str, tuple[str, float]] = {}  # ip -> (kullanıcı_adı, son_görülme)
        self.on_peers_changed = on_peers_changed
        self._running = False
        self._lock = threading.Lock()
        log.info(f"EşKeşfi '{username}' kullanıcısı için başlatıldı (Oda: {active_room_id})")

    def set_active_room(self, room_id: int):
        if self.active_room_id != room_id:
            self.active_room_id = room_id
            with self._lock:
                self.peers.clear()
            if self.on_peers_changed:
                self.on_peers_changed([])
            log.debug(f"EşKeşfi aktif oda değiştirildi: {room_id}")

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
            log.info(f"EşKeşfi {DISCOVERY_PORT} portunda başlatıldı")
        except Exception as e:
            log.error(f"EşKeşfi başlatılamadı: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("EşKeşfi durduruluyor...")
        self._running = False
        # HOŞÇAKAL paketi gönder
        try:
            # MSG_BYE + room_id + username
            payload = MSG_BYE + struct.pack("B", self.active_room_id) + self.username.encode("utf-8")
            for addr in self.broadcast_addrs:
                try:
                    self._send_sock.sendto(payload, (addr, DISCOVERY_PORT))
                except Exception:
                    pass
            log.debug("HOŞÇAKAL paketi gönderildi")
        except Exception as e:
            log.warning(f"HOŞÇAKAL paketi gönderilemedi: {e}")
        try:
            self._send_sock.close()
        except Exception as e:
            log.debug(f"Gönderim soketi kapatılırken hata: {e}")
        try:
            self._recv_sock.close()
        except Exception as e:
            log.debug(f"Alım soketi kapatılırken hata: {e}")
        log.info("EşKeşfi durduruldu")

    def _is_local(self, ip: str) -> bool:
        """Verilen IP'nin bu makineye ait olup olmadığını kontrol eder."""
        return ip in self.local_ips

    def _broadcast_loop(self):
        log.debug("Keşif yayın döngüsü başladı")
        while self._running:
            try:
                # MSG_HELLO + room_id + username
                payload = MSG_HELLO + struct.pack("B", self.active_room_id) + self.username.encode("utf-8")
                # Tüm yayın adreslerine gönder
                for addr in self.broadcast_addrs:
                    try:
                        self._send_sock.sendto(payload, (addr, DISCOVERY_PORT))
                    except Exception:
                        pass
            except Exception as e:
                log.warning(f"MERHABA yayını gönderilemedi: {e}")
            time.sleep(HELLO_INTERVAL)
        log.debug("Keşif yayın döngüsü sona erdi")

    def _listen_loop(self):
        log.debug("Keşif dinleme döngüsü başladı")
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]

                # Kendi paketlerimizi atla (tüm yerel IP'leri kontrol et)
                if self._is_local(ip):
                    continue

                if data[0:1] == MSG_HELLO:
                    if len(data) < 2: continue
                    room_id = data[1]
                    if room_id != self.active_room_id: continue
                    
                    name = data[2:].decode("utf-8", errors="replace")
                    with self._lock:
                        was_new = ip not in self.peers
                        self.peers[ip] = (name, time.time())
                    if was_new:
                        log.info(f"Yeni eş keşfedildi: '{name}' - {ip}")
                        if self.on_peers_changed:
                            self.on_peers_changed(self._get_peer_list())

                elif data[0:1] == MSG_BYE:
                    if len(data) < 2: continue
                    room_id = data[1]
                    if room_id != self.active_room_id: continue
                    
                    with self._lock:
                        if ip in self.peers:
                            name = self.peers[ip][0]
                            del self.peers[ip]
                            log.info(f"Eş ayrıldı: '{name}' - {ip}")
                    if self.on_peers_changed:
                        self.on_peers_changed(self._get_peer_list())

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Keşif dinleme döngüsünde hata: {e}", exc_info=True)
                else:
                    break
        log.debug("Keşif dinleme döngüsü sona erdi")

    def _cleanup_loop(self):
        log.debug("Eş temizleme döngüsü başladı")
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
                        log.info(f"Eş zaman aşımına uğradı: '{name}' - {ip}")
                if removed and self.on_peers_changed:
                    self.on_peers_changed(self._get_peer_list())
            except Exception as e:
                log.error(f"Eş temizleme döngüsünde hata: {e}", exc_info=True)
        log.debug("Eş temizleme döngüsü sona erdi")

    def _get_peer_list(self) -> list[tuple[str, str]]:
        """(kullanıcı_adı, ip) listesi döndürür."""
        with self._lock:
            return [(name, ip) for ip, (name, _) in self.peers.items()]


class ChatTransport:
    """UDP yayını ile şifreli metin sohbet mesajları gönderir ve alır. Birden fazla odayı destekler."""

    def __init__(self, username: str, encryption_keys: dict[int, bytes], active_room_id: int = 0, on_message=None):
        self.username = username
        self.keys = encryption_keys  # {oda_id: anahtar_baytları}
        self.active_room_id = active_room_id
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.on_message = on_message  # geri çağırma(gönderen_adı, mesaj_metni, oda_id)
        self._running = False
        log.info(f"SohbetAktarımı '{username}' kullanıcısı için başlatıldı (Oda: {active_room_id})")

    def set_active_room(self, room_id: int):
        if room_id in self.keys:
            self.active_room_id = room_id
            log.debug(f"SohbetAktarımı aktif oda değiştirildi: {room_id}")

    def start(self):
        try:
            self._running = True
            self._send_sock = _make_broadcast_socket(CHAT_PORT)
            self._recv_sock = _make_broadcast_socket(CHAT_PORT, bind=True)

            self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._recv_thread.start()
            log.info(f"SohbetAktarımı {CHAT_PORT} portunda başlatıldı")
        except Exception as e:
            log.error(f"SohbetAktarımı başlatılamadı: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("SohbetAktarımı durduruluyor...")
        self._running = False
        try:
            self._send_sock.close()
        except Exception as e:
            log.debug(f"Sohbet gönderim soketi kapatılırken hata: {e}")
        try:
            self._recv_sock.close()
        except Exception as e:
            log.debug(f"Sohbet alım soketi kapatılırken hata: {e}")
        log.info("SohbetAktarımı durduruldu")

    def send_message(self, text: str, room_id: int):
        """Belirtilen odaya şifreli sohbet mesajı yayınlar."""
        if room_id not in self.keys:
            log.warning(f"Sohbet mesajı gönderilemedi: {room_id} numaralı oda için anahtar yok")
            return
            
        try:
            # Paketleme: kullanıcı_adı_uzunluğu (1 bayt) + kullanıcı_adı + mesaj
            name_bytes = self.username.encode("utf-8")[:255]
            msg_bytes = text.encode("utf-8")
            payload = struct.pack("B", len(name_bytes)) + name_bytes + msg_bytes
            
            # Seçilen odanın anahtarıyla şifrele
            encrypted = encrypt(payload, self.keys[room_id])
            
            # Paket: MSG_CHAT (1 bayt) + ODA_ID (1 bayt) + Şifreli Veri
            room_byte = struct.pack("B", room_id)
            packet = MSG_CHAT + room_byte + encrypted
            
            for addr in self.broadcast_addrs:
                try:
                    self._send_sock.sendto(packet, (addr, CHAT_PORT))
                except Exception:
                    pass
            log.debug(f"Sohbet mesajı gönderildi (Oda {room_id}): '{text[:50]}' ({len(packet)} bayt)")
        except Exception as e:
            log.error(f"Sohbet mesajı gönderilemedi: {e}", exc_info=True)

    def _listen_loop(self):
        log.debug("Sohbet dinleme döngüsü başladı")
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
                    if room_id != self.active_room_id:
                        continue
                        
                    # Odaya abone miyiz kontrol et (zaten active_room ise aboneyizdir ama emin olalım)
                    if room_id not in self.keys:
                        continue
                        
                    encrypted = data[2:]
                    plaintext = decrypt(encrypted, self.keys[room_id])
                    
                    if plaintext is None:
                        log.debug(f"{ip} adresinden sohbet alındı ama şifre çözülemedi (Oda {room_id} yanlış anahtar?)")
                        continue
                        
                    name_len = plaintext[0]
                    sender = plaintext[1:1 + name_len].decode("utf-8", errors="replace")
                    message = plaintext[1 + name_len:].decode("utf-8", errors="replace")
                    log.debug(f"'{sender}' ({ip}) adresinden sohbet alındı (Oda {room_id}): '{message[:50]}'")
                    
                    if self.on_message:
                        self.on_message(sender, message, room_id)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    log.error(f"Sohbet dinleme döngüsünde hata: {e}", exc_info=True)
                else:
                    break
        log.debug("Sohbet dinleme döngüsü sona erdi")


class VoiceTransport:
    """UDP yayını ile şifreli ses çerçeveleri gönderir ve alır. Birden fazla odayı destekler."""

    def __init__(self, username: str, encryption_keys: dict[int, bytes], active_room_id: int = 0, on_voice=None):
        self.username = username
        self.keys = encryption_keys  # {oda_id: anahtar_baytları}
        self.active_room_id = active_room_id
        self.local_ips = _get_all_local_ips()
        self.broadcast_addrs = _get_broadcast_addresses()
        self.on_voice = on_voice  # geri çağırma(gönderen_adı, ses_baytları, oda_id)
        self._running = False
        log.info(f"SesAktarımı '{username}' kullanıcısı için başlatıldı (Oda: {active_room_id})")

    def set_active_room(self, room_id: int):
        if room_id in self.keys:
            self.active_room_id = room_id
            log.debug(f"SesAktarımı aktif oda değiştirildi: {room_id}")

    def start(self):
        try:
            self._running = True
            self._send_sock = _make_broadcast_socket(VOICE_PORT)
            self._recv_sock = _make_broadcast_socket(VOICE_PORT, bind=True)

            self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._recv_thread.start()
            log.info(f"SesAktarımı {VOICE_PORT} portunda başlatıldı")
        except Exception as e:
            log.error(f"SesAktarımı başlatılamadı: {e}", exc_info=True)
            self._running = False

    def stop(self):
        log.info("SesAktarımı durduruluyor...")
        self._running = False
        try:
            self._send_sock.close()
        except Exception as e:
            log.debug(f"Ses gönderim soketi kapatılırken hata: {e}")
        try:
            self._recv_sock.close()
        except Exception as e:
            log.debug(f"Ses alım soketi kapatılırken hata: {e}")
        log.info("SesAktarımı durduruldu")

    def send_voice(self, audio_data: bytes, room_id: int):
        """Belirtilen odaya şifreli ses çerçevesi yayınlar."""
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
            log.error(f"Ses çerçevesi gönderilemedi: {e}", exc_info=True)

    def _listen_loop(self):
        log.debug("Ses dinleme döngüsü başladı")
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
                    
                    if room_id != self.active_room_id:
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
                    log.error(f"Ses dinleme döngüsünde hata: {e}", exc_info=True)
                else:
                    break
        log.debug("Ses dinleme döngüsü sona erdi")
