import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import struct
import pytest
from walkie.network import (
    _build_peer_packet, _parse_peer_packet, _Deduplicator,
    MSG_HELLO, MSG_BYE, MSG_CHAT, MSG_VOICE,
    _get_all_local_ips, _get_broadcast_addresses,
)


def test_build_peer_packet_hello():
    packet = _build_peer_packet(MSG_HELLO, {0, 1}, "alice")
    assert packet[0:1] == MSG_HELLO
    assert packet[1] == 2
    assert packet[2] == 0
    assert packet[3] == 1
    assert packet[4:].decode() == "alice"


def test_build_peer_packet_bye():
    packet = _build_peer_packet(MSG_BYE, {2}, "bob")
    assert packet[0:1] == MSG_BYE
    assert packet[1] == 1
    assert packet[2] == 2
    assert packet[3:].decode() == "bob"


def test_build_peer_packet_empty_rooms():
    packet = _build_peer_packet(MSG_HELLO, set(), "user")
    assert packet[1] == 0


def test_parse_peer_packet_valid():
    packet = _build_peer_packet(MSG_HELLO, {0, 2}, "charlie")
    result = _parse_peer_packet(packet)
    assert result is not None
    room_ids, username = result
    assert room_ids == {0, 2}
    assert username == "charlie"


def test_parse_peer_packet_too_short():
    assert _parse_peer_packet(b"\x01") is None


def test_parse_peer_packet_zero_rooms():
    data = MSG_HELLO + struct.pack("B", 0) + b"nobody"
    assert _parse_peer_packet(data) is None


def test_parse_peer_packet_truncated():
    data = MSG_HELLO + struct.pack("B", 3) + b"\x00\x01"
    assert _parse_peer_packet(data) is None


def test_parse_peer_packet_unicode():
    packet = _build_peer_packet(MSG_HELLO, {0}, "u\u00e9\u00e8")
    result = _parse_peer_packet(packet)
    assert result is not None
    assert result[1] == "u\u00e9\u00e8"


def test_deduplicator_first_seen():
    d = _Deduplicator()
    assert d.is_duplicate(b"hello") is False


def test_deduplicator_duplicate():
    d = _Deduplicator()
    d.is_duplicate(b"hello")
    assert d.is_duplicate(b"hello") is True


def test_deduplicator_different_data():
    d = _Deduplicator()
    d.is_duplicate(b"hello")
    assert d.is_duplicate(b"world") is False


def test_deduplicator_clear():
    d = _Deduplicator()
    d.is_duplicate(b"hello")
    d.clear()
    assert d.is_duplicate(b"hello") is False


def test_deduplicator_max_size():
    d = _Deduplicator(max_size=3)
    d.is_duplicate(b"a")
    d.is_duplicate(b"b")
    d.is_duplicate(b"c")
    d.is_duplicate(b"d")
    assert d.is_duplicate(b"a") is False
    assert d.is_duplicate(b"d") is True


def test_get_all_local_ips():
    ips = _get_all_local_ips()
    assert "127.0.0.1" in ips
    assert all(isinstance(ip, str) for ip in ips)


def test_get_broadcast_addresses():
    addrs = _get_broadcast_addresses()
    assert "<broadcast>" in addrs
    assert all(isinstance(a, str) for a in addrs)
