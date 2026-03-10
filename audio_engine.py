"""
Audio engine for the Walkie-Talkie application.
Uses sounddevice for microphone capture and speaker playback.
"""

import threading
import logging
import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

# Audio parameters
SAMPLE_RATE = 16000   # 16 kHz
CHANNELS = 1          # Mono
DTYPE = "int16"       # 16-bit PCM
BLOCK_SIZE = 1024     # frames per buffer (~64ms at 16kHz)


class AudioEngine:
    """Handles microphone capture and audio playback."""

    def __init__(self, on_audio_captured=None):
        """
        Args:
            on_audio_captured: callback(audio_bytes) called with each captured frame
        """
        self.on_audio_captured = on_audio_captured
        self._capturing = False
        self._capture_stream = None
        self._playback_stream = None
        self._lock = threading.Lock()

        log.info(f"AudioEngine initializing (rate={SAMPLE_RATE}, channels={CHANNELS}, dtype={DTYPE}, block={BLOCK_SIZE})")

        # List available devices for debugging
        try:
            devices = sd.query_devices()
            log.debug(f"Available audio devices:\n{devices}")
            default_input = sd.query_devices(kind='input')
            default_output = sd.query_devices(kind='output')
            log.info(f"Default input device: {default_input['name']}")
            log.info(f"Default output device: {default_output['name']}")
        except Exception as e:
            log.warning(f"Could not query audio devices: {e}")

        # Start a persistent output stream for playback
        try:
            self._playback_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
            )
            self._playback_stream.start()
            log.info("Playback stream opened and started")
        except Exception as e:
            log.error(f"Could not open playback device: {e}", exc_info=True)
            self._playback_stream = None

    def start_capture(self):
        """Start capturing audio from the microphone."""
        if self._capturing:
            log.debug("start_capture called but already capturing, ignoring")
            return
        self._capturing = True
        try:
            self._capture_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
                callback=self._capture_callback,
            )
            self._capture_stream.start()
            log.info("Microphone capture started (PTT active)")
        except Exception as e:
            log.error(f"Could not open capture device: {e}", exc_info=True)
            self._capturing = False

    def stop_capture(self):
        """Stop capturing audio from the microphone."""
        if not self._capturing:
            log.debug("stop_capture called but not capturing, ignoring")
            return
        self._capturing = False
        try:
            if self._capture_stream:
                self._capture_stream.stop()
                self._capture_stream.close()
                self._capture_stream = None
                log.info("Microphone capture stopped (PTT released)")
        except Exception as e:
            log.error(f"Error stopping capture stream: {e}", exc_info=True)

    def play_audio(self, audio_bytes: bytes):
        """Play received audio data through the speakers."""
        if self._playback_stream is None:
            log.warning("play_audio called but no playback stream available")
            return
        try:
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_array = audio_array.reshape(-1, CHANNELS)
            self._playback_stream.write(audio_array)
        except Exception as e:
            log.error(f"Error playing audio ({len(audio_bytes)} bytes): {e}", exc_info=True)

    def shutdown(self):
        """Clean up all audio resources."""
        log.info("AudioEngine shutting down...")
        self.stop_capture()
        try:
            if self._playback_stream:
                self._playback_stream.stop()
                self._playback_stream.close()
                self._playback_stream = None
                log.info("Playback stream closed")
        except Exception as e:
            log.error(f"Error closing playback stream: {e}", exc_info=True)
        log.info("AudioEngine shutdown complete")

    def _capture_callback(self, indata, frames, time_info, status):
        """Called by sounddevice when audio data is available."""
        try:
            if status:
                log.warning(f"Audio capture status: {status}")
            if self._capturing and self.on_audio_captured:
                audio_bytes = indata.tobytes()
                self.on_audio_captured(audio_bytes)
        except Exception as e:
            log.error(f"Error in capture callback: {e}", exc_info=True)
