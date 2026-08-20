from pathlib import Path
import sys

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import pytest
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
