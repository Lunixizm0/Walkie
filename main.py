"""
Walkie-Talkie LAN Uygulaması
==============================
LAN için sunucusuz, eşler arası walkie-talkie.
Özellikler: otomatik keşif, şifreli metin sohbet, bas-konuş sesli iletişim.

Giriş noktası — tüm modülleri birbirine bağlar ve uygulamayı başlatır.
"""

import sys
import logging
from crypto_utils import derive_key, get_genel_key
from network import PeerDiscovery, ChatTransport, VoiceTransport
from audio_engine import AudioEngine
from gui import StartupDialog, WalkieTalkieGUI, ROOM_NAMES

# ── Günlükleme yapılandırması ──────────────────────────────────
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
    log.info("Walkie-Talkie LAN Uygulaması başlatılıyor")
    log.info("=" * 60)

    # ── Kullanıcı adı ve parola almak için giriş penceresi ──
    try:
        dialog = StartupDialog()
        dialog.mainloop()

        if dialog.result is None:
            log.info("Kullanıcı giriş penceresini iptal etti — çıkılıyor")
            sys.exit(0)

        username, rooms_passwords, minimize_to_tray_enabled = dialog.result
        log.info(f"Kullanıcı '{username}' bilgilerini girdi (Tray: {minimize_to_tray_enabled})")
    except Exception as e:
        log.error(f"Giriş penceresinde hata: {e}", exc_info=True)
        sys.exit(1)

    # ── Şifreleme anahtarlarını türet ──────────────────────────
    try:
        encryption_keys = {}
        for room_id, passphrase in rooms_passwords.items():
            if room_id == 0:
                encryption_keys[0] = get_genel_key()
                log.info("Genel oda için sabit anahtar alındı")
            else:
                encryption_keys[room_id] = derive_key(passphrase)
                log.info(f"'{ROOM_NAMES.get(room_id)}' odası için anahtar türetildi")
    except Exception as e:
        log.error(f"Şifreleme anahtarları türetilemedi: {e}", exc_info=True)
        sys.exit(1)

    # ── Bileşenleri başlat ──────────────────────────────────
    try:
        active_room_id = list(encryption_keys.keys())[0] if encryption_keys else 0

        log.info("SesAktarımı başlatılıyor...")
        voice_transport = VoiceTransport(
            username=username,
            encryption_keys=encryption_keys,
            active_room_id=active_room_id
        )

        log.info("SohbetAktarımı başlatılıyor...")
        chat_transport = ChatTransport(
            username=username,
            encryption_keys=encryption_keys,
            active_room_id=active_room_id
        )

        log.info("EşKeşfi başlatılıyor...")
        peer_discovery = PeerDiscovery(
            username=username,
            active_room_id=active_room_id
        )

        log.info("SesMotoru başlatılıyor...")
        audio_engine = AudioEngine(
            on_audio_captured=lambda data, room_id: voice_transport.send_voice(data, room_id)
        )

        # Ses alma geri çağırması → sesi çal
        voice_transport.on_voice = lambda sender, data, room_id: audio_engine.play_audio(data)

        def handle_channel_change(new_room_id):
            log.info(f"Kanal değiştirildi: {new_room_id}. Ağ katmanları güncelleniyor...")
            peer_discovery.set_active_room(new_room_id)
            chat_transport.set_active_room(new_room_id)
            voice_transport.set_active_room(new_room_id)

        log.info("Arayüz başlatılıyor...")
        active_rooms = list(encryption_keys.keys())
        gui = WalkieTalkieGUI(
            username=username,
            active_rooms=active_rooms,
            minimize_to_tray_enabled=minimize_to_tray_enabled,
            on_send_chat=lambda text, room_id: chat_transport.send_message(text, room_id),
            on_ptt_start=lambda room_id: audio_engine.start_capture(room_id),
            on_ptt_stop=lambda: audio_engine.stop_capture(),
            on_channel_changed=handle_channel_change,
            on_vad_toggled=lambda enabled, room_id: audio_engine.set_vad_enabled(enabled, room_id),
            on_play_beep=lambda freq, dur: audio_engine.play_beep(freq, dur),
            on_close=lambda: shutdown(),
        )

        # ── Geri çağırmaları bağla ──────────────────────────────
        def on_peers_changed(peers):
            try:
                gui.update_peers(peers)
                log.debug(f"Eşler güncellendi: {[(name, ip) for name, ip in peers]}")
            except Exception as e:
                log.error(f"on_peers_changed geri çağırmasında hata: {e}", exc_info=True)

        def on_chat_received(sender, message, room_id):
            try:
                gui.append_chat(sender, message, room_id, is_self=False)
                log.debug(f"'{sender}' adresinden sohbet alındı: '{message[:50]}'")
            except Exception as e:
                log.error(f"on_chat_received geri çağırmasında hata: {e}", exc_info=True)

        chat_transport.on_message = on_chat_received
        peer_discovery.on_peers_changed = on_peers_changed

    except Exception as e:
        log.error(f"Bileşenler başlatılamadı: {e}", exc_info=True)
        sys.exit(1)

    # ── Kapatma yöneticisi ──────────────────────────────────
    def shutdown():
        try:
            log.info("Kapatma başlatıldı — tüm servisler durduruluyor")
            peer_discovery.stop()
            chat_transport.stop()
            voice_transport.stop()
            audio_engine.shutdown()
            log.info("Tüm servisler başarıyla durduruldu")
        except Exception as e:
            log.error(f"Kapatma sırasında hata: {e}", exc_info=True)

    gui.on_close = shutdown

    # ── Her şeyi başlat ─────────────────────────────────────
    try:
        log.info("Tüm ağ servisleri başlatılıyor...")
        peer_discovery.start()
        chat_transport.start()
        voice_transport.start()
        log.info("Tüm servisler başarıyla başlatıldı")
    except Exception as e:
        log.error(f"Servisler başlatılamadı: {e}", exc_info=True)
        shutdown()
        sys.exit(1)

    gui.add_system_message("Uygulama başlatıldı · Uçtan uca şifreli 🔒")
    gui.add_system_message(f"{username} olarak şu kanallara bağlandınız: {[ROOM_NAMES[r] for r in active_rooms]}")

    log.info("Arayüz ana döngüsüne giriliyor")
    # Arayüz ana döngüsünü başlat (pencere kapanana kadar bloke eder)
    gui.mainloop()

    log.info("Uygulama sonlandı")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"main içinde yakalanmamış istisna: {e}", exc_info=True)
        sys.exit(1)
