import collections
import logging
import threading
import time

import numpy as np
import sounddevice as sd

from . import audio_codec
from .config import get_audio_config, get_vad_config

log = logging.getLogger(__name__)

_audio_cfg = get_audio_config()
_vad_cfg = get_vad_config()

SAMPLE_RATE = _audio_cfg["sample_rate"]
CHANNELS = _audio_cfg["channels"]
DTYPE = "int16"

FRAME_DURATION_MS = _audio_cfg["frame_duration_ms"]
BLOCK_SIZE = audio_codec.FRAME_SAMPLES

JITTER_BUFFER_MIN = 4
JITTER_BUFFER_MAX = 25

VAD_RMS_THRESHOLD = _vad_cfg["rms_threshold"]

DECODER_MAX_AGE = 60.0
DECODER_MAX_COUNT = 20


class JitterBuffer:
    # Buffers incoming audio packets for seamless playback

    def __init__(self, min_depth: int = JITTER_BUFFER_MIN, max_depth: int = JITTER_BUFFER_MAX):
        self._buffer: collections.deque = collections.deque(maxlen=max_depth)
        self._min_depth = min_depth
        self._started   = False
        self._lock      = threading.Lock()
        log.info(f"JitterBuffer created (min={min_depth}, max={max_depth})")

    def push(self, audio_array: np.ndarray):
        with self._lock:
            self._buffer.append(audio_array)

    def pop(self) -> np.ndarray | None:
        with self._lock:
            if not self._started:
                if len(self._buffer) >= self._min_depth:
                    self._started = True
                    log.debug(f"JitterBuffer started playing ({len(self._buffer)} packets buffered)")
                else:
                    return None

            if self._buffer:
                return self._buffer.popleft()
            else:
                self._started = False
                log.debug("JitterBuffer drained, waiting for buffer to refill")
                return None

    def clear(self):
        with self._lock:
            self._buffer.clear()
            self._started = False


