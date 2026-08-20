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


def test_aad_roundtrip():
    key = b"0" * 32
    data = b"authenticated data"
    aad = b"room_1_context"
    encrypted = encrypt(data, key, aad=aad)
    assert encrypted is not None
    decrypted = decrypt(encrypted, key, aad=aad)
    assert decrypted == data


def test_aad_wrong_aad_fails():
    key = b"0" * 32
    data = b"authenticated data"
    aad1 = b"room_1"
    aad2 = b"room_2"
    encrypted = encrypt(data, key, aad=aad1)
    result = decrypt(encrypted, key, aad=aad2)
    assert result is None


def test_aad_none_vs_bytes():
    key = b"0" * 32
    data = b"test data"
    enc_no_aad = encrypt(data, key, aad=None)
    enc_with_aad = encrypt(data, key, aad=b"extra")
    assert enc_no_aad != enc_with_aad
    assert decrypt(enc_no_aad, key, aad=None) == data
    assert decrypt(enc_with_aad, key, aad=b"extra") == data


def test_encrypt_empty_data():
    key = b"0" * 32
    encrypted = encrypt(b"", key)
    assert encrypted is not None
    assert len(encrypted) > 0
    decrypted = decrypt(encrypted, key)
    assert decrypted == b""


def test_encrypt_large_data():
    key = b"0" * 32
    data = b"x" * 100000
    encrypted = encrypt(data, key)
    assert encrypted is not None
    decrypted = decrypt(encrypted, key)
    assert decrypted == data


def test_decrypt_12_bytes_only_nonce():
    key = b"0" * 32
    result = decrypt(b"\x00" * 12, key)
    assert result is None


def test_decrypt_13_bytes():
    key = b"0" * 32
    result = decrypt(b"\x00" * 13, key)
    assert result is None


def test_decrypt_corrupted_ciphertext():
    key = b"0" * 32
    data = b"original data"
    encrypted = encrypt(data, key)
    corrupted = bytearray(encrypted)
    corrupted[-1] ^= 0xFF
    result = decrypt(bytes(corrupted), key)
    assert result is None


def test_decrypt_corrupted_nonce():
    key = b"0" * 32
    data = b"original data"
    encrypted = encrypt(data, key)
    corrupted = bytearray(encrypted)
    corrupted[0] ^= 0xFF
    result = decrypt(bytes(corrupted), key)
    assert result is None


def test_encrypt_binary_data():
    key = b"0" * 32
    data = bytes(range(256)) * 100
    encrypted = encrypt(data, key)
    decrypted = decrypt(encrypted, key)
    assert decrypted == data


def test_encrypt_unicode_data():
    key = b"0" * 32
    data = "Turkish: cagris sayin".encode("utf-8")
    encrypted = encrypt(data, key)
    decrypted = decrypt(encrypted, key)
    assert decrypted == data


def test_encrypt_single_byte():
    key = b"0" * 32
    data = b"\xff"
    encrypted = encrypt(data, key)
    decrypted = decrypt(encrypted, key)
    assert decrypted == data


def test_aad_empty_bytes():
    key = b"0" * 32
    data = b"test"
    encrypted = encrypt(data, key, aad=b"")
    decrypted = decrypt(encrypted, key, aad=b"")
    assert decrypted == data


def test_aad_empty_vs_none():
    key = b"0" * 32
    data = b"test"
    enc_empty = encrypt(data, key, aad=b"")
    enc_none = encrypt(data, key, aad=None)
    assert enc_empty != enc_none
    assert decrypt(enc_empty, key, aad=b"") == data
    assert decrypt(enc_none, key, aad=None) == data


def test_many_encryptions_unique_nonces():
    key = b"0" * 32
    data = b"test"
    nonces = set()
    for _ in range(100):
        encrypted = encrypt(data, key)
        nonce = encrypted[:12]
        nonces.add(nonce)
    assert len(nonces) == 100
