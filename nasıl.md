# 📻 Walkie-Talkie — Proje Dokümantasyonu

> **Proje Türü:** Bilgisayar Ağları / Yazılım Geliştirme  
> **Dil:** Python 3.14
> **Platform:** Windows / Linux
> **Amaç:** Yerel ağ (LAN) üzerinden sunucusuz, eşler arası (peer-to-peer) sesli ve yazılı iletişim uygulaması

---

## İçindekiler

1. [Projeye Genel Bakış](#1-projeye-genel-bakış)
2. [Sistem Mimarisi](#2-sistem-mimarisi)
3. [Modüller ve Dosya Yapısı](#3-modüller-ve-dosya-yapısı)
4. [Ağ Katmanı — network.py](#4-ağ-katmanı--networkpy)
5. [Ses Motoru — audio_engine.py](#5-ses-motoru--audio_enginepy)
6. [Ses Codec'i — audio_codec.py](#6-ses-codeci--audio_codecpy)
7. [Şifreleme — crypto_utils.py](#7-şifreleme--crypto_utilspy)
8. [Arayüz — gui.py](#8-arayüz--guipy)
9. [Uygulama Giriş Noktası — main.py](#9-uygulama-giriş-noktası--mainpy)
10. [Veri Akışı Diyagramları](#10-veri-akışı-diyagramları)
11. [Kullanılan Teknolojiler ve Kütüphaneler](#11-kullanılan-teknolojiler-ve-kütüphaneler)
12. [Kurulum ve Çalıştırma](#12-kurulum-ve-çalıştırma)
13. [Güvenlik Analizi](#13-güvenlik-analizi)
14. [Performans ve Optimizasyon](#14-performans-ve-optimizasyon)

---

## 1. Projeye Genel Bakış

Bu proje, aynı yerel ağa bağlı bilgisayarlar arasında **merkezi bir sunucuya ihtiyaç duymadan** gerçek zamanlı sesli iletişim ve metin sohbeti sağlayan bir uygulamadır. Gerçek hayattaki telsiz (walkie-talkie) cihazlarından ilham alınarak tasarlanmıştır.

### Temel Özellikler

| Özellik                 | Açıklama                                                |
| ----------------------- | ------------------------------------------------------- |
| **Sunucusuz Mimari**    | Tüm cihazlar eşit konumdadır, merkezi sunucu yoktur     |
| **Otomatik Eş Keşfi**   | Aynı ağdaki kullanıcılar birbirini otomatik bulur       |
| **Bas-Konuş (PTT)**     | Shift+V tuşuyla gerçek telsiz deneyimi                  |
| **Sesli Yayın**         | Normal sesli yayın                                      |
| **Uçtan Uca Şifreleme** | AES-256-GCM ile tüm ses ve metin şifrelenir             |
| **Çoklu Kanal**         | Genel, Öğretmenler Arası ve ThinkTank kanalları         |
| **Opus Codec**          | Yüksek kaliteli, düşük bant genişliğinde ses sıkıştırma |

---

## 2. Sistem Mimarisi

### 2.1 Genel Mimari: Peer-to-Peer (P2P)

Geleneksel istemci-sunucu mimarisinin aksine bu uygulama **tamamen dağıtık** çalışır. Her bir bilgisayar hem gönderici hem de alıcı konumundadır.

```
┌─────────────────────────────────────────────────────────┐
│                   YEREL AĞ (LAN)                        │
│                                                         │
│   ┌──────────┐         ┌──────────┐         ┌────────┐  │
│   │ Cihaz A  │◄───────►│ Cihaz B  │◄───────►│Cihaz C │  │
│   │ (Fatih)  │         │ (Ahmet)  │         │ (Ayşe) │  │
│   └──────────┘         └──────────┘         └────────┘  │
│        │                    │                    │      │
│        └────────────────────┴────────────────────┘      │
│                     UDP Broadcast                       │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Port Yapısı

Uygulama üç farklı UDP portu kullanır; her biri ayrı bir görev üstlenir:

| Port      | Protokol      | Görev                          |
| --------- | ------------- | ------------------------------ |
| **50000** | UDP Broadcast | Eş keşfi (Hello/Bye paketleri) |
| **50001** | UDP Broadcast | Şifreli metin mesajları        |
| **50002** | UDP Broadcast | Şifreli ses paketleri          |

### 2.3 Katmanlı Mimari

```
┌─────────────────────────────────┐
│          GUI Katmanı            │  ← Kullanıcı arayüzü (tkinter)
├─────────────────────────────────┤
│       Uygulama Katmanı          │  ← main.py (modülleri bağlar)
├──────────────┬──────────────────┤
│  Ses Motoru  │   Ağ Katmanı     │  ← audio_engine.py / network.py
├──────────────┼──────────────────┤
│  Ses Codec   │   Şifreleme      │  ← audio_codec.py / crypto_utils.py
└──────────────┴──────────────────┘
```

---

## 3. Modüller ve Dosya Yapısı

```
Walkie/
│
├── main.py              # Uygulama giriş noktası, modülleri birbirine bağlar
├── gui.py               # Tkinter arayüzü (giriş ekranı + ana pencere)
├── network.py           # UDP ağ katmanı (keşif, sohbet, ses aktarımı)
├── audio_engine.py      # Mikrofon yakalama ve ses çalma motoru
├── audio_codec.py       # Opus ses codec'i (PyAV ile)
├── crypto_utils.py      # AES-256-GCM şifreleme araçları
└── requirements.txt     # Python bağımlılıkları
```

---

## 4. Ağ Katmanı — network.py

Bu modül uygulamanın ağ ile tüm iletişimini yönetir. Üç ana sınıf içerir.

### 4.1 PeerDiscovery — Eş Keşfi

Aynı ağdaki diğer kullanıcıları bulmak için **UDP broadcast** (yayın) kullanılır. Broadcast, paketin ağdaki tüm cihazlara aynı anda gönderilmesi anlamına gelir.

#### Nasıl Çalışır?

```
Her 2 saniyede bir:
  Cihaz A  ──── HELLO (OdaID + KullanıcıAdı) ────► 192.168.1.255
               (broadcast — tüm cihazlar alır)

  Cihaz B  alır → "A çevrimiçi" kaydeder
  Cihaz C  alır → "A çevrimiçi" kaydeder

10 saniye HELLO gelmezse:
  Cihaz A zaman aşımına uğradı → listeden silinir
```

#### Paket Yapısı

```
┌──────────┬──────────┬──────────────────────┐
│ MSG_HELLO│  OdaID   │    KullanıcıAdı       │
│  1 byte  │  1 byte  │    N byte (UTF-8)     │
└──────────┴──────────┴──────────────────────┘
```

**MSG_HELLO (0x01):** Yeni bir cihazın varlığını duyurur  
**MSG_BYE (0x02):** Uygulama kapanırken "veda" paketi gönderilir, diğerleri anında güncellenir

#### Çoklu Ağ Arayüzü Desteği

Bir bilgisayarda birden fazla ağ kartı olabilir (Ethernet, Wi-Fi, sanal adaptörler). Uygulama tüm arayüzlerin IP adreslerini tespit ederek hem kendi paketlerini tanır hem de tüm alt ağlara yayın yapabilir:

```python
# Tespit edilen IP'ler (örnek):
{'192.168.1.110', '192.168.146.1', '172.23.144.1', '127.0.0.1'}

# Yayın yapılan adresler:
['<broadcast>', '192.168.1.255', '192.168.146.255', '172.23.144.255']
```

#### Thread Yapısı

`PeerDiscovery` üç ayrı thread ile çalışır:

```
Ana Thread
    │
    ├── _broadcast_loop (Thread 1)   → Her 2s'de HELLO yayınlar
    ├── _listen_loop    (Thread 2)   → Gelen paketleri dinler
    └── _cleanup_loop   (Thread 3)   → 10s görülmeyenleri siler
```

### 4.2 ChatTransport — Metin Sohbeti

Şifreli metin mesajlarını UDP broadcast üzerinden gönderir ve alır.

#### Paket Yapısı

```
┌──────────┬──────────┬─────────────────────────────────────────┐
│ MSG_CHAT │  OdaID   │         AES-GCM Şifreli Veri            │
│  1 byte  │  1 byte  │  [Nonce(12)] + [Ad_Uzun(1)+Ad+Mesaj]    │
└──────────┴──────────┴─────────────────────────────────────────┘
```

Alıcı tarafta:

1. Paket türü kontrol edilir (`MSG_CHAT`)
2. Oda ID'si kontrol edilir (yanlış odanın mesajı atlanır)
3. Şifre çözme yapılır (yanlış anahtarla çözülemezse atlanır)
4. Gönderen adı ve mesaj ayrıştırılır

### 4.3 VoiceTransport — Ses Aktarımı

Şifreli Opus ses paketlerini gerçek zamanlı olarak iletir.

#### Paket Yapısı

```
┌───────────┬──────────┬─────────────────────────────────────────┐
│ MSG_VOICE │  OdaID   │         AES-GCM Şifreli Veri            │
│   1 byte  │  1 byte  │  [Nonce(12)] + [Ad_Uzun(1)+Ad+OpusPCM] │
└───────────┴──────────┴─────────────────────────────────────────┘
```

---

## 5. Ses Motoru — audio_engine.py

Bu modül mikrofondan ses yakalar, Opus ile kodlar; ağdan gelen Opus paketlerini çözer ve hoparlörden çalar.

### 5.1 Ses Parametreleri

| Parametre   | Değer     | Açıklama           |
| ----------- | --------- | ------------------ |
| Sample Rate | 48.000 Hz | Saniyede 48.000    |
| Channels    | 1 (Mono)  | Tek kanal          |
| Dtype       | int16     | 16-bit tam sayı    |
| Frame Size  | 960 örnek | 20ms'lik ses bloğu |

### 5.2 JitterBuffer

Ağ üzerinden gelen ses paketleri her zaman düzenli aralıklarla gelmez — ağ yoğunluğuna bağlı olarak bazen geç, bazen erken, bazen de toplu hâlde ulaşabilir. Bu duruma **jitter** (titreşim/gecikme dalgalanması) denir.

```
Ağdan gelen paketler (düzensiz):
▓░░▓▓░▓░░░▓▓▓░▓ ← boşluklar ve yığılmalar var

JitterBuffer sonrası (düzenli):
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ← akıcı ses çıkışı
```

#### Tampon Mantığı

```
BAŞLANGIÇ:
  Buffer dolmaya başlar

  [pkt1][pkt2][pkt3][pkt4] → Min derinlik (4 paket = 80ms) doldu
                           → Çalma başlar!

ÇALMA SIRASINDA:
  Gelen paket → Buffer'ın sonuna eklenir
  Çalma      → Buffer'ın başından alınır
  (FIFO: İlk giren, ilk çıkar)

BUFFER TÜKENİRSE:
  _started = False → Yeniden 4 paket birikene kadar bekle
```

**Neden bu gecikme gerekli?** 80ms başlangıç gecikmesi anlık kesintileri önlemek için kasıtlıdır. Gerçek zamanlı iletişimde kısa bir gecikme kabul edilebilirdir; ancak kesik kesik ses kullanılamaz.

### 5.3 Sesli Yayın

Sesli Yayın bas konuş yerine toggle ile çalışır.

### 5.4 Ses Akışı Callback Modeli

`sounddevice` kütüphanesi **callback (geri çağırma)** modeli kullanır. Bu modelde ses işleme kodu ana programdan bağımsız, ayrı bir thread'de çalışır:

```
sounddevice (OS Ses Sürücüsü)
    │
    ├── _capture_callback()   → Her 20ms'de mikrofon verisini teslim eder
    │       └── VAD kontrolü → encode() → şifrele → ağa gönder
    │
    └── _playback_callback()  → Her 20ms'de hoparlöre veri ister
            └── JitterBuffer.pop() → veri varsa çal, yoksa sessizlik (sıfır)
```

---

## 6. Ses Codec'i — audio_codec.py

### 6.1 Neden Sıkıştırma Gerekli?

Ham 16-bit PCM ses, 48.000 Hz sample rate ile saniyede şu kadar veri üretir:

```
48.000 örnek/s × 2 byte/örnek × 1 kanal = 96.000 byte/s = 768 kbps
```

Bu, yerel ağda sorun olmasa da gereksiz yük oluşturur. Opus ile bu **24 kbps'e** düşer — **32 kat sıkıştırma** — üstelik ses kalitesi çok daha iyi.

#### Opus'un Avantajları

| Özellik               | Açıklama                                             |
| --------------------- | ---------------------------------------------------- |
| **Düşük gecikme**     | 20ms frame ile gerçek zamanlı iletişim için ideal    |
| **Adaptif bitrate**   | 6 kbps'den 510 kbps'e kadar ayarlanabilir            |
| **Gürültü toleransı** | Paket kaybı durumunda FEC (Forward Error Correction) |

#### Encode Süreci

```
Ham PCM (int16)
    │
    ▼
int16 → float32 dönüşümü
  (/ 32768.0 ile normalize: -1.0 ile +1.0 arasına)
    │
    ▼
AudioFrame.from_ndarray()
  (PyAV ile fltp formatında frame oluştur)
    │
    ▼
_encoder.encode(frame)
  (FFmpeg Opus encoder — frekans analizi)
    │
    ▼
encode(None) → flush
  (Delayed encoder'ı zorla boşalt)
    │
    ▼
Ham Opus paketi (bytes) → Ağa gönderilir
```

#### Decode Süreci

```
Ham Opus paketi (bytes) ← Ağdan alındı
    │
    ▼
av.Packet(opus_bytes)
    │
    ▼
_decoder.decode(packet)
  (FFmpeg Opus decoder)
    │
    ▼
to_ndarray() → float32 array
    │
    ▼
float32 → int16
  (× 32767 ile geri ölçekle, clip ile taşmayı önle)
    │
    ▼
JitterBuffer'a eklenir → Hoparlörden çalınır
```

### 6.3 PyAV ve FFmpeg

PyAV, FFmpeg kütüphanesinin Python için hazırlanmış bağlantı katmanıdır.

---

## 7. Şifreleme — crypto_utils.py

Tüm ses ve metin iletişimi uçtan uca şifrelenir. Bu, ağı dinleyen birinin mesajları okuyamaması anlamına gelir.

### 7.1 AES-256-GCM

**AES (Advanced Encryption Standard)** dünyada en yaygın kullanılan simetrik şifreleme algoritmasıdır. **GCM (Galois/Counter Mode)** ise hem şifreleme hem de **kimlik doğrulama** sağlayan bir çalışma modudur.

```
Gönderici:
  Düz Metin + Anahtar + Nonce (12 byte rastgele)
      │
      ▼
  AES-256-GCM Şifreleme
      │
      ▼
  Şifreli Metin + Kimlik Doğrulama Etiketi (Tag)

Alıcı:
  Şifreli Metin + Anahtar + Nonce + Tag
      │
      ▼
  AES-256-GCM Çözme + Doğrulama
      │
      ├── Başarılı → Düz Metin
      └── Başarısız → None (paket bozuk veya yanlış anahtar)
```

**GCM'nin önemi:** Sadece şifreleme yapmaz, aynı zamanda verinin yolda değiştirilmediğini de doğrular. Bu özellik olmadan, birisi şifreli paketi değiştirip alıcıya gönderebilirdi (man-in-the-middle saldırısı).

### 7.2 Nonce Kullanımı

Her şifreleme işleminde **12 byte rastgele nonce (number used once)** üretilir:

```python
nonce = os.urandom(12)  # Her seferinde farklı
```

Aynı anahtar ve aynı veri için bile her şifrelemede farklı şifreli metin üretilir. Bu, saldırganların şifreli mesajları karşılaştırarak pattern (örüntü) bulmasını engeller.

### 7.3 Anahtar Türetme — PBKDF2

Kullanıcının girdiği şifre (`fatih`) doğrudan şifreleme anahtarı olarak kullanılamaz çünkü çok kısadır. **PBKDF2 (Password-Based Key Derivation Function 2)** ile şifreden güçlü bir anahtar türetilir:

```
Şifre: "fatih"
Sabit Tuz: "walkie-talkie-lan-salt-2026"
İterasyon: 100.000 kez SHA-256

→ 256-bit (32 byte) AES Anahtarı
```

**100.000 iterasyon neden önemli?** Brute-force saldırılarını yavaşlatır. Normal bir bilgisayar saniyede milyarlarca şifre deneyebilir, ancak her deneme için 100.000 SHA-256 hesaplamak gerekirse bu süre ciddi ölçüde artar.

### 7.4 Kanal Güvenliği

| Kanal               | Anahtar Türü            | Açıklama         |
| ------------------- | ----------------------- | ---------------- |
| Genel (ID: 0)       | Sabit hardcoded anahtar | Herkes duyabilir |
| Öğretmenler (ID: 1) | PBKDF2("fatih")         | Şifreli kanal    |
| ThinkTank (ID: 2)   | PBKDF2("fatih")         | Şifreli kanal    |

Öğretmenler ve ThinkTank kanalları aynı şifreyle türetilse de **farklı oda ID'leri** olduğundan ağ katmanında birbirinden izole çalışır.

---

## 8. Arayüz — gui.py

### 8.1 StartupDialog — Giriş Ekranı

Uygulama açılışında kullanılan sayfa.

Şifre doğrulaması: Yalnızca `fatih` kabul edilir. Yanlış giriş yapılınca şifre kutusu kırmızıya döner.

### 8.2 WalkieTalkieGUI — Ana Pencere

```
┌──────────────┬─────────────────────────────────────────┐
│  📡 Çevrimiçi│  💬 Kanal Sohbeti    [Yayın Kanalı ▼]  │
│  Eşler       ├─────────────────────────────────────────┤
│              │  [10:32] [Genel] Fatih: merhaba         │
│  ● Sen       │  [10:33] [Genel] Ahmet: selam           │
│  ─────────   │                                         │
│  ● Ahmet     │                                         │
│    192.168.. │                                         │
│              ├─────────────────────────────────────────┤
│              │  [Mesaj yazın...        ] [Gönder]      │
│              ├─────────────────────────────────────────┤
│              │  ● HAZIR · Shift+V basılı tut  [VAD]    │
└──────────────┴─────────────────────────────────────────┘
```

### 8.3 Thread Güvenliği

Tkinter yalnızca ana thread'den güncelleme kabul eder. Ağ ve ses thread'lerinden arayüz güncellemek için `root.after(0, _update)` kullanılır — bu güncellemeyi ana thread'in olay döngüsüne kuyruğa ekler:

```python
def update_peers(self, peers):
    def _update():        # Bu fonksiyon...
        # ...tkinter widgetlarını günceller
    self.root.after(0, _update)  # ...ana thread'de çalışır
```

### 8.4 Sistem Tepsisi Entegrasyonu

Kapatma butonuna basıldığında kullanıcıya seçenek sunulur:

```
┌────────────────────────────┐
│  Ne yapmak istiyorsunuz?   │
│                            │
│  [🔽 Traye Küçült] [❌ Çık] │
└────────────────────────────┘
```

"Traye Küçült" seçilirse pencere gizlenir, sistem tepsisinde ikon kalır. Uygulama arka planda çalışmaya devam eder — ses ve mesajlar iletilmeyi sürdürür.

---

## 9. Uygulama Giriş Noktası — main.py

`main.py` tüm modülleri bir araya getiren "orkestratör" görevi görür. Hiçbir iş mantığı içermez — sadece bileşenleri oluşturur ve birbirine bağlar.

### 9.1 Başlangıç Sırası

```
1. StartupDialog  → Kullanıcı adı ve şifre al
2. derive_key()   → Şifreleme anahtarları türet
3. VoiceTransport → Ses ağ katmanını hazırla
4. ChatTransport  → Sohbet ağ katmanını hazırla
5. PeerDiscovery  → Eş keşif sistemini hazırla
6. AudioEngine    → Ses motorunu başlat (playback açılır)
7. WalkieTalkieGUI → Arayüzü oluştur
8. Callback'leri bağla (geri çağırma fonksiyonları)
9. Tüm servisleri başlat (thread'ler devreye girer)
10. GUI mainloop() → Pencereyi göster, olayları bekle
```

### 9.2 Callback Zinciri

Modüller birbirini doğrudan çağırmaz — bunun yerine **callback (geri çağırma)** fonksiyonları aracılığıyla haberleşir. Bu yaklaşım modüller arasındaki bağımlılığı azaltır:

```
Mikrofon → AudioEngine._capture_callback()
               └── audio_codec.encode()
                       └── VoiceTransport.send_voice()
                               └── şifrele → UDP paketi → ağa gönder

Ağdan gelir → VoiceTransport._listen_loop()
               └── şifre çöz → on_voice callback
                       └── AudioEngine.play_audio()
                               └── audio_codec.decode()
                                       └── JitterBuffer.push()
                                               └── hoparlörden çalınır
```

---

## 10. Veri Akışı Diyagramları

### 10.1 Ses Gönderme Akışı

```
[Kullanıcı Shift+V'ye basar]
         │
         ▼
  AudioEngine.start_capture()
         │
         ▼ (her 20ms)
  sounddevice callback → ham PCM (960 örnek, int16)
         │
         ├─[VAD açıksa]→ RMS hesapla → eşik altıysa DUR
         │
         ▼
  audio_codec.encode() → Opus paketi (~50-150 byte)
         │
         ▼
  crypto_utils.encrypt() → Nonce + Şifreli Veri
         │
         ▼
  MSG_VOICE + OdaID + Şifreli Veri
         │
         ▼
  UDP Broadcast → 192.168.1.255:50002
         │
         ▼
  [Tüm ağdaki cihazlar alır]
```

### 10.2 Ses Alma Akışı

```
  UDP:50002 → VoiceTransport._listen_loop()
         │
         ├─[Kendi IP'si mi?]→ ATLA
         ├─[Doğru oda ID?]→ Değilse ATLA
         │
         ▼
  crypto_utils.decrypt() → Düz Metin
         │
         ├─[Şifre çözülemedi?]→ ATLA (yanlış anahtar)
         │
         ▼
  Gönderen adı + Opus ses verisi ayrıştır
         │
         ▼
  on_voice callback → AudioEngine.play_audio()
         │
         ▼
  audio_codec.decode() → int16 PCM (960 örnek)
         │
         ▼
  JitterBuffer.push() → tampona ekle
         │
         ▼ (her 20ms, sounddevice callback)
  JitterBuffer.pop() → hoparlöre ver
```

### 10.3 Eş Keşfi Akışı

```
  [Uygulama başlar]
         │
         ▼ (her 2s)
  MSG_HELLO + OdaID + KullanıcıAdı → Broadcast

  [Diğer cihaz alır]
         │
         ├─[Kendi paketi mi?]→ ATLA
         ├─[Doğru oda ID?]→ Değilse ATLA
         │
         ▼
  peers[ip] = (ad, şu_an)   ← listeye ekle
         │
         ▼
  on_peers_changed() → GUI güncelle

  [10s sonra HELLO gelmezse]
         │
         ▼
  peers[ip] sil → GUI güncelle
```

---

## 11. Kullanılan Teknolojiler ve Kütüphaneler

### 11.1 Python Standart Kütüphaneleri

| Kütüphane           | Kullanım Amacı                     |
| ------------------- | ---------------------------------- |
| `socket`            | UDP soket oluşturma ve yönetimi    |
| `threading`         | Çoklu thread (paralel işlem)       |
| `struct`            | Binary veri paketleme/çözme        |
| `collections.deque` | JitterBuffer için çift uçlu kuyruk |
| `ctypes`            | Düşük seviye bellek erişimi        |
| `os`                | Rastgele nonce üretimi             |
| `tkinter`           | GUI arayüzü                        |

### 11.2 Üçüncü Parti Kütüphaneler

| Kütüphane      | Versiyon | Kullanım Amacı                                |
| -------------- | -------- | --------------------------------------------- |
| `sounddevice`  | Latest   | Mikrofon/hoparlör erişimi (PortAudio üzerine) |
| `numpy`        | Latest   | Ses verisi için verimli dizi işlemleri        |
| `cryptography` | Latest   | AES-GCM şifreleme, PBKDF2 anahtar türetme     |
| `av` (PyAV)    | 16.x     | Opus codec — FFmpeg Python bağlantısı         |
| `pystray`      | Latest   | Sistem tepsisi entegrasyonu                   |
| `Pillow`       | Latest   | Tepsi ikonu oluşturma                         |

### 11.3 Protokoller ve Standartlar

| Protokol/Standart | Kullanım                                         |
| ----------------- | ------------------------------------------------ |
| **UDP**           | Tüm ağ iletişimi (düşük gecikme için TCP yerine) |
| **Opus**          | Ses sıkıştırma codec'i (RFC 6716)                |
| **AES-256-GCM**   | Kimlik doğrulamalı şifreleme                     |
| **PBKDF2-SHA256** | Şifreden anahtar türetme (RFC 2898)              |

**Neden TCP değil UDP?** TCP her paketin ulaşmasını garantiler ve yeniden gönderim yapar. Sesli iletişimde geç gelen bir paket yeniden gönderilse bile artık yararsızdır — oynatma zamanı çoktan geçmiştir. UDP bu garantiyi vermez ama gecikme çok düşüktür. Kayıp paket sessizlik olarak geçilir, bu sesli iletişimde kabul edilebilir.

---

## 12. Kurulum ve Çalıştırma

### 12.1 Gereksinimler

- Python 3.11 veya üzeri
- Windows 10/11 (Linux ve macOS da desteklenir)
- Aynı yerel ağa bağlı en az 2 bilgisayar

### 12.2 Kurulum Adımları

```bash
# 1. Sanal ortam oluştur
python -m venv .venv

# 2. Sanal ortamı aktifleştir (Windows)
.venv\Scripts\activate

# 3. Bağımlılıkları kur
pip install -r requirements.txt
```

**requirements.txt içeriği:**

```
sounddevice
numpy
cryptography
pystray
Pillow
av
```

### 12.3 Çalıştırma

```bash
python main.py
```

### 12.4 Kullanım

1. Uygulamayı başlatın, adınızı girin
2. İstediğiniz kanalları seçin (şifreli kanallar için `fatih` şifresi)
3. **Shift+V** tuşunu basılı tutarak konuşun, bırakınca durursiniz
4. **VAD** butonuyla sesle aktivasyon modunu açabilirsiniz
5. Sohbet kutusuna yazıp Enter veya "Gönder" ile mesaj gönderin
6. Kanal değiştirmek için sağ üstteki "Yayın Kanalı" açılır menüsünü kullanın

---

## 13. Güvenlik Analizi

### 13.1 Sağlanan Güvenlik Özellikleri

**Gizlilik (Confidentiality):** AES-256-GCM şifreleme ile ağı dinleyen biri sesi veya mesajları okuyamaz.

**Bütünlük (Integrity):** GCM'nin kimlik doğrulama etiketi (authentication tag) sayesinde verinin yolda değiştirilip değiştirilmediği tespit edilir.

**Yeniden Oynatma Koruması (Replay Protection):** Her pakette rastgele nonce kullanıldığından, saldırgan aynı paketi tekrar gönderse bile şifre çözme başarısız olur (farklı nonce beklenir).

### 13.2 Mevcut Sınırlamalar

**Genel Oda:** Genel kanal sabit (hardcoded) bir anahtarla çalışır. Ağı bilen herkes bu kanalı dinleyebilir — bu tasarım gereğidir.

**Şifre Sabit:** `fatih` şifresi kodun içine yazılmıştır. Gerçek bir uygulamada yönetici tarafından değiştirilebilir olması tercih edilirdi.

**Kimlik Doğrulama Yok:** Kullanıcı adları doğrulanmaz; birisi başkasının adını yazarak giriş yapabilir.

---

## 14. Performans ve Optimizasyon

### 14.1 Bant Genişliği Kullanımı

| Bileşen          | Boyut         | Frekans  | Bant Genişliği   |
| ---------------- | ------------- | -------- | ---------------- |
| Opus ses paketi  | ~80 byte      | 50/s     | ~32 kbps         |
| AES-GCM overhead | +28 byte      | 50/s     | +11 kbps         |
| UDP/IP header    | +28 byte      | 50/s     | +11 kbps         |
| **Toplam (ses)** | **~136 byte** | **50/s** | **~54 kbps**     |
| HELLO paketi     | ~20 byte      | 0.5/s    | ihmal edilebilir |

### 14.2 Gecikme Analizi

```
Mikrofon → encode:     ~1ms  (Opus encoding)
encode → şifrele:      ~0.1ms
şifrele → ağ:          ~0.1ms
Ağ gecikmesi (LAN):    ~1ms
Ağdan al → şifre çöz:  ~0.1ms
JitterBuffer bekle:    ~80ms  ← Toplam gecikmenin büyük kısmı
decode → hoparlör:     ~1ms

Toplam: ~83ms
```

80ms JitterBuffer gecikmesi kasıtlıdır. Bu değer azaltılabilir ama ağ dalgalanmalarına karşı dayanıklılık düşer.

### 14.3 Thread Modeli

```
Ana Thread:         GUI (tkinter mainloop)
Thread Pool:
  ├── broadcast_loop      (PeerDiscovery)
  ├── discovery_listen    (PeerDiscovery)
  ├── cleanup_loop        (PeerDiscovery)
  ├── chat_listen         (ChatTransport)
  ├── voice_listen        (VoiceTransport)
  └── tray_icon (opsiyonel, tepsi aktifken)

sounddevice (OS yönetiminde):
  ├── capture_callback    (ses yakalama)
  └── playback_callback   (ses çalma)
```

Thread'ler arası paylaşılan veri yapıları (`JitterBuffer`, `peers` dict) `threading.Lock()` ile korunur — bu, aynı anda iki thread'in aynı veriyi bozmasını engeller.
