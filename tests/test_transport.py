import sys
import os
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import socket
import struct
import time
import threading
from unittest.mock import MagicMock

import pytest
from walkie.network import (
    Transport, _Deduplicator,
    MSG_CHAT, MSG_VOICE,
    CHAT_FRAG_TIMEOUT, CHAT_FRAG_MAX_PENDING,
)
from walkie.crypto_utils import encrypt, decrypt


def _make_transport(port=50090, msg_type=MSG_VOICE, fragmented=False, rooms=None, keys=None, peer_disc=None):
    if rooms is None:
        rooms = {0, 1}
    if keys is None:
        keys = {0: b"0" * 32, 1: b"1" * 32}
    return Transport(
        username="testuser",
        encryption_keys=keys,
        active_rooms=rooms,
        port=port,
        message_type=msg_type,
        fragmented=fragmented,
        peer_discovery=peer_disc,
    )


def _make_transport_with_mock(port, keys, rooms, msg_type, fragmented, on_receive):
    mock_disc = MagicMock()
    mock_disc.get_peers_for_room.return_value = [("peer", "127.0.0.1")]
    return Transport(
        username="testuser",
        encryption_keys=keys,
        active_rooms=rooms,
        port=port,
        message_type=msg_type,
        fragmented=fragmented,
        on_receive=on_receive,
        peer_discovery=mock_disc,
    )


class TestTransportAssembly:

    def test_assemble_single_fragment(self):
        t = _make_transport()
        key = b"0" * 32
        data = b"hello world"
        encrypted = encrypt(data, key, aad=struct.pack("B", 0))
        result = t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=1, encrypted=encrypted)
        assert result is not None
        assert result == encrypted

    def test_assemble_multiple_fragments(self):
        t = _make_transport()
        key = b"0" * 32
        chunks = [b"chunk1", b"chunk2", b"chunk3"]
        encrypted_chunks = [encrypt(c, key, aad=struct.pack("B", 0)) for c in chunks]
        for i, enc in enumerate(encrypted_chunks):
            result = t._assemble_fragment(msg_id=10, frag_idx=i, total_frags=3, encrypted=enc)
            if i < 2:
                assert result is None
            else:
                assert result is not None
                assert result == b"".join(encrypted_chunks)

    def test_assemble_duplicate_frag_idx_ignored(self):
        t = _make_transport()
        key = b"0" * 32
        enc1 = encrypt(b"data1", key, aad=struct.pack("B", 0))
        enc2 = encrypt(b"data2", key, aad=struct.pack("B", 0))
        t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=2, encrypted=enc1)
        result = t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=2, encrypted=enc2)
        assert result is None

    def test_assemble_wrong_total_frags_rejected(self):
        t = _make_transport()
        key = b"0" * 32
        enc = encrypt(b"data", key, aad=struct.pack("B", 0))
        t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=3, encrypted=enc)
        result = t._assemble_fragment(msg_id=1, frag_idx=1, total_frags=2, encrypted=enc)
        assert result is None

    def test_assemble_frag_idx_out_of_range(self):
        t = _make_transport()
        key = b"0" * 32
        enc = encrypt(b"data", key, aad=struct.pack("B", 0))
        result = t._assemble_fragment(msg_id=1, frag_idx=5, total_frags=3, encrypted=enc)
        assert result is None

    def test_assemble_max_pending_evicts_oldest(self):
        t = _make_transport()
        key = b"0" * 32
        enc = encrypt(b"data", key, aad=struct.pack("B", 0))
        for i in range(CHAT_FRAG_MAX_PENDING + 5):
            t._assemble_fragment(msg_id=i, frag_idx=0, total_frags=2, encrypted=enc)
        assert len(t._assembly) <= CHAT_FRAG_MAX_PENDING

    def test_assemble_stale_cleanup(self):
        t = _make_transport()
        key = b"0" * 32
        enc = encrypt(b"data", key, aad=struct.pack("B", 0))
        t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=2, encrypted=enc)
        t._assembly[1]["ts"] = time.monotonic() - CHAT_FRAG_TIMEOUT - 1
        t._cleanup_stale_assembly()
        assert 1 not in t._assembly

    def test_assemble_fresh_not_cleaned(self):
        t = _make_transport()
        key = b"0" * 32
        enc = encrypt(b"data", key, aad=struct.pack("B", 0))
        t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=2, encrypted=enc)
        t._cleanup_stale_assembly()
        assert 1 in t._assembly

    def test_assemble_completed_entry_deleted(self):
        t = _make_transport()
        key = b"0" * 32
        enc = encrypt(b"data", key, aad=struct.pack("B", 0))
        t._assemble_fragment(msg_id=42, frag_idx=0, total_frags=1, encrypted=enc)
        assert 42 not in t._assembly

    def test_assemble_same_msg_id_new_message_after_complete(self):
        t = _make_transport()
        key = b"0" * 32
        enc = encrypt(b"first", key, aad=struct.pack("B", 0))
        r1 = t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=1, encrypted=enc)
        assert r1 is not None
        enc2 = encrypt(b"second", key, aad=struct.pack("B", 0))
        r2 = t._assemble_fragment(msg_id=1, frag_idx=0, total_frags=1, encrypted=enc2)
        assert r2 is not None


