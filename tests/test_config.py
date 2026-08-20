import sys
import os
import tempfile
import string

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from walkie.config import (
    _deep_merge, _validate, generate_config, load_config,
    _generate_password, _load_toml, get_config, get_rooms,
    get_room_names, get_room_passwords, get_network_config,
    get_audio_config, get_vad_config, get_general_room_config,
)


def test_deep_merge():
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    over = {"b": {"c": 99}, "e": 5}
    result = _deep_merge(base, over)
    assert result["a"] == 1
    assert result["b"]["c"] == 99
    assert result["b"]["d"] == 3
    assert result["e"] == 5


def test_validate_missing_rooms():
    cfg = {
        "network": {"discovery_port": 50000, "chat_port": 50001, "voice_port": 50002},
        "audio": {"sample_rate": 48000, "channels": 1},
        "rooms": [],
        "general_room": {"salt": "x", "encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="At least one room"):
        _validate(cfg)


def test_generate_config_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_config.toml")
        cfg = generate_config(path)
        assert os.path.exists(path)
        assert len(cfg["general_room"]["salt"]) == 64
        assert len(cfg["general_room"]["encryption_key"]) == 64
        assert cfg["rooms"][0]["name"] == "General"
        assert cfg["rooms"][1]["password"] != ""
        assert cfg["rooms"][2]["password"] != ""


def test_load_config_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "nonexistent.toml")
        with pytest.raises(ValueError, match="Run 'walkie gen'"):
            load_config(path)


def test_load_config_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.toml")
        generate_config(path)
        cfg = load_config(path)
        assert cfg["network"]["discovery_port"] == 50000
        assert cfg["audio"]["sample_rate"] == 48000
        assert len(cfg["rooms"]) == 3


def test_deep_merge_empty_overrides():
    base = {"a": 1, "b": 2}
    result = _deep_merge(base, {})
    assert result == base


def test_deep_merge_empty_base():
    over = {"a": 1, "b": {"c": 2}}
    result = _deep_merge({}, over)
    assert result == over


def test_deep_merge_non_dict_override_replaces():
    base = {"a": {"b": 1}}
    over = {"a": "string"}
    result = _deep_merge(base, over)
    assert result["a"] == "string"


def test_deep_merge_deeply_nested():
    base = {"a": {"b": {"c": {"d": 1}}}}
    over = {"a": {"b": {"c": {"d": 99, "e": 5}}}}
    result = _deep_merge(base, over)
    assert result["a"]["b"]["c"]["d"] == 99
    assert result["a"]["b"]["c"]["e"] == 5


def test_validate_missing_network_discovery_port():
    cfg = {
        "network": {"chat_port": 50001, "voice_port": 50002},
        "audio": {"sample_rate": 48000},
        "rooms": [{"id": 0, "name": "General"}],
        "general_room": {"salt": "x", "encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="discovery_port"):
        _validate(cfg)


def test_validate_missing_network_chat_port():
    cfg = {
        "network": {"discovery_port": 50000, "voice_port": 50002},
        "audio": {"sample_rate": 48000},
        "rooms": [{"id": 0, "name": "General"}],
        "general_room": {"salt": "x", "encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="chat_port"):
        _validate(cfg)


def test_validate_missing_network_voice_port():
    cfg = {
        "network": {"discovery_port": 50000, "chat_port": 50001},
        "audio": {"sample_rate": 48000},
        "rooms": [{"id": 0, "name": "General"}],
        "general_room": {"salt": "x", "encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="voice_port"):
        _validate(cfg)


def test_validate_missing_audio_sample_rate():
    cfg = {
        "network": {"discovery_port": 50000, "chat_port": 50001, "voice_port": 50002},
        "audio": {"channels": 1},
        "rooms": [{"id": 0, "name": "General"}],
        "general_room": {"salt": "x", "encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="sample_rate"):
        _validate(cfg)


def test_validate_missing_general_room_salt():
    cfg = {
        "network": {"discovery_port": 50000, "chat_port": 50001, "voice_port": 50002},
        "audio": {"sample_rate": 48000},
        "rooms": [{"id": 0, "name": "General"}],
        "general_room": {"encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="Config not found"):
        _validate(cfg)


def test_validate_missing_general_room_key():
    cfg = {
        "network": {"discovery_port": 50000, "chat_port": 50001, "voice_port": 50002},
        "audio": {"sample_rate": 48000},
        "rooms": [{"id": 0, "name": "General"}],
        "general_room": {"salt": "x"},
    }
    with pytest.raises(ValueError, match="Config not found"):
        _validate(cfg)


def test_validate_room_missing_id():
    cfg = {
        "network": {"discovery_port": 50000, "chat_port": 50001, "voice_port": 50002},
        "audio": {"sample_rate": 48000},
        "rooms": [{"name": "General"}],
        "general_room": {"salt": "x", "encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="id"):
        _validate(cfg)


def test_validate_room_missing_name():
    cfg = {
        "network": {"discovery_port": 50000, "chat_port": 50001, "voice_port": 50002},
        "audio": {"sample_rate": 48000},
        "rooms": [{"id": 0}],
        "general_room": {"salt": "x", "encryption_key": "y"},
    }
    with pytest.raises(ValueError, match="name"):
        _validate(cfg)


def test_generate_config_produces_valid_toml():
    import tomllib
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.toml")
        generate_config(path)
        with open(path, "rb") as f:
            parsed = tomllib.load(f)
        assert "network" in parsed
        assert "audio" in parsed
        assert "rooms" in parsed
        assert "general_room" in parsed
        assert isinstance(parsed["rooms"], list)
        assert len(parsed["rooms"]) == 3


def test_generate_config_default_path():
    import tomllib
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "walkie_config.toml")
        cfg = generate_config(path)
        with open(path, "rb") as f:
            parsed = tomllib.load(f)
        assert parsed["general_room"]["salt"] == cfg["general_room"]["salt"]
        assert parsed["general_room"]["encryption_key"] == cfg["general_room"]["encryption_key"]


def test_generate_config_creates_parent_dirs():
    import tomllib
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "sub", "dir", "config.toml")
        generate_config(path)
        assert os.path.exists(path)


def test_generate_config_different_each_time():
    with tempfile.TemporaryDirectory() as tmpdir:
        path1 = os.path.join(tmpdir, "c1.toml")
        path2 = os.path.join(tmpdir, "c2.toml")
        cfg1 = generate_config(path1)
        cfg2 = generate_config(path2)
        assert cfg1["general_room"]["salt"] != cfg2["general_room"]["salt"]
        assert cfg1["general_room"]["encryption_key"] != cfg2["general_room"]["encryption_key"]


def test_generate_password_length():
    for length in [1, 8, 16, 20, 64, 128]:
        pw = _generate_password(length)
        assert len(pw) == length


def test_generate_password_charset():
    pw = _generate_password(200)
    valid = set(string.ascii_letters + string.digits)
    assert all(c in valid for c in pw)


def test_generate_password_different_each_time():
    passwords = {_generate_password(16) for _ in range(20)}
    assert len(passwords) == 20


def test_load_toml_nonexistent():
    result = _load_toml("/nonexistent/path/config.toml")
    assert result == {}


def test_load_toml_invalid_toml():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "bad.toml")
        with open(path, "w") as f:
            f.write("this is not valid toml [[[")
        result = _load_toml(path)
        assert result == {}


def test_load_toml_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "good.toml")
        with open(path, "w") as f:
            f.write('[network]\ndiscovery_port = 50000\n')
        result = _load_toml(path)
        assert result["network"]["discovery_port"] == 50000


def test_load_config_merges_with_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "partial.toml")
        with open(path, "w") as f:
            f.write('[general_room]\nsalt = "abc"\nencryption_key = "def"\n\n[[rooms]]\nid = 0\nname = "General"\npassword = ""\n')
        cfg = load_config(path)
        assert cfg["network"]["discovery_port"] == 50000
        assert cfg["audio"]["sample_rate"] == 48000
        assert cfg["general_room"]["salt"] == "abc"


def test_get_config_returns_dict():
    cfg = get_config()
    assert isinstance(cfg, dict)
    assert "network" in cfg
    assert "rooms" in cfg


def test_get_config_caches():
    cfg1 = get_config()
    cfg2 = get_config()
    assert cfg1 is cfg2


def test_get_rooms():
    rooms = get_rooms()
    assert isinstance(rooms, list)
    assert len(rooms) >= 1
    assert all("id" in r and "name" in r for r in rooms)


def test_get_room_names():
    names = get_room_names()
    assert isinstance(names, dict)
    assert 0 in names
    assert names[0] == "General"


def test_get_room_passwords():
    passwords = get_room_passwords()
    assert isinstance(passwords, dict)


def test_get_network_config():
    net = get_network_config()
    assert "discovery_port" in net
    assert "chat_port" in net
    assert "voice_port" in net
    assert isinstance(net["discovery_port"], int)


def test_get_audio_config():
    audio = get_audio_config()
    assert "sample_rate" in audio
    assert "channels" in audio
    assert isinstance(audio["sample_rate"], int)


def test_get_vad_config():
    vad = get_vad_config()
    assert "rms_threshold" in vad
    assert isinstance(vad["rms_threshold"], (int, float))


def test_get_general_room_config():
    gr = get_general_room_config()
    assert "salt" in gr
    assert "encryption_key" in gr
