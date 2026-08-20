import logging

import av
import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE   = 48000
FRAME_SAMPLES = 960    # 20ms @ 48kHz
BITRATE       = 24000  # 24 kbps

# PTS counter - encoder requires monotonically increasing PTS per frame
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
    # Encode int16 PCM to Opus packet bytes Uses from_ndarray, flushes after each frame
    global _pts_counter
    try:
        samples = pcm_data.flatten().astype(np.int16)

        # Normalize size
        if len(samples) < FRAME_SAMPLES:
            padded = np.zeros(FRAME_SAMPLES, dtype=np.int16)
            padded[:len(samples)] = samples
            samples = padded
        else:
            samples = samples[:FRAME_SAMPLES]

        # int16 - float32 (fltp shape: [1, FRAME_SAMPLES])
        float_samples = (samples.astype(np.float32) / 32768.0).reshape(1, FRAME_SAMPLES)

        # AudioFrame.from_ndarray
        frame = av.AudioFrame.from_ndarray(float_samples, format="fltp", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.pts = _pts_counter
        _pts_counter += FRAME_SAMPLES

        # Encode + flush
        packets = _encoder.encode(frame)
        # Opus encoder may hold back packets flush to force output
        if not packets:
            packets = _encoder.encode(None)

        if not packets:
            log.warning("Opus encode: no packet produced")
            return b""

        return bytes(packets[0])

    except Exception as e:
        log.error(f"Opus encode error: {e}", exc_info=True)
        return b""


def decode(opus_bytes: bytes) -> np.ndarray:
    # Decode Opus packet bytes to int16 PCM numpy array
    if not opus_bytes:
        return np.zeros(FRAME_SAMPLES, dtype=np.int16)

    try:
        packet = av.Packet(opus_bytes)
        frames = _decoder.decode(packet)

        if not frames:
            log.warning("Opus decode: no frame produced")
            return np.zeros(FRAME_SAMPLES, dtype=np.int16)

        # to_ndarray returns numpy array directly (fltp - shape [1, N])
        arr = frames[0].to_ndarray()  # fltp: shape (1, samples)
        float_pcm = arr[0]            # shape (samples)

        # float32 - int16
        pcm = (np.clip(float_pcm, -1.0, 1.0) * 32767).astype(np.int16)

        # Normalize size
        if len(pcm) < FRAME_SAMPLES:
            padded = np.zeros(FRAME_SAMPLES, dtype=np.int16)
            padded[:len(pcm)] = pcm
            return padded
        return pcm[:FRAME_SAMPLES]

    except Exception as e:
        log.error(f"Opus decode error: {e}", exc_info=True)
        return np.zeros(FRAME_SAMPLES, dtype=np.int16)