class TestTransportState:

    def test_active_rooms_property_returns_copy(self):
        t = _make_transport(rooms={0, 1})
        rooms = t.active_rooms
        rooms.add(99)
        assert 99 not in t.active_rooms

    def test_set_active_rooms_clears_dedup(self):
        t = _make_transport()
        t._dedup.is_duplicate(b"test")
        t.set_active_rooms({0, 1})
        assert t._dedup.is_duplicate(b"test") is False

    def test_set_active_rooms_clears_assembly(self):
        t = _make_transport(fragmented=True)
        t._assembly[1] = {"frags": [None], "received": 0, "total": 1, "ts": time.monotonic()}
        t.set_active_rooms({0, 1})
        assert len(t._assembly) == 0

    def test_get_packet_loss_stats_initial(self):
        t = _make_transport()
        lost, total = t.get_packet_loss_stats()
        assert lost == 0
        assert total == 0

    def test_packet_loss_counter_increments(self):
        t = _make_transport()
        t._packet_total_count = 10
        t._packet_loss_count = 2
        lost, total = t.get_packet_loss_stats()
        assert lost == 2
        assert total == 10

    def test_send_missing_room_key(self):
        t = _make_transport(keys={0: b"0" * 32})
        t.send(b"test", room_id=99)

    def test_set_active_rooms_tuple_conversion(self):
        t = _make_transport(rooms={0, 1})
        t.set_active_rooms({2, 3})
        assert isinstance(t._active_rooms, tuple)
        assert set(t._active_rooms) == {2, 3}

    def test_send_increments_seq_num(self):
        t = _make_transport()
        assert t._seq_num == 0
        key = b"0" * 32
        mock_disc = MagicMock()
        mock_disc.get_peers_for_room.return_value = [("alice", "192.168.1.10")]
        t.peer_discovery = mock_disc
        t.send(b"test", room_id=0)
        assert t._seq_num == 1
        t.send(b"test2", room_id=0)
        assert t._seq_num == 2


