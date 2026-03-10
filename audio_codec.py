"""
IMA ADPCM ses codec'i.
16-bit PCM veriyi 4-bit ADPCM'e sıkıştırır (4:1 sıkıştırma oranı).
Saf Python + numpy ile çalışır, harici bağımlılık gerektirmez.
"""

import struct
import logging
import numpy as np

log = logging.getLogger(__name__)

# IMA ADPCM adım tablosu (89 giriş)
_STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17,
    19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118,
    130, 143, 157, 173, 190, 209, 230, 253, 279, 307,
    337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
    876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
    2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
    5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899,
    15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
]

# İndeks tablosu: 4-bit ADPCM kodu -> adım indeksi değişimi
_INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8]


def encode(pcm_data: np.ndarray) -> bytes:
    """
    16-bit PCM veriyi IMA ADPCM formatına kodlar.

    Argümanlar:
        pcm_data: int16 numpy dizisi (mono ses örnekleri)

    Döndürür:
        Kodlanmış ADPCM baytları (başlıkta tahmin ve indeks bilgisi içerir)
    """
    samples = pcm_data.flatten().astype(np.int32)
    num_samples = len(samples)

    # Başlangıç durumu
    predictor = int(samples[0]) if num_samples > 0 else 0
    step_index = 0

    # Başlık: tahmin (int16) + adım_indeksi (uint8) + örnek_sayısı (uint16)
    header = struct.pack("<hBH", np.clip(predictor, -32768, 32767), step_index, num_samples)

    # ADPCM kodlarını oluştur (her biri 4 bit)
    codes = []
    for i in range(num_samples):
        sample = int(samples[i])
        step = _STEP_TABLE[step_index]

        # Farkı hesapla
        diff = sample - predictor

        # İşaret biti
        if diff < 0:
            sign = 8
            diff = -diff
        else:
            sign = 0

        # Farkı kuantize et
        code = 0
        if diff >= step:
            code = 4
            diff -= step
        if diff >= step >> 1:
            code |= 2
            diff -= step >> 1
        if diff >= step >> 2:
            code |= 1

        code |= sign
        codes.append(code)

        # Tahmini güncelle
        step = _STEP_TABLE[step_index]
        diff_q = step >> 3
        if code & 4:
            diff_q += step
        if code & 2:
            diff_q += step >> 1
        if code & 1:
            diff_q += step >> 2

        if code & 8:
            predictor -= diff_q
        else:
            predictor += diff_q

        # Sınırla
        predictor = max(-32768, min(32767, predictor))

        # Adım indeksini güncelle
        step_index += _INDEX_TABLE[code & 7]
        step_index = max(0, min(88, step_index))

    # 4-bit kodları baytlara paketle (her bayt 2 örnek)
    packed = bytearray()
    for i in range(0, len(codes) - 1, 2):
        byte = (codes[i] & 0x0F) | ((codes[i + 1] & 0x0F) << 4)
        packed.append(byte)
    if len(codes) % 2 == 1:
        packed.append(codes[-1] & 0x0F)

    return header + bytes(packed)


def decode(adpcm_data: bytes) -> np.ndarray:
    """
    IMA ADPCM verisinin kodunu çözer ve 16-bit PCM'e dönüştürür.

    Argümanlar:
        adpcm_data: Kodlanmış ADPCM baytları (başlık + veri)

    Döndürür:
        int16 numpy dizisi (mono ses örnekleri)
    """
    if len(adpcm_data) < 5:
        log.warning(f"ADPCM verisi çok kısa: {len(adpcm_data)} bayt")
        return np.zeros(0, dtype=np.int16)

    # Başlığı oku
    predictor, step_index, num_samples = struct.unpack("<hBH", adpcm_data[:5])
    predictor = int(predictor)
    step_index = max(0, min(88, step_index))

    packed_data = adpcm_data[5:]

    # 4-bit kodları çıkar
    codes = []
    for byte in packed_data:
        codes.append(byte & 0x0F)
        codes.append((byte >> 4) & 0x0F)

    # Tam örnek sayısına kırp
    codes = codes[:num_samples]

    # Kodları çöz
    samples = np.zeros(num_samples, dtype=np.int32)
    for i, code in enumerate(codes):
        step = _STEP_TABLE[step_index]

        # Farkı hesapla
        diff_q = step >> 3
        if code & 4:
            diff_q += step
        if code & 2:
            diff_q += step >> 1
        if code & 1:
            diff_q += step >> 2

        if code & 8:
            predictor -= diff_q
        else:
            predictor += diff_q

        # Sınırla
        predictor = max(-32768, min(32767, predictor))
        samples[i] = predictor

        # Adım indeksini güncelle
        step_index += _INDEX_TABLE[code & 7]
        step_index = max(0, min(88, step_index))

    return samples.astype(np.int16)
