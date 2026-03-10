"""
Walkie-Talkie uygulaması için şifreleme araçları.
Paylaşılan parola ile AES-GCM kimlik doğrulamalı şifreleme kullanır.
"""

import os
import logging
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger(__name__)

# Sabit tuz: aynı parolayı kullanan tüm istemciler aynı anahtarı türetir
_FIXED_SALT = b"walkie-talkie-lan-salt-2026"

# Genel oda için sabit anahtar (şifresiz odanın herkes tarafından dinlenebilmesi için)
_GENEL_KEY = b"ortak_genel_oda_anahtari_2026_!!"  # 32 byte


def get_genel_key() -> bytes:
    """Genel (şifresiz) oda için kullanılacak sabit 32 baytlık AES anahtarını döndürür."""
    return _GENEL_KEY


def derive_key(passphrase: str) -> bytes:
    """PBKDF2 kullanarak paroladan 256-bit AES anahtarı türetir."""
    try:
        log.debug("Paroladan şifreleme anahtarı türetiliyor (PBKDF2, 100k iterasyon)")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_FIXED_SALT,
            iterations=100_000,
        )
        key = kdf.derive(passphrase.encode("utf-8"))
        log.info("Şifreleme anahtarı başarıyla türetildi")
        return key
    except Exception as e:
        log.error(f"Şifreleme anahtarı türetilemedi: {e}", exc_info=True)
        raise


def encrypt(data: bytes, key: bytes) -> bytes:
    """
    Veriyi AES-256-GCM ile şifreler.
    Döndürür: nonce (12 bayt) + şifreli metin + etiket
    """
    try:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        log.debug(f"{len(data)} bayt şifrelendi -> {len(nonce) + len(ciphertext)} bayt")
        return nonce + ciphertext
    except Exception as e:
        log.error(f"Şifreleme başarısız: {e}", exc_info=True)
        raise


def decrypt(payload: bytes, key: bytes) -> bytes | None:
    """
    AES-256-GCM verisinin şifresini çözer.
    Beklenen format: nonce (12 bayt) + şifreli metin + etiket
    Düz metin baytları döndürür, şifre çözme başarısız olursa None döner.
    """
    if len(payload) < 12:
        log.warning(f"Şifre çözme başarısız: veri çok kısa ({len(payload)} bayt, en az 12 gerekli)")
        return None
    try:
        aesgcm = AESGCM(key)
        nonce = payload[:12]
        ciphertext = payload[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        log.debug(f"{len(payload)} bayt şifresi çözüldü -> {len(plaintext)} bayt")
        return plaintext
    except Exception as e:
        log.debug(f"Şifre çözme başarısız (muhtemelen yanlış anahtar veya bozuk veri): {e}")
        return None