class TestTransportListenLoop:

    def _send_packet(self, port, packet, target="127.0.0.1"):
        sender = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_DGRAM)
        try:
            sender.sendto(packet, (target, port))
        finally:
            sender.close()

    def test_voice_receive_loopback_skips_local(self):
        key = b"0" * 32
        port = 50091
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_VOICE, False,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = {"127.0.0.1"}
        t.start()
        try:
            name_bytes = b"testuser"
            payload = struct.pack("B", len(name_bytes)) + name_bytes + b"voice data"
            aad = struct.pack("B", 0)
            encrypted = encrypt(payload, key, aad=aad)
            room_byte = struct.pack("B", 0)
            seq_bytes = struct.pack("!H", 0)
            packet = MSG_VOICE + room_byte + seq_bytes + encrypted
            self._send_packet(port, packet)
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 0

    def test_voice_receive_wrong_msg_type_ignored(self):
        key = b"0" * 32
        port = 50092
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_VOICE, False,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            packet = MSG_CHAT + b"\x00" + b"\x00\x00" + b"\x00" * 20
            self._send_packet(port, packet)
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 0

    def test_voice_receive_wrong_room_ignored(self):
        key = b"0" * 32
        port = 50093
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_VOICE, False,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            name_bytes = b"testuser"
            payload = struct.pack("B", len(name_bytes)) + name_bytes + b"data"
            aad = struct.pack("B", 5)
            encrypted = encrypt(payload, key, aad=aad)
            room_byte = struct.pack("B", 5)
            seq_bytes = struct.pack("!H", 0)
            packet = MSG_VOICE + room_byte + seq_bytes + encrypted
            self._send_packet(port, packet)
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 0

    def test_voice_receive_wrong_key_ignored(self):
        key = b"0" * 32
        wrong_key = b"9" * 32
        port = 50094
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_VOICE, False,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            name_bytes = b"testuser"
            payload = struct.pack("B", len(name_bytes)) + name_bytes + b"data"
            aad = struct.pack("B", 0)
            encrypted = encrypt(payload, wrong_key, aad=aad)
            room_byte = struct.pack("B", 0)
            seq_bytes = struct.pack("!H", 0)
            packet = MSG_VOICE + room_byte + seq_bytes + encrypted
            self._send_packet(port, packet)
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 0

    def test_voice_receive_too_short_ignored(self):
        key = b"0" * 32
        port = 50095
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_VOICE, False,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            self._send_packet(port, MSG_VOICE + b"\x00")
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 0

    def test_voice_receive_dedup(self):
        key = b"0" * 32
        port = 50096
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_VOICE, False,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        name_bytes = b"testuser"
        payload = struct.pack("B", len(name_bytes)) + name_bytes + b"data"
        aad = struct.pack("B", 0)
        encrypted = encrypt(payload, key, aad=aad)
        room_byte = struct.pack("B", 0)
        seq_bytes = struct.pack("!H", 0)
        packet = MSG_VOICE + room_byte + seq_bytes + encrypted
        t.start()
        try:
            self._send_packet(port, packet)
            time.sleep(0.5)
            assert len(received) == 1
            t._dedup.is_duplicate(received[0][1])
            self._send_packet(port, packet)
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 1

    def test_voice_receive_seq_tracking(self):
        key = b"0" * 32
        port = 50097
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_VOICE, False,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            name_bytes = b"testuser"
            room_byte = struct.pack("B", 0)
            aad = struct.pack("B", 0)

            payload0 = struct.pack("B", len(name_bytes)) + name_bytes + b"msg_seq_0"
            enc0 = encrypt(payload0, key, aad=aad)
            self._send_packet(port, MSG_VOICE + room_byte + struct.pack("!H", 0) + enc0)
            time.sleep(0.5)

            payload1 = struct.pack("B", len(name_bytes)) + name_bytes + b"msg_seq_1"
            enc1 = encrypt(payload1, key, aad=aad)
            self._send_packet(port, MSG_VOICE + room_byte + struct.pack("!H", 1) + enc1)
            time.sleep(0.5)

            payload5 = struct.pack("B", len(name_bytes)) + name_bytes + b"msg_seq_5"
            enc5 = encrypt(payload5, key, aad=aad)
            self._send_packet(port, MSG_VOICE + room_byte + struct.pack("!H", 5) + enc5)
            time.sleep(1.0)
        finally:
            t.stop()
        assert t._packet_total_count == 3
        assert t._packet_loss_count == 1

    def test_chat_fragment_receive(self):
        key = b"0" * 32
        port = 50098
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_CHAT, True,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            name_bytes = b"testuser"
            full_payload = struct.pack("B", len(name_bytes)) + name_bytes + b"hello chat"
            aad = struct.pack("B", 0)
            encrypted = encrypt(full_payload, key, aad=aad)
            room_byte = struct.pack("B", 0)
            msg_id = struct.pack("!H", 42)
            frag_idx = struct.pack("B", 0)
            total_frags = struct.pack("B", 1)
            packet = MSG_CHAT + room_byte + msg_id + frag_idx + total_frags + encrypted
            self._send_packet(port, packet)
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 1
        assert received[0][0] == "testuser"
        assert received[0][1] == b"hello chat"

    def test_chat_fragment_short_packet_ignored(self):
        key = b"0" * 32
        port = 50099
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_CHAT, True,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            self._send_packet(port, MSG_CHAT + b"\x00" + b"\x00\x00\x00\x00")
            time.sleep(0.5)
        finally:
            t.stop()
        assert len(received) == 0

    def test_chat_fragment_multiple_received(self):
        key = b"0" * 32
        port = 50100
        received = []
        t = _make_transport_with_mock(port, {0: key}, {0}, MSG_CHAT, True,
                                       lambda s, d, r: received.append((s, d, r)))
        t.local_ips = set()
        t.start()
        try:
            name_bytes = b"alice"
            full_payload = struct.pack("B", len(name_bytes)) + name_bytes + b"hello world"
            aad = struct.pack("B", 0)
            encrypted = encrypt(full_payload, key, aad=aad)
            half = len(encrypted) // 2
            chunk1 = encrypted[:half]
            chunk2 = encrypted[half:]
            room_byte = struct.pack("B", 0)
            msg_id = struct.pack("!H", 99)

            pkt1 = MSG_CHAT + room_byte + msg_id + struct.pack("B", 0) + struct.pack("B", 2) + chunk1
            pkt2 = MSG_CHAT + room_byte + msg_id + struct.pack("B", 1) + struct.pack("B", 2) + chunk2
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.sendto(pkt1, ("127.0.0.1", port))
                time.sleep(0.3)
                sock.sendto(pkt2, ("127.0.0.1", port))
            finally:
                sock.close()
            time.sleep(1.5)
        finally:
            t.stop()
        assert len(received) == 1
        assert received[0][1] == b"hello world"


