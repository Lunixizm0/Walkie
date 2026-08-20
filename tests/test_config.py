import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from walkie.config import _deep_merge, _validate, generate_config, load_config


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
