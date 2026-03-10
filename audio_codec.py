"""
Opus ses codec'i — PyAV 16 kullanır.
AudioFrame.from_ndarray() ile temiz encode, flush ile delayed packet sorunu çözülmüş.
"""

import av
import numpy as np
import logging

log = logging.getLogger(__name__)

SAMPLE_RATE   = 48000
FRAME_SAMPLES = 960    # 20ms @ 48kHz
BITRATE       = 24000  # 24 kbps

# PTS sayacı — encoder her frame için artan PTS ister
_pts_counter = 0


def _make_encoder():
    codec = av.CodecContext.create("opus", "w")
    codec.sample_rate = SAMPLE_RATE
    codec.bit_rate    = BITRATE
    codec.layout      = av.AudioLayout("mono")
    codec.format      = av.AudioFormat("fltp")
    codec.open()
    return codec


def _make_decoder():
    codec = av.CodecContext.create("opus", "r")
    codec.sample_rate = SAMPLE_RATE
    codec.layout      = av.AudioLayout("mono")
    codec.open()
    return codec


_encoder = _make_encoder()
_decoder = _make_decoder()


def encode(pcm_data: np.ndarray) -> bytes:
    """
    int16 PCM -> Opus paket baytları.
    from_ndarray kullanır, her frame sonrası flush yapar.
    """
    global _pts_counter
    try:
        samples = pcm_data.flatten().astype(np.int16)

        # Boyutu normalize et
        if len(samples) < FRAME_SAMPLES:
            padded = np.zeros(FRAME_SAMPLES, dtype=np.int16)
            padded[:len(samples)] = samples
            samples = padded
        else:
            samples = samples[:FRAME_SAMPLES]

        # int16 -> float32 (fltp için shape: [1, FRAME_SAMPLES])
        float_samples = (samples.astype(np.float32) / 32768.0).reshape(1, FRAME_SAMPLES)

        # AudioFrame.from_ndarray — en güvenilir yöntem
        frame = av.AudioFrame.from_ndarray(float_samples, format="fltp", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.pts = _pts_counter
        _pts_counter += FRAME_SAMPLES

        # Encode + flush
        packets = _encoder.encode(frame)
        # Opus encoder delayed olabilir, flush ile zorla al
        if not packets:
            packets = _encoder.encode(None)

        if not packets:
            log.warning("Opus encode: paket üretilemedi")
            return b""

        return bytes(packets[0])

    except Exception as e:
        log.error(f"Opus encode hatası: {e}", exc_info=True)
        return b""


def decode(opus_bytes: bytes) -> np.ndarray:
    """
    Opus paket baytları -> int16 PCM numpy dizisi.
    """
    if not opus_bytes:
        return np.zeros(FRAME_SAMPLES, dtype=np.int16)

    try:
        packet = av.Packet(opus_bytes)
        frames = _decoder.decode(packet)

        if not frames:
            log.warning("Opus decode: frame üretilemedi")
            return np.zeros(FRAME_SAMPLES, dtype=np.int16)

        # to_ndarray ile direkt numpy array al (fltp -> shape [1, N])
        arr = frames[0].to_ndarray()  # fltp: shape (1, samples)
        float_pcm = arr[0]            # shape (samples,)

        # float32 -> int16
        pcm = (np.clip(float_pcm, -1.0, 1.0) * 32767).astype(np.int16)

        # Boyutu normalize et
        if len(pcm) < FRAME_SAMPLES:
            padded = np.zeros(FRAME_SAMPLES, dtype=np.int16)
            padded[:len(pcm)] = pcm
            return padded
        return pcm[:FRAME_SAMPLES]

    except Exception as e:
        log.error(f"Opus decode hatası: {e}", exc_info=True)
        return np.zeros(FRAME_SAMPLES, dtype=np.int16)