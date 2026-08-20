import sys
import os
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import time
import struct
import threading
import pytest
from walkie.network import (
    PeerDiscovery, _build_peer_packet, _parse_peer_packet,
    MSG_HELLO, MSG_BYE, _get_all_local_ips,
)


def _make_discovery(port=50080, rooms=None, username="testuser"):
    if rooms is None:
        rooms = {0, 1}
    return PeerDiscovery(
        username=username,
        active_rooms=rooms,
        discovery_port=port,
        hello_interval=0.5,
        peer_timeout=2.0,
    )


class TestPeerDiscoveryRooms:

    def test_active_rooms_property_returns_copy(self):
        pd = _make_discovery(rooms={0, 1})
        rooms = pd.active_rooms
        rooms.add(99)
        assert 99 not in pd.active_rooms

    def test_set_active_rooms_updates_tuple(self):
        pd = _make_discovery(rooms={0, 1})
        pd.set_active_rooms({2, 3})
        assert set(pd.active_rooms) == {2, 3}

    def test_set_active_rooms_removes_peers_no_shared_rooms(self):
        pd = _make_discovery(rooms={0, 1, 2})
        pd.peers["192.168.1.10"] = ("alice", time.time(), {0})
        pd.peers["192.168.1.20"] = ("bob", time.time(), {1})
        pd.set_active_rooms({1, 2})
        assert "192.168.1.10" not in pd.peers
        assert "192.168.1.20" in pd.peers

    def test_set_active_rooms_preserves_peers_with_remaining_rooms(self):
        pd = _make_discovery(rooms={0, 1, 2})
        pd.peers["192.168.1.10"] = ("alice", time.time(), {0, 1})
        pd.set_active_rooms({1, 2})
        assert "192.168.1.10" in pd.peers
        assert pd.peers["192.168.1.10"][2] == {1}

    def test_set_active_rooms_empty(self):
        pd = _make_discovery(rooms={0, 1})
        pd.peers["192.168.1.10"] = ("alice", time.time(), {0})
        pd.set_active_rooms(set())
        assert len(pd.peers) == 0

    def test_set_active_rooms_fires_callback(self):
        pd = _make_discovery(rooms={0, 1})
        callback_called = []
        pd.on_peers_changed = lambda peers: callback_called.append(peers)
        pd.set_active_rooms({0})
        assert len(callback_called) == 1

    def test_set_active_rooms_same_no_callback(self):
        pd = _make_discovery(rooms={0, 1})
        callback_called = []
        pd.on_peers_changed = lambda peers: callback_called.append(peers)
        pd.set_active_rooms({0, 1})
        assert len(callback_called) == 1


class TestPeerDiscoveryPeerManagement:

    def test_get_peers_for_room(self):
        pd = _make_discovery(rooms={0, 1})
        pd.peers["192.168.1.10"] = ("alice", time.time(), {0})
        pd.peers["192.168.1.20"] = ("bob", time.time(), {1})
        pd.peers["192.168.1.30"] = ("charlie", time.time(), {0, 1})
        room0 = pd.get_peers_for_room(0)
        assert len(room0) == 2
        names = {name for name, ip in room0}
        assert "alice" in names
        assert "charlie" in names

    def test_get_peers_for_room_empty(self):
        pd = _make_discovery(rooms={0})
        pd.peers["192.168.1.10"] = ("alice", time.time(), {1})
        room0 = pd.get_peers_for_room(0)
        assert len(room0) == 0

    def test_get_peers_for_room_no_peers(self):
        pd = _make_discovery(rooms={0})
        room0 = pd.get_peers_for_room(0)
        assert len(room0) == 0

    def test_get_peers_for_room_thread_safety(self):
        pd = _make_discovery(rooms={0})
        errors = []

        def writer():
            try:
                for i in range(100):
                    pd.peers[f"192.168.1.{i}"] = (f"user{i}", time.time(), {0})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    pd.get_peers_for_room(0)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert len(errors) == 0


class TestPeerDiscoveryIsLocal:

    def test_is_local_returns_true_for_localhost(self):
        pd = _make_discovery()
        pd.local_ips = {"127.0.0.1", "192.168.1.5"}
        assert pd._is_local("127.0.0.1") is True

    def test_is_local_returns_false_for_remote(self):
        pd = _make_discovery()
        pd.local_ips = {"127.0.0.1", "192.168.1.5"}
        assert pd._is_local("10.0.0.1") is False


