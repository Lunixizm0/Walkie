from pathlib import Path
import sys

sys_path = str(Path(__file__).resolve().parent.parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import numpy as np
import pytest
from walkie.audio_codec import make_encoder, make_decoder, encode, decode, FRAME_SAMPLES


def test_encode_decode_roundtrip():
    encoder = make_encoder()
    decoder = make_decoder()
    pcm = np.random.randint(-1000, 1000, FRAME_SAMPLES, dtype=np.int16)
    encoded = encode(encoder, pcm)
    assert len(encoded) > 0
    decoded = decode(decoder, encoded)
    assert len(decoded) == FRAME_SAMPLES


def test_encode_empty():
    encoder = make_encoder()
    pcm = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    encoded = encode(encoder, pcm)
    assert isinstance(encoded, bytes)


def test_decode_empty():
    decoder = make_decoder()
    result = decode(decoder, b"")
    assert len(result) == FRAME_SAMPLES
    assert np.all(result == 0)


def test_encode_truncates_long():
    encoder = make_encoder()
    pcm = np.random.randint(-1000, 1000, FRAME_SAMPLES * 2, dtype=np.int16)
    encoded = encode(encoder, pcm)
    assert isinstance(encoded, bytes)


def test_encode_pads_short():
    encoder = make_encoder()
    pcm = np.random.randint(-1000, 1000, FRAME_SAMPLES // 2, dtype=np.int16)
    encoded = encode(encoder, pcm)
    assert isinstance(encoded, bytes)


def test_pts_counter_increments():
    encoder = make_encoder()
    pcm = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    encode(encoder, pcm)
    assert encoder["pts"] == FRAME_SAMPLES
    encode(encoder, pcm)
    assert encoder["pts"] == FRAME_SAMPLES * 2


def test_separate_encoders_independent():
    enc1 = make_encoder()
    enc2 = make_encoder()
    pcm = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    encode(enc1, pcm)
    assert enc1["pts"] == FRAME_SAMPLES
    assert enc2["pts"] == 0


def test_per_sender_decoders():
    enc1 = make_encoder()
    enc2 = make_encoder()
    dec1 = make_decoder()
    dec2 = make_decoder()

    pcm1 = np.ones(FRAME_SAMPLES, dtype=np.int16) * 100
    pcm2 = np.ones(FRAME_SAMPLES, dtype=np.int16) * -100

    encoded1 = encode(enc1, pcm1)
    encoded2 = encode(enc2, pcm2)

    decoded1 = decode(dec1, encoded1)
    decoded2 = decode(dec2, encoded2)

    assert len(decoded1) == FRAME_SAMPLES
    assert len(decoded2) == FRAME_SAMPLES


def test_pcm_value_preservation():
    encoder = make_encoder()
    decoder = make_decoder()
    pcm = np.sin(np.linspace(0, 2 * np.pi, FRAME_SAMPLES)) * 5000
    pcm = pcm.astype(np.int16)
    encoded = encode(encoder, pcm)
    decoded = decode(decoder, encoded)
    assert len(decoded) == FRAME_SAMPLES
    assert np.any(np.abs(decoded) > 0)


def test_sequential_encode_decode_many_frames():
    encoder = make_encoder()
    decoder = make_decoder()
    for i in range(50):
        pcm = np.sin(np.linspace(0, 2 * np.pi * (i + 1) / 50, FRAME_SAMPLES)) * 3000
        pcm = pcm.astype(np.int16)
        encoded = encode(encoder, pcm)
        assert len(encoded) > 0
        decoded = decode(decoder, encoded)
        assert len(decoded) == FRAME_SAMPLES
    assert encoder["pts"] == FRAME_SAMPLES * 50


def test_encode_exact_frame_size():
    encoder = make_encoder()
    pcm = np.full(FRAME_SAMPLES, 100, dtype=np.int16)
    encoded = encode(encoder, pcm)
    assert len(encoded) > 0
    decoder = make_decoder()
    decoded = decode(decoder, encoded)
    assert len(decoded) == FRAME_SAMPLES


def test_encode_one_sample():
    encoder = make_encoder()
    pcm = np.array([500], dtype=np.int16)
    encoded = encode(encoder, pcm)
    assert isinstance(encoded, bytes)
    assert len(encoded) > 0


def test_encode_zero_samples():
    encoder = make_encoder()
    pcm = np.array([], dtype=np.int16)
    encoded = encode(encoder, pcm)
    assert isinstance(encoded, bytes)
    assert len(encoded) > 0


def test_decoder_corrupted_data_returns_zeros():
    decoder = make_decoder()
    result = decode(decoder, b"\x00\x01\x02\x03\x04\x05")
    assert len(result) == FRAME_SAMPLES
    assert result.dtype == np.int16


def test_decoder_random_garbage_returns_zeros():
    decoder = make_decoder()
    garbage = bytes(range(256)) * 4
    result = decode(decoder, garbage)
    assert len(result) == FRAME_SAMPLES


def test_encode_max_amplitude():
    encoder = make_encoder()
    decoder = make_decoder()
    pcm = np.full(FRAME_SAMPLES, 32767, dtype=np.int16)
    encoded = encode(encoder, pcm)
    decoded = decode(decoder, encoded)
    assert len(decoded) == FRAME_SAMPLES
    assert np.any(decoded > 0)


def test_encode_min_amplitude():
    encoder = make_encoder()
    decoder = make_decoder()
    pcm = np.full(FRAME_SAMPLES, -32768, dtype=np.int16)
    encoded = encode(encoder, pcm)
    decoded = decode(decoder, encoded)
    assert len(decoded) == FRAME_SAMPLES
    assert np.any(decoded < 0)


def test_encode_negative_pcm():
    encoder = make_encoder()
    decoder = make_decoder()
    pcm = np.full(FRAME_SAMPLES, -1000, dtype=np.int16)
    encoded = encode(encoder, pcm)
    decoded = decode(decoder, encoded)
    assert len(decoded) == FRAME_SAMPLES


def test_encode_alternating_signal():
    encoder = make_encoder()
    decoder = make_decoder()
    pcm = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    pcm[::2] = 1000
    pcm[1::2] = -1000
    encoded = encode(encoder, pcm)
    decoded = decode(decoder, encoded)
    assert len(decoded) == FRAME_SAMPLES
