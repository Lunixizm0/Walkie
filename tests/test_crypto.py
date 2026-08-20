import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from walkie.crypto_utils import encrypt, decrypt


def test_encrypt_decrypt_roundtrip():
    key = b"0" * 32
    data = b"hello world"
    encrypted = encrypt(data, key)
    assert encrypted != data
    decrypted = decrypt(encrypted, key)
    assert decrypted == data


def test_decrypt_wrong_key():
    key1 = b"0" * 32
    key2 = b"1" * 32
    data = b"secret data"
    encrypted = encrypt(data, key1)
    result = decrypt(encrypted, key2)
    assert result is None


def test_decrypt_too_short():
    result = decrypt(b"short", b"0" * 32)
    assert result is None


def test_encrypt_different_nonces():
    key = b"0" * 32
    data = b"same data"
    enc1 = encrypt(data, key)
    enc2 = encrypt(data, key)
    assert enc1 != enc2
    assert decrypt(enc1, key) == data
    assert decrypt(enc2, key) == data