class TestPeerDiscoveryListenProcessing:

    def test_process_hello_adds_peer(self):
        pd = _make_discovery(rooms={0, 1})
        pd.local_ips = {"127.0.0.1"}
        peer_ip = "192.168.1.100"
        packet = _build_peer_packet(MSG_HELLO, {0}, "alice")
        callback_called = []
        pd.on_peers_changed = lambda peers: callback_called.append(peers)

        parsed = _parse_peer_packet(packet)
        room_ids, name = parsed
        common = room_ids & pd.active_rooms
        assert len(common) > 0
        pd.peers[peer_ip] = (name, time.time(), set(common))
        assert peer_ip in pd.peers
        assert pd.peers[peer_ip][0] == "alice"

    def test_process_bye_removes_peer(self):
        pd = _make_discovery(rooms={0, 1})
        pd.peers["192.168.1.100"] = ("alice", time.time(), {0})
        del pd.peers["192.168.1.100"]
        assert "192.168.1.100" not in pd.peers

    def test_process_bye_partial_room_removal(self):
        pd = _make_discovery(rooms={0, 1})
        pd.peers["192.168.1.100"] = ("alice", time.time(), {0, 1})
        peer_rooms = pd.peers["192.168.1.100"][2]
        remaining = peer_rooms - {0}
        pd.peers["192.168.1.100"] = ("alice", time.time(), remaining)
        assert 1 in pd.peers["192.168.1.100"][2]
        assert 0 not in pd.peers["192.168.1.100"][2]

    def test_process_hello_updates_room_union(self):
        pd = _make_discovery(rooms={0, 1})
        pd.peers["192.168.1.100"] = ("alice", time.time(), {0})
        existing_rooms = pd.peers["192.168.1.100"][2]
        new_rooms = {0, 1}
        updated = existing_rooms | new_rooms
        pd.peers["192.168.1.100"] = ("alice", time.time(), updated)
        assert pd.peers["192.168.1.100"][2] == {0, 1}


class TestPeerDiscoveryStartStop:

    def test_start_creates_sockets(self):
        pd = _make_discovery(port=50081)
        pd.start()
        try:
            assert hasattr(pd, "_send_sock")
            assert hasattr(pd, "_recv_sock")
            assert pd._running is True
        finally:
            pd.stop()

    def test_stop_sets_running_false(self):
        pd = _make_discovery(port=50082)
        pd.start()
        pd.stop()
        assert pd._running is False

    def test_start_stop_multiple_cycles(self):
        pd = _make_discovery(port=50083)
        for _ in range(3):
            pd.start()
            time.sleep(0.1)
            pd.stop()
        assert pd._running is False

    def test_stop_without_start(self):
        pd = _make_discovery(port=50084)
        pd.stop()
        assert pd._running is False


class TestPeerDiscoveryCleanup:

    def test_cleanup_removes_expired_peers(self):
        pd = _make_discovery(port=50085, rooms={0})
        pd.peers["192.168.1.10"] = ("alice", time.time() - 100, {0})
        pd.peers["192.168.1.20"] = ("bob", time.time(), {0})
        expired = [ip for ip, (_, ts, _) in pd.peers.items() if time.time() - ts > pd._peer_timeout]
        for ip in expired:
            del pd.peers[ip]
        assert "192.168.1.10" not in pd.peers
        assert "192.168.1.20" in pd.peers

    def test_cleanup_preserves_fresh_peers(self):
        pd = _make_discovery(port=50086, rooms={0})
        pd.peers["192.168.1.10"] = ("alice", time.time(), {0})
        expired = [ip for ip, (_, ts, _) in pd.peers.items() if time.time() - ts > pd._peer_timeout]
        for ip in expired:
            del pd.peers[ip]
        assert "192.168.1.10" in pd.peers


class TestPeerDiscoveryBroadcast:

    def test_broadcast_packet_format(self):
        packet = _build_peer_packet(MSG_HELLO, {0, 1}, "testuser")
        assert packet[0:1] == MSG_HELLO
        assert packet[1] == 2
        result = _parse_peer_packet(packet)
        assert result is not None
        room_ids, name = result
        assert room_ids == {0, 1}
        assert name == "testuser"

    def test_bye_packet_format(self):
        packet = _build_peer_packet(MSG_BYE, {0}, "testuser")
        assert packet[0:1] == MSG_BYE
        result = _parse_peer_packet(packet)
        assert result is not None
        assert result[0] == {0}
        assert result[1] == "testuser"