class TestTransportAssemblyFragmented:

    def test_voice_packet_with_peer_discovery(self):
        key = b"0" * 32
        mock_disc = MagicMock()
        mock_disc.get_peers_for_room.return_value = [("alice", "192.168.1.10")]
        t1 = _make_transport(port=50101, fragmented=False, keys={0: key}, peer_disc=mock_disc)
        t1._send_sock = MagicMock()
        t1.send(b"voice data", room_id=0)
        t1._send_sock.sendto.assert_called_once()

    def test_chat_fragmented_with_peer_discovery(self):
        key = b"0" * 32
        mock_disc = MagicMock()
        mock_disc.get_peers_for_room.return_value = [("alice", "192.168.1.10")]
        t1 = _make_transport(port=50102, fragmented=True, keys={0: key}, peer_disc=mock_disc)
        t1._send_sock = MagicMock()
        t1.send(b"chat message", room_id=0)
        assert t1._send_sock.sendto.call_count >= 1


class TestTransportPeers:

    def test_send_uses_peer_discovery(self):
        key = b"0" * 32
        mock_disc = MagicMock()
        mock_disc.get_peers_for_room.return_value = [("alice", "192.168.1.10"), ("bob", "192.168.1.20")]
        t = _make_transport(port=50103, keys={0: key}, peer_disc=mock_disc)
        t.send(b"hello", room_id=0)
        mock_disc.get_peers_for_room.assert_called_with(0)

    def test_send_no_peers_does_not_crash(self):
        key = b"0" * 32
        mock_disc = MagicMock()
        mock_disc.get_peers_for_room.return_value = []
        t = _make_transport(port=50104, keys={0: key}, peer_disc=mock_disc)
        t.send(b"hello", room_id=0)

    def test_send_multiple_rooms(self):
        key = b"0" * 32
        mock_disc = MagicMock()
        mock_disc.get_peers_for_room.return_value = [("alice", "192.168.1.10")]
        t = _make_transport(port=50105, keys={0: key, 1: key}, peer_disc=mock_disc)
        t.send(b"room0", room_id=0)
        t.send(b"room1", room_id=1)
        calls = mock_disc.get_peers_for_room.call_args_list
        assert calls[0].args == (0,)
        assert calls[1].args == (1,)
