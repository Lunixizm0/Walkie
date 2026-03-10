"""
Walkie-Talkie uygulaması için ses motoru.
Mikrofon yakalama ve hoparlör çalma için sounddevice kullanır.
IMA ADPCM codec, gürültü bastırma ve jitter buffer içerir.
"""

import collections
import threading
import logging
import numpy as np
import sounddevice as sd
import audio_codec

log = logging.getLogger(__name__)

# Ses parametreleri
SAMPLE_RATE = 48000   # 48 kHz - yüksek kalite
CHANNELS = 1          # Mono
DTYPE = "int16"       # 16-bit PCM
BLOCK_SIZE = 960      # tampon başına çerçeve (~20ms, 48kHz'de)

# Jitter buffer ayarları
JITTER_BUFFER_MIN = 3   # çalmaya başlamadan önce biriktirilecek minimum paket
JITTER_BUFFER_MAX = 15  # maksimum tampon derinliği (taşma koruması)


class JitterBuffer:
    """
    Gelen ses paketlerini tamponlayarak kesintisiz çalma sağlar.
    Paketler biriktirilir, yeterli derinliğe ulaşınca çalma başlar.
    """

    def __init__(self, min_depth: int = JITTER_BUFFER_MIN, max_depth: int = JITTER_BUFFER_MAX):
        self._buffer: collections.deque[np.ndarray] = collections.deque(maxlen=max_depth)
        self._min_depth = min_depth
        self._started = False
        self._lock = threading.Lock()
        log.info(f"JitterBuffer oluşturuldu (min={min_depth}, maks={max_depth})")

    def push(self, audio_array: np.ndarray):
        """Tampona ses verisi ekler."""
        with self._lock:
            self._buffer.append(audio_array)

    def pop(self) -> np.ndarray | None:
        """
        Tampondan bir ses bloğu alır.
        Yeterli veri birikmediyse None döndürür.
        """
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
                # Tampon tükendi — yeniden doldurulmasını bekle
                self._started = False
                log.debug("JitterBuffer tükendi, yeniden birikme bekleniyor")
                return None

    def clear(self):
        """Tamponu temizler."""
        with self._lock:
            self._buffer.clear()
            self._started = False


class AudioEngine:
    """
    Mikrofon yakalama ve ses çalmayı yönetir.
    IMA ADPCM codec, gürültü bastırma ve jitter buffer içerir.
    """

    def __init__(self, on_audio_captured=None):
        """
        Argümanlar:
            on_audio_captured: geri çağırma(kodlanmış_baytlar) - her yakalanan çerçevede çağrılır
        """
        self.on_audio_captured = on_audio_captured
        self._capturing = False
        self._capture_stream = None
        self._playback_stream = None
        self._lock = threading.Lock()

        # Jitter buffer
        self._jitter_buffer = JitterBuffer()

        log.info(f"SesMotoru başlatılıyor (oran={SAMPLE_RATE}, kanal={CHANNELS}, tip={DTYPE}, blok={BLOCK_SIZE})")

        # Mevcut cihazları listele
        try:
            devices = sd.query_devices()
            log.debug(f"Mevcut ses cihazları:\n{devices}")
            default_input = sd.query_devices(kind='input')
            default_output = sd.query_devices(kind='output')
            log.info(f"Varsayılan giriş cihazı: {default_input['name']}")
            log.info(f"Varsayılan çıkış cihazı: {default_output['name']}")
        except Exception as e:
            log.warning(f"Ses cihazları sorgulanamadı: {e}")

        # Çalma akışı — jitter buffer'dan veri çeken callback ile
        try:
            self._playback_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=BLOCK_SIZE,
                callback=self._playback_callback,
            )
            self._playback_stream.start()
            log.info("Çalma akışı açıldı ve başlatıldı (jitter buffer ile)")
        except Exception as e:
            log.error(f"Çalma cihazı açılamadı: {e}", exc_info=True)
            self._playback_stream = None

    def start_capture(self):
        """Mikrofondan ses yakalamayı başlatır."""
        if self._capturing:
            log.debug("start_capture çağrıldı ama zaten yakalama yapılıyor, atlanıyor")
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
            log.info("Mikrofon yakalama başladı (Bas-Konuş aktif)")
        except Exception as e:
            log.error(f"Yakalama cihazı açılamadı: {e}", exc_info=True)
            self._capturing = False

    def stop_capture(self):
        """Mikrofondan ses yakalamayı durdurur."""
        if not self._capturing:
            log.debug("stop_capture çağrıldı ama yakalama yapılmıyor, atlanıyor")
            return
        self._capturing = False
        try:
            if self._capture_stream:
                self._capture_stream.stop()
                self._capture_stream.close()
                self._capture_stream = None
                log.info("Mikrofon yakalama durdu (Bas-Konuş bırakıldı)")
        except Exception as e:
            log.error(f"Yakalama akışı durdurulurken hata: {e}", exc_info=True)

    def play_audio(self, encoded_bytes: bytes):
        """
        Kodlanmış ses verisini çözer ve jitter buffer'a ekler.
        Çalma, buffer'dan otomatik olarak callback ile yapılır.
        """
        if self._playback_stream is None:
            return
        try:
            # ADPCM kodunu çöz
            pcm_array = audio_codec.decode(encoded_bytes)
            if len(pcm_array) == 0:
                return

            # Doğru blok boyutuna getir
            pcm_array = pcm_array[:BLOCK_SIZE]
            if len(pcm_array) < BLOCK_SIZE:
                # Eksik örnekleri sıfırla
                padded = np.zeros(BLOCK_SIZE, dtype=np.int16)
                padded[:len(pcm_array)] = pcm_array
                pcm_array = padded

            # Jitter buffer'a ekle
            self._jitter_buffer.push(pcm_array.reshape(-1, CHANNELS))
        except Exception as e:
            log.error(f"Ses çözme/tamponlama hatası: {e}", exc_info=True)

    def shutdown(self):
        """Tüm ses kaynaklarını temizler."""
        log.info("SesMotoru kapatılıyor...")
        self.stop_capture()
        try:
            if self._playback_stream:
                self._playback_stream.stop()
                self._playback_stream.close()
                self._playback_stream = None
                log.info("Çalma akışı kapatıldı")
        except Exception as e:
            log.error(f"Çalma akışı kapatılırken hata: {e}", exc_info=True)
        self._jitter_buffer.clear()
        log.info("SesMotoru kapatma tamamlandı")

    def _capture_callback(self, indata, frames, time_info, status):
        """Ses verisi yakalandığında sounddevice tarafından çağrılır."""
        try:
            if status:
                log.warning(f"Ses yakalama durumu: {status}")
            if not self._capturing or not self.on_audio_captured:
                return

            # Ham PCM verisini al
            pcm_array = indata[:, 0].copy()  # mono
            pcm_array = pcm_array.astype(np.int16)

            # ADPCM ile kodla
            encoded = audio_codec.encode(pcm_array)

            # Geri çağırma ile gönder
            self.on_audio_captured(encoded)
        except Exception as e:
            log.error(f"Yakalama geri çağırmasında hata: {e}", exc_info=True)

    def _playback_callback(self, outdata, frames, time_info, status):
        """Ses çıkışı için veri gerektiğinde sounddevice tarafından çağrılır."""
        try:
            if status:
                log.debug(f"Çalma durumu: {status}")

            data = self._jitter_buffer.pop()
            if data is not None:
                outdata[:] = data
            else:
                # Tampon boş — sessizlik çal
                outdata[:] = 0
        except Exception as e:
            outdata[:] = 0
            log.error(f"Çalma geri çağırmasında hata: {e}", exc_info=True)
