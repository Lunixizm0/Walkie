from pathlib import Path
import sys

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from walkie.config import _ecdh_keypair, _ecdh_shared_secret, _derive_exchange_key


def test_ecdh_shared_secret():
    priv1, pub1 = _ecdh_keypair()
    priv2, pub2 = _ecdh_keypair()
    secret1 = _ecdh_shared_secret(priv1, pub2)
    secret2 = _ecdh_shared_secret(priv2, pub1)
    assert secret1 == secret2


def test_ecdh_different_keys():
    priv1, pub1 = _ecdh_keypair()
    priv2, pub2 = _ecdh_keypair()
    priv3, pub3 = _ecdh_keypair()
    secret1 = _ecdh_shared_secret(priv1, pub2)
    secret2 = _ecdh_shared_secret(priv1, pub3)
    assert secret1 != secret2


def test_derive_exchange_key():
    key1 = _derive_exchange_key(b"shared_secret_1")
    key2 = _derive_exchange_key(b"shared_secret_2")
    assert key1 != key2
    assert len(key1) == 32
    assert len(key2) == 32


def test_derive_exchange_key_deterministic():
    key1 = _derive_exchange_key(b"same_secret")
    key2 = _derive_exchange_key(b"same_secret")
    assert key1 == key2


def test_keypair_returns_valid_types():
    priv, pub = _ecdh_keypair()
    assert isinstance(priv, ec.EllipticCurvePrivateKey)
    assert isinstance(pub, bytes)


def test_keypair_pub_is_pem():
    priv, pub = _ecdh_keypair()
    assert pub.startswith(b"-----BEGIN PUBLIC KEY-----")
    assert pub.endswith(b"-----END PUBLIC KEY-----\n")


def test_keypairs_are_unique():
    pairs = [_ecdh_keypair() for _ in range(20)]
    pubs = [pub for _, pub in pairs]
    assert len(set(pubs)) == 20


def test_shared_secret_non_empty():
    priv1, _ = _ecdh_keypair()
    _, pub2 = _ecdh_keypair()
    secret = _ecdh_shared_secret(priv1, pub2)
    assert isinstance(secret, bytes)
    assert len(secret) > 0


def test_shared_secret_consistent_length():
    lengths = set()
    for _ in range(10):
        priv1, _ = _ecdh_keypair()
        _, pub2 = _ecdh_keypair()
        secret = _ecdh_shared_secret(priv1, pub2)
        lengths.add(len(secret))
    assert len(lengths) == 1


def test_derive_exchange_key_returns_32_bytes():
    for secret in [b"short", b"a" * 1000, b"\x00" * 32]:
        key = _derive_exchange_key(secret)
        assert len(key) == 32


def test_derive_exchange_key_deterministic_with_various_inputs():
    inputs = [b"password1", b"password2", b"", b"\x00" * 64, b"very long secret " * 100]
    for inp in inputs:
        k1 = _derive_exchange_key(inp)
        k2 = _derive_exchange_key(inp)
        assert k1 == k2


def test_derive_exchange_key_different_inputs_differ():
    keys = set()
    for i in range(20):
        key = _derive_exchange_key(f"input_{i}".encode())
        keys.add(key)
    assert len(keys) == 20


def test_ecdh_full_exchange_simulation():
    alice_priv, alice_pub = _ecdh_keypair()
    bob_priv, bob_pub = _ecdh_keypair()
    alice_shared = _ecdh_shared_secret(alice_priv, bob_pub)
    bob_shared = _ecdh_shared_secret(bob_priv, alice_pub)
    assert alice_shared == bob_shared
    alice_key = _derive_exchange_key(alice_shared)
    bob_key = _derive_exchange_key(bob_shared)
    assert alice_key == bob_key
    assert len(alice_key) == 32
