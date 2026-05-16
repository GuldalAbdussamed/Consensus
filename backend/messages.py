"""
Worker'lar arası veri sözleşmeleri.

Her dataclass bir queue mesajıdır. Mutasyon yok — sadece üret/oku.

Zaman damgaları iki türlü:
- wall_time:  time.time() ile alınmış UNIX timestamp (gecikme/stale kontrolü için)
- video_time: video başlangıcından itibaren saniye (loglama, zaman hizalama için)
"""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


# ============================================================
# video_source.py çıktıları
# ============================================================

@dataclass
class FrameItem:
    """Video'dan yakalanmış tek bir frame.

    video_source bunu üretir. VAD bir boşluk bildirdiğinde
    o anki video_time'a en yakın frame seçilir.
    """
    wall_time: float       # ne zaman yakalandı (UNIX timestamp)
    video_time: float      # video içinde hangi saniyeye denk geliyor
    image: np.ndarray      # BGR, OpenCV formatı


@dataclass
class AudioChunk:
    """Audio stream'den gelen ham PCM parçası.

    video_source iki ayrı queue'ya audio basar:
    - lookahead queue (VAD için, 2sn ileride)
    - realtime queue (mixer için, normal hız)

    Her ikisinde de aynı format.
    """
    wall_time: float          # ne zaman queue'ya kondu
    video_time_start: float   # bu chunk'ın video içindeki başlangıç saniyesi
    video_time_end: float     # bitiş saniyesi
    pcm: np.ndarray           # float32, mono, AUDIO_SAMPLE_RATE
    sample_rate: int


# ============================================================
# vad.py çıktıları
# ============================================================

@dataclass
class GapItem:
    """VAD'in tespit ettiği konuşma boşluğu.

    Sahne galerisi kontrolünden geçmiş — yani:
    - Yeterince uzun (>= MIN_GAP_SEC)
    - Sahne yeni veya farklı (galeride yok)

    vlm_worker bunu alır ve betimleme üretir.
    """
    video_time_start: float   # boşluğun başlangıcı
    video_time_end: float     # boşluğun bitişi
    video_time_center: float  # frame penceresinin merkez noktası
    available_seconds: float  # boşluk uzunluğu (kelime bütçesi için)
    frames: list[np.ndarray]  # FRAME_WINDOW_OFFSETS'e göre 3 frame (BGR)
    is_first: bool            # ilk betimleme mi (prompt modu için)
    context: list[str]        # son N betimleme (prompt'a geri besleme)
    wall_time: float          # ne zaman üretildi (stale kontrolü)


# ============================================================
# vlm.py çıktıları
# ============================================================

@dataclass
class DescriptionItem:
    """VLM'in ürettiği, temizlenmiş, filtrelerden geçmiş betimleme.

    Buraya gelmişse:
    - Meta-pattern temizlenmiş ("Bu karede..." vb. atılmış)
    - is_too_weak filtresinden geçmiş
    - Jaccard tekrar filtresinden geçmiş
    - Sahne galerisine kaydedilmiş

    tts_worker bunu alır ve sese çevirir.
    """
    video_time_start: float   # boşluğun başlangıcı (mix zamanlaması için)
    video_time_end: float
    text: str                 # söylenecek Türkçe cümle
    available_seconds: float
    wall_time: float          # vlm çağrısı bittiği an


# ============================================================
# tts.py çıktıları
# ============================================================

@dataclass
class AudioItem:
    """TTS'in ürettiği hazır ses.

    mixer_worker bunu alır, video_time_start zamanı geldiğinde
    orijinal sesi duckler ve bunu üstüne miks eder.

    Eğer wall_time + MAX_AUDIO_AGE_SEC geçmişse çöpe atılır
    (konuşma başladı, geç kaldık).
    """
    video_time_start: float   # boşluğun başlangıcı (ne zaman çalmalı)
    text: str                 # log için
    pcm: np.ndarray           # float32 mono, sample_rate'e göre
    sample_rate: int          # genelde TTS_SAMPLE_RATE (24000)
    wall_time: float          # TTS çağrısı bittiği an


# ============================================================
# Yardımcı: stop event ile birlikte gelen sentinel
# ============================================================

@dataclass
class StreamEnded:
    """Bir queue'ya bu nesne konulduğunda 'akış bitti' demektir.
    Tüketici worker'lar bunu görünce graceful kapatır.
    """
    reason: str = "eof"
