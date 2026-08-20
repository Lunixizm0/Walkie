import logging

import av
import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
FRAME_SAMPLES = 960
BITRATE = 24000


def make_encoder():
    codec = av.CodecContext.create("opus", "w")
    codec.sample_rate = SAMPLE_RATE
    codec.bit_rate = BITRATE
    codec.layout = av.AudioLayout("mono")
    codec.format = av.AudioFormat("fltp")
    codec.open()
    return {"codec": codec, "pts": 0}


def make_decoder():
    codec = av.CodecContext.create("opus", "r")
    codec.sample_rate = SAMPLE_RATE
    codec.layout = av.AudioLayout("mono")
    codec.open()
    return codec


def encode(encoder_ctx: dict, pcm_data: np.ndarray) -> bytes:
    try:
        samples = pcm_data.flatten().astype(np.int16)

        if len(samples) < FRAME_SAMPLES:
            padded = np.zeros(FRAME_SAMPLES, dtype=np.int16)
            padded[:len(samples)] = samples
            samples = padded
        else:
            samples = samples[:FRAME_SAMPLES]

        float_samples = (samples.astype(np.float32) / 32768.0).reshape(1, FRAME_SAMPLES)

        frame = av.AudioFrame.from_ndarray(float_samples, format="fltp", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.pts = encoder_ctx["pts"]
        encoder_ctx["pts"] += FRAME_SAMPLES

        packets = encoder_ctx["codec"].encode(frame)
        if not packets:
            packets = encoder_ctx["codec"].encode(None)

        if not packets:
            log.warning("Opus encode: no packet produced")
            return b""

        return bytes(packets[0])

    except Exception as e:
        log.error(f"Opus encode error: {e}", exc_info=True)
        return b""


def decode(decoder, opus_bytes: bytes) -> np.ndarray:
    if not opus_bytes:
        return np.zeros(FRAME_SAMPLES, dtype=np.int16)

    try:
        packet = av.Packet(opus_bytes)
        frames = decoder.decode(packet)

        if not frames:
            log.warning("Opus decode: no frame produced")
            return np.zeros(FRAME_SAMPLES, dtype=np.int16)

        arr = frames[0].to_ndarray()
        float_pcm = arr[0]

        pcm = (np.clip(float_pcm, -1.0, 1.0) * 32767).astype(np.int16)

        if len(pcm) < FRAME_SAMPLES:
            padded = np.zeros(FRAME_SAMPLES, dtype=np.int16)
            padded[:len(pcm)] = pcm
            return padded
        return pcm[:FRAME_SAMPLES]

    except Exception as e:
        log.error(f"Opus decode error: {e}", exc_info=True)
        return np.zeros(FRAME_SAMPLES, dtype=np.int16)
