"""
Encryption utilities for the Walkie-Talkie application.
Uses AES-GCM for authenticated encryption with a shared passphrase.
"""

import os
import logging
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger(__name__)

# Fixed salt so all peers with the same passphrase derive the same key
_FIXED_SALT = b"walkie-talkie-lan-salt-2026"


def derive_key(passphrase: str) -> bytes:
    """Derive a 256-bit AES key from a passphrase using PBKDF2."""
    try:
        log.debug("Deriving encryption key from passphrase (PBKDF2, 100k iterations)")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_FIXED_SALT,
            iterations=100_000,
        )
        key = kdf.derive(passphrase.encode("utf-8"))
        log.info("Encryption key derived successfully")
        return key
    except Exception as e:
        log.error(f"Failed to derive encryption key: {e}", exc_info=True)
        raise


def encrypt(data: bytes, key: bytes) -> bytes:
    """
    Encrypt data with AES-256-GCM.
    Returns: nonce (12 bytes) + ciphertext + tag
    """
    try:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        log.debug(f"Encrypted {len(data)} bytes -> {len(nonce) + len(ciphertext)} bytes")
        return nonce + ciphertext
    except Exception as e:
        log.error(f"Encryption failed: {e}", exc_info=True)
        raise


def decrypt(payload: bytes, key: bytes) -> bytes | None:
    """
    Decrypt AES-256-GCM payload.
    Expects: nonce (12 bytes) + ciphertext + tag
    Returns plaintext bytes, or None if decryption fails (wrong key).
    """
    if len(payload) < 12:
        log.warning(f"Decrypt failed: payload too short ({len(payload)} bytes, need >= 12)")
        return None
    try:
        aesgcm = AESGCM(key)
        nonce = payload[:12]
        ciphertext = payload[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        log.debug(f"Decrypted {len(payload)} bytes -> {len(plaintext)} bytes")
        return plaintext
    except Exception as e:
        log.debug(f"Decryption failed (likely wrong key or corrupted data): {e}")
        return None
