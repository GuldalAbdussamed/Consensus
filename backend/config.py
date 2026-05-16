"""
Engelsiz TV - Tüm tunable parametreler tek yerde.

Hackathon temposunda eşikleri sürekli oynayacağız. Burası tek doğruluk kaynağı.
"""

# ============================================================
# Servis URL'leri
# ============================================================

# vLLM (Qwen2.5-VL) sunucusu — AWS L40S
VLLM_URL = "http://ec2-3-145-206-228.us-east-2.compute.amazonaws.com:8000/v1"
VLLM_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
VLLM_API_KEY = "dummy"  # vLLM doğrulama istemiyor

# XTTS-v2 sunucusu — aynı L40S, yan yana (durum notu kararı)
# tts_server.py'ı L40S'te başlatınca burayı güncelle
TTS_URL = "http://ec2-3-144-104-180.us-east-2.compute.amazonaws.com:8020"
TTS_LANGUAGE = "tr"
TTS_SPEAKER_WAV = None  # None = default ses; ileride ses klonlama için referans WAV

# ============================================================
# Video / Audio kaynağı
# ============================================================

# Audio: Silero VAD 16kHz mono ister
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1

# Audio chunk'ları kaç ms'lik parçalarla okuyalım
# 100ms küçük yeterli; VAD bunlar üzerinde sliding window çalıştıracak
AUDIO_CHUNK_MS = 100

# Look-ahead: audio stream'i kaç saniye ileriden okuyalım?
# VAD boşluğu önceden görsün, VLM+TTS yetişsin diye.
# 2sn pragmatik — VLM ~1sn + TTS ~0.6sn = ~1.6sn, biraz pay var.
AUDIO_LOOKAHEAD_SEC = 2.0

# Video frame örnekleme: VAD bir boşluk bildirdiğinde
# o boşluğun ORTASINA denk gelen frame'i (ve etrafından 2 frame) VLM'e göndereceğiz.
# test_vllm.py'daki gibi: t-0.5, t, t+0.5
FRAME_WINDOW_OFFSETS = [-0.5, 0.0, 0.5]

# VLM'e gönderilen JPEG kalitesi ve boyut sınırı
FRAME_MAX_DIM = 512
FRAME_JPEG_QUALITY = 80

# ============================================================
# VAD (Silero) parametreleri
# ============================================================

VAD_THRESHOLD = 0.5
VAD_MIN_SILENCE_MS = 300
VAD_MIN_SPEECH_MS = 250

# Minimum kullanılabilir boşluk — bundan kısa TTS sığmaz
MIN_GAP_SEC = 1.5

# Çok uzun boşlukları parçalara böl (örn. 30sn'lik boşluğa tek betimleme yetmez)
MAX_GAP_CHUNK_SEC = 8.0

# VAD ne sıklıkla audio buffer üzerinde çalışsın?
# Audio buffer'a yeni chunk geldikçe değil, periyodik:
VAD_INTERVAL_SEC = 0.5

# VAD penceresi: son kaç saniyelik audio üzerinden çalışsın?
# Look-ahead + biraz geçmiş yeterli
VAD_BUFFER_SEC = 5.0

# ============================================================
# Sahne galerisi (HSV histogram + Bhattacharyya)
# ============================================================

# Bu eşik altındaki mesafe = "aynı sahne, betimleme tekrarlama"
# test_vllm.py'da 0.25 oldu, A-B-A-B kamera açılarında iyi çalıştı
SCENE_CHANGE_THRESHOLD = 0.25

# HSV histogram bin sayıları (test_vllm.py ile aynı)
HSV_HIST_BINS = (50, 60)

# ============================================================
# VLM (Qwen2.5-VL) parametreleri
# ============================================================

# Kelime bütçesi: boşluğa kaç kelime sığar
# TTS Türkçe ~3 kelime/saniye
WORDS_PER_SECOND = 3.0
MIN_WORD_BUDGET = 4
MAX_WORD_BUDGET = 15

# Türkçe kelime ~2 token, payı bırak
TOKENS_PER_WORD = 3

# Bağlam: son N betimleme prompt'a geri beslenir ("farklı bir şey söyle")
CONTEXT_WINDOW = 2

# VLM çağrısı timeout
VLM_TIMEOUT_SEC = 5.0
VLM_TEMPERATURE = 0.2

# Jaccard tekrar filtresi eşiği (0-1)
# İki cümlenin kelime setleri bu oranda kesişiyorsa "tekrar" say
JACCARD_REPEAT_THRESHOLD = 0.6

# ============================================================
# TTS (XTTS-v2) parametreleri
# ============================================================

TTS_TIMEOUT_SEC = 10.0
TTS_SAMPLE_RATE = 24000  # XTTS-v2 default

# ============================================================
# Mixer (ducking + crossfade)
# ============================================================

# Orijinal sesi TTS sırasında kaç dB alçaltalım
DUCKING_DB = -12.0

# Ducking giriş/çıkışta crossfade (ms)
DUCKING_FADE_MS = 150

# Mixer hangi sample rate ile çalışsın?
# Orijinal video sesi muhtemelen 44.1k/48k, TTS 24k.
# Mixer içinde 48k'ya resample edelim, çıkış 48k.
MIXER_SAMPLE_RATE = 48000

# ============================================================
# Queue boyutları (bounded — backpressure için)
# ============================================================

# Audio look-ahead chunk'ları; küçük tut, bellek için
AUDIO_QUEUE_SIZE = 50

# Frame queue: VLM yetişmezse eskiyi at, taze frame VLM'e gitsin
FRAME_QUEUE_SIZE = 4

# Gap queue: VAD'in bulduğu boşluklar VLM'i bekliyor
GAP_QUEUE_SIZE = 4

# Description queue: VLM çıktıları TTS'i bekliyor
DESC_QUEUE_SIZE = 4

# Audio queue: TTS çıktıları mixer'ı bekliyor
TTS_AUDIO_QUEUE_SIZE = 4

# ============================================================
# Stale audio: TTS bittiğinde boşluk geçtiyse atla
# ============================================================

# Bir AudioItem üretildikten N saniye sonra hâlâ çalınmadıysa, çöpe at.
# Boşluk geçti, konuşmanın üstüne binmesin.
MAX_AUDIO_AGE_SEC = 5.0

# ============================================================
# Logging
# ============================================================

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFMT = "%H:%M:%S"

# Debug: monitor worker queue uzunluklarını kaç saniyede bir bassın
MONITOR_INTERVAL_SEC = 3.0