class AudioEngine:
    #Manages microphone capture and audio playback

    def __init__(self, on_audio_captured=None):
        self.on_audio_captured = on_audio_captured
        self._capturing        = False
        self._capture_stream   = None
        self._playback_stream  = None
        self._lock             = threading.Lock()
        self.enabled_rooms: set[int] = set()
        self.vad_enabled       = False

        self._encoder = audio_codec.make_encoder()
        self._decoders: dict[str, object] = {}
        self._decoder_ts: dict[str, float] = {}
        self._last_cleanup = time.monotonic()

        self._jitter_buffer = JitterBuffer()

        log.info(f"AudioEngine starting - Opus @ {SAMPLE_RATE}Hz, {BLOCK_SIZE} samples/frame ({FRAME_DURATION_MS}ms)")

        try:
            self._playback_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
                callback=self._playback_callback,
            )
            self._playback_stream.start()
            log.info("Playback stream opened (jitter buffer + Opus)")
        except Exception as e:
            log.error(f"Failed to open playback device: {e}", exc_info=True)
            self._playback_stream = None

    def start_capture(self, enabled_rooms: set[int]):
        if self._capturing:
            return
        self._capturing     = True
        self.enabled_rooms  = set(enabled_rooms)
        try:
            self._capture_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
                callback=self._capture_callback,
            )
            self._capture_stream.start()
            log.info("Microphone capture started (Push-to-Talk active)")
        except Exception as e:
            log.error(f"Failed to open capture device: {e}", exc_info=True)
            self._capturing = False

    def stop_capture(self):
        if not self._capturing:
            return
        self._capturing = False
        try:
            if self._capture_stream:
                self._capture_stream.stop()
                self._capture_stream.close()
                self._capture_stream = None
                log.info("Microphone capture stopped")
        except Exception as e:
            log.error(f"Error stopping capture stream: {e}", exc_info=True)

    def set_vad_enabled(self, enabled: bool, enabled_rooms: set[int] = None):
        self.vad_enabled = enabled
        if enabled:
            self.start_capture(enabled_rooms or set())
        else:
            self.stop_capture()

    def play_beep(self, frequency: float, duration_ms: int):
        # Generate a notification tone and push it into the jitter buffer
        if self._playback_stream is None:
            return
        try:
            n_samples = int(SAMPLE_RATE * duration_ms / 1000.0)
            t         = np.linspace(0, duration_ms / 1000.0, n_samples, endpoint=False)
            waveform  = 0.05 * np.sin(2 * np.pi * frequency * t)
            audio_data = (waveform * 32767).astype(np.int16)

            for i in range(0, len(audio_data), BLOCK_SIZE):
                chunk = audio_data[i:i + BLOCK_SIZE]
                if len(chunk) < BLOCK_SIZE:
                    padded = np.zeros(BLOCK_SIZE, dtype=np.int16)
                    padded[:len(chunk)] = chunk
                    chunk = padded
                self._jitter_buffer.push(chunk.reshape(-1, CHANNELS))
        except Exception as e:
            log.error(f"Failed to generate beep: {e}", exc_info=True)

    def play_audio(self, encoded_bytes: bytes, sender: str):
        #Decode an Opus packet using a per-sender decoder and add to jitter buffer
        if self._playback_stream is None or not encoded_bytes:
            return
        try:
            if sender not in self._decoders:
                self._decoders[sender] = audio_codec.make_decoder()
                log.debug(f"Created new decoder for sender '{sender}'")
            self._decoder_ts[sender] = time.monotonic()

            pcm_array = audio_codec.decode(self._decoders[sender], encoded_bytes)
            if len(pcm_array) == 0:
                return
            self._jitter_buffer.push(pcm_array.reshape(-1, CHANNELS))
            self._maybe_cleanup_decoders()
        except Exception as e:
            log.error(f"Audio decode/buffer error: {e}", exc_info=True)

    def _maybe_cleanup_decoders(self):
        now = time.monotonic()
        if now - self._last_cleanup < 10.0:
            return
        self._last_cleanup = now
        stale = [s for s, t in self._decoder_ts.items() if now - t > DECODER_MAX_AGE]
        for s in stale:
            del self._decoders[s]
            del self._decoder_ts[s]
            log.debug(f"Cleaned up stale decoder for '{s}'")
        if len(self._decoders) > DECODER_MAX_COUNT:
            oldest = sorted(self._decoder_ts, key=self._decoder_ts.get)[:len(self._decoders) - DECODER_MAX_COUNT]
            for s in oldest:
                del self._decoders[s]
                del self._decoder_ts[s]
                log.debug(f"Evicted excess decoder for '{s}'")

    def shutdown(self):
        log.info("AudioEngine shutting down...")
        self.stop_capture()
        try:
            if self._playback_stream:
                self._playback_stream.stop()
                self._playback_stream.close()
                self._playback_stream = None
        except Exception as e:
            log.error(f"Error closing playback stream: {e}", exc_info=True)
        self._jitter_buffer.clear()
        self._decoders.clear()
        self._decoder_ts.clear()
        log.info("AudioEngine shutdown complete")

    #  internal callbacks

    def _capture_callback(self, indata, frames, time_info, status):
        try:
            if status:
                log.warning(f"Capture status: {status}")
            if not self._capturing or not self.on_audio_captured:
                return

            pcm_array = indata[:, 0].copy().astype(np.int16)

            if self.vad_enabled:
                rms = np.sqrt(np.mean(np.square(pcm_array.astype(np.float32))))
                if rms < VAD_RMS_THRESHOLD:
                    return

            encoded = audio_codec.encode(self._encoder, pcm_array)
            if encoded:
                for rid in self.enabled_rooms:
                    self.on_audio_captured(encoded, rid)
        except Exception as e:
            log.error(f"Capture callback error: {e}", exc_info=True)

    def _playback_callback(self, outdata, frames, time_info, status):
        try:
            if status:
                log.debug(f"Playback status: {status}")
            data = self._jitter_buffer.pop()
            if data is not None:
                outdata[:] = data
            else:
                outdata[:] = 0
        except Exception as e:
            outdata[:] = 0
            log.error(f"Playback callback error: {e}", exc_info=True)
