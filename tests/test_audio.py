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
