"""
Walkie-Talkie LAN Uygulaması
==============================
LAN için sunucusuz, eşler arası walkie-talkie.
Özellikler: otomatik keşif, şifreli metin sohbet, bas-konuş sesli iletişim.

Giriş noktası — tüm modülleri birbirine bağlar ve uygulamayı başlatır.
"""

import sys
import logging
from crypto_utils import derive_key
from network import PeerDiscovery, ChatTransport, VoiceTransport
from audio_engine import AudioEngine
from gui import StartupDialog, WalkieTalkieGUI

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

        username, passphrase = dialog.result
        log.info(f"Kullanıcı '{username}' bilgilerini girdi")
    except Exception as e:
        log.error(f"Giriş penceresinde hata: {e}", exc_info=True)
        sys.exit(1)

    # ── Şifreleme anahtarını türet ──────────────────────────
    try:
        encryption_key = derive_key(passphrase)
        log.info("Paroladan şifreleme anahtarı türetildi")
    except Exception as e:
        log.error(f"Şifreleme anahtarı türetilemedi: {e}", exc_info=True)
        sys.exit(1)

    # ── Bileşenleri başlat ──────────────────────────────────
    try:
        log.info("SesAktarımı başlatılıyor...")
        voice_transport = VoiceTransport(
            username=username,
            encryption_key=encryption_key,
        )

        log.info("SesMotoru başlatılıyor...")
        audio_engine = AudioEngine(
            on_audio_captured=lambda data: voice_transport.send_voice(data)
        )

        # Ses alma geri çağırması → sesi çal
        voice_transport.on_voice = lambda sender, data: audio_engine.play_audio(data)

        log.info("SohbetAktarımı başlatılıyor...")
        chat_transport = ChatTransport(
            username=username,
            encryption_key=encryption_key,
        )

        log.info("Arayüz başlatılıyor...")
        gui = WalkieTalkieGUI(
            username=username,
            on_send_chat=lambda text: chat_transport.send_message(text),
            on_ptt_start=lambda: audio_engine.start_capture(),
            on_ptt_stop=lambda: audio_engine.stop_capture(),
            on_close=lambda: shutdown(),
        )
    except Exception as e:
        log.error(f"Bileşenler başlatılamadı: {e}", exc_info=True)
        sys.exit(1)

    # ── Geri çağırmaları bağla ──────────────────────────────
    def on_peers_changed(peers):
        try:
            gui.update_peers(peers)
            log.debug(f"Eşler güncellendi: {[(name, ip) for name, ip in peers]}")
        except Exception as e:
            log.error(f"on_peers_changed geri çağırmasında hata: {e}", exc_info=True)

    def on_chat_received(sender, message):
        try:
            gui.add_chat_message(sender, message, is_self=False)
            log.debug(f"'{sender}' adresinden sohbet alındı: '{message[:50]}'")
        except Exception as e:
            log.error(f"on_chat_received geri çağırmasında hata: {e}", exc_info=True)

    chat_transport.on_message = on_chat_received

    try:
        log.info("EşKeşfi başlatılıyor...")
        peer_discovery = PeerDiscovery(
            username=username,
            on_peers_changed=on_peers_changed,
        )
    except Exception as e:
        log.error(f"EşKeşfi başlatılamadı: {e}", exc_info=True)
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

    gui.add_system_message("Kanala bağlanıldı · Uçtan uca şifreli 🔒")
    gui.add_system_message(f"{username} olarak giriş yapıldı · Eşler aranıyor…")

    log.info("Arayüz ana döngüsüne giriliyor")
    # Arayüz ana döngüsünü başlat (pencere kapanana kadar bloke eder)
    gui.run()

    log.info("Uygulama sonlandı")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"main içinde yakalanmamış istisna: {e}", exc_info=True)
        sys.exit(1)
