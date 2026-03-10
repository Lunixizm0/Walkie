"""
Walkie-Talkie uygulaması için ses motoru.
Mikrofon yakalama ve hoparlör çalma için sounddevice kullanır.
Opus codec (PyAV) ve jitter buffer içerir.
"""

import collections
import threading
import logging
import numpy as np
import sounddevice as sd
import audio_codec

log = logging.getLogger(__name__)

# Ses parametreleri
SAMPLE_RATE = 48000
CHANNELS    = 1
DTYPE       = "int16"

# Opus frame: 20ms @ 48kHz = 960 örnek
FRAME_DURATION_MS = 20
BLOCK_SIZE = audio_codec.FRAME_SAMPLES   # 960

# Jitter buffer ayarları
JITTER_BUFFER_MIN = 4   # 80ms başlangıç gecikmesi (4 × 20ms)
JITTER_BUFFER_MAX = 25  # maks 500ms tampon

# VAD eşiği
VAD_RMS_THRESHOLD = 50


class JitterBuffer:
    """
    Gelen ses paketlerini tamponlayarak kesintisiz çalma sağlar.
    """

    def __init__(self, min_depth: int = JITTER_BUFFER_MIN, max_depth: int = JITTER_BUFFER_MAX):
        self._buffer: collections.deque = collections.deque(maxlen=max_depth)
        self._min_depth = min_depth
        self._started   = False
        self._lock      = threading.Lock()
        log.info(f"JitterBuffer oluşturuldu (min={min_depth}, maks={max_depth})")

    def push(self, audio_array: np.ndarray):
        with self._lock:
            self._buffer.append(audio_array)

    def pop(self) -> np.ndarray | None:
        with self._lock:
            if not self._started:
                if len(self._buffer) >= self._min_depth:
                    self._started = True
                    log.debug(f"JitterBuffer çalmaya başladı ({len(self._buffer)} paket birikti)")
                else:
                    return None

            if self._buffer:
                return self._buffer.popleft()
            else:
                self._started = False
                log.debug("JitterBuffer tükendi, yeniden birikme bekleniyor")
                return None

    def clear(self):
        with self._lock:
            self._buffer.clear()
            self._started = False


class AudioEngine:
    """
    Mikrofon yakalama ve ses çalmayı yönetir.
    Opus codec (PyAV) ve jitter buffer içerir.
    """

    def __init__(self, on_audio_captured=None):
        self.on_audio_captured = on_audio_captured
        self._capturing        = False
        self._capture_stream   = None
        self._playback_stream  = None
        self._lock             = threading.Lock()
        self.active_room_id    = 0
        self.vad_enabled       = False

        self._jitter_buffer = JitterBuffer()

        log.info(f"SesMotoru başlatılıyor — Opus @ {SAMPLE_RATE}Hz, {BLOCK_SIZE} örnek/frame ({FRAME_DURATION_MS}ms)")

        try:
            self._playback_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
                callback=self._playback_callback,
            )
            self._playback_stream.start()
            log.info("Çalma akışı açıldı (jitter buffer + Opus)")
        except Exception as e:
            log.error(f"Çalma cihazı açılamadı: {e}", exc_info=True)
            self._playback_stream = None

    def start_capture(self, room_id: int):
        if self._capturing:
            return
        self._capturing     = True
        self.active_room_id = room_id
        try:
            self._capture_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
                callback=self._capture_callback,
            )
            self._capture_stream.start()
            log.info("Mikrofon yakalama başladı (Bas-Konuş aktif)")
        except Exception as e:
            log.error(f"Yakalama cihazı açılamadı: {e}", exc_info=True)
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
                log.info("Mikrofon yakalama durdu")
        except Exception as e:
            log.error(f"Yakalama akışı durdurulurken hata: {e}", exc_info=True)

    def set_vad_enabled(self, enabled: bool, room_id: int = 0):
        self.vad_enabled = enabled
        if enabled:
            self.start_capture(room_id)
        else:
            self.stop_capture()

    def play_beep(self, frequency: float, duration_ms: int):
        """Bildirim sesi üretir ve jitter buffer'a iter."""
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
            log.error(f"Bip sesi üretilemedi: {e}", exc_info=True)

    def play_audio(self, encoded_bytes: bytes):
        """
        Opus paketini çözer ve jitter buffer'a ekler.
        """
        if self._playback_stream is None or not encoded_bytes:
            return
        try:
            pcm_array = audio_codec.decode(encoded_bytes)
            if len(pcm_array) == 0:
                return
            self._jitter_buffer.push(pcm_array.reshape(-1, CHANNELS))
        except Exception as e:
            log.error(f"Ses çözme/tamponlama hatası: {e}", exc_info=True)

    def shutdown(self):
        log.info("SesMotoru kapatılıyor...")
        self.stop_capture()
        try:
            if self._playback_stream:
                self._playback_stream.stop()
                self._playback_stream.close()
                self._playback_stream = None
        except Exception as e:
            log.error(f"Çalma akışı kapatılırken hata: {e}", exc_info=True)
        self._jitter_buffer.clear()
        log.info("SesMotoru kapatma tamamlandı")

    # ── Dahili callback'ler ────────────────────────────────────

    def _capture_callback(self, indata, frames, time_info, status):
        try:
            if status:
                log.warning(f"Yakalama durumu: {status}")
            if not self._capturing or not self.on_audio_captured:
                return

            pcm_array = indata[:, 0].copy().astype(np.int16)

            if self.vad_enabled:
                rms = np.sqrt(np.mean(np.square(pcm_array.astype(np.float32))))
                if rms < VAD_RMS_THRESHOLD:
                    return

            encoded = audio_codec.encode(pcm_array)
            if encoded:
                self.on_audio_captured(encoded, self.active_room_id)
        except Exception as e:
            log.error(f"Yakalama callback hatası: {e}", exc_info=True)

    def _playback_callback(self, outdata, frames, time_info, status):
        try:
            if status:
                log.debug(f"Çalma durumu: {status}")
            data = self._jitter_buffer.pop()
            if data is not None:
                outdata[:] = data
            else:
                outdata[:] = 0
        except Exception as e:
            outdata[:] = 0
            log.error(f"Çalma callback hatası: {e}", exc_info=True)