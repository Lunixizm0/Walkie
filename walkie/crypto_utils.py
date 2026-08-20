import logging
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .config import get_config, get_general_room_config

log = logging.getLogger(__name__)


def get_general_key() -> bytes:
    cfg = get_general_room_config()
    return bytes.fromhex(cfg["encryption_key"])


def derive_key(passphrase: str) -> bytes:
    try:
        cfg = get_config()
        salt = cfg["general_room"]["salt"].encode("utf-8")
        log.debug("Deriving encryption key from passphrase (PBKDF2, 100k iterations)")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        key = kdf.derive(passphrase.encode("utf-8"))
        log.info("Encryption key derived successfully")
        return key
    except Exception as e:
        log.error(f"Failed to derive encryption key: {e}", exc_info=True)
        raise


def encrypt(data: bytes, key: bytes) -> bytes:
    try:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        log.debug(f"{len(data)} bytes encrypted -> {len(nonce) + len(ciphertext)} bytes")
        return nonce + ciphertext
    except Exception as e:
        log.error(f"Encryption failed: {e}", exc_info=True)
        raise


def decrypt(payload: bytes, key: bytes) -> bytes | None:
    if len(payload) < 12:
        log.warning(f"Decryption failed: data too short ({len(payload)} bytes, need at least 12)")
        return None
    try:
        aesgcm = AESGCM(key)
        nonce = payload[:12]
        ciphertext = payload[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        log.debug(f"{len(payload)} bytes decrypted -> {len(plaintext)} bytes")
        return plaintext
    except Exception as e:
        log.debug(f"Decryption failed (wrong key or corrupted data): {e}")
        return None
