"""
vad.py — Silero VAD + sahne galerisi + GapItem üretici.

Mantık:
1. audio_q_lookahead'den (2sn ileride) AudioChunk'ları alıp ring buffer'da tut
2. Periyodik olarak (VAD_INTERVAL_SEC) son VAD_BUFFER_SEC'lik audio üzerinde
   Silero VAD çalıştır → konuşma segmentleri
3. Konuşma segmentlerini buffer'ın kendi zaman penceresine göre boşluklara çevir
4. Yeni bulunan, yeterince uzun boşluk için frame penceresi topla
5. Sahne galerisinde aramada eşleşme yoksa GapItem üret

Frame penceresi: vad kendi içinde son ~5sn'lik frame'leri saklar (dict[video_time→frame]).
Boşluk merkezi belli olunca o civardan FRAME_WINDOW_OFFSETS'e göre 3 frame seçer.

Önemli: VAD audio'yu look-ahead ile aldığı için, frame'lerin "şimdiki an"da olması
TAMAM — VAD'in boşluk dediği video_time aslında 2sn sonraki an. O ana ait frame
henüz frame_queue'ya gelmemiş olabilir. Çözüm: vad frame'leri biriktirir ve
yeterince frame gelene kadar GapItem'ı tutar. Bu basit yaklaşım hackathon için yeter.

Daha akıllı yol: gap'i hemen üret, frame'leri ileride al — ama bu vlm worker'ı
karmaşıklaştırır. Hackathon için kabul edilebilir gecikme.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Optional

import cv2
import numpy as np

import config
from messages import FrameItem, AudioChunk, GapItem, StreamEnded

log = logging.getLogger("vad")


# ============================================================
# Sahne galerisi (HSV histogram + Bhattacharyya mesafesi)
# ============================================================

def _compute_hsv_histogram(frame_bgr: np.ndarray) -> np.ndarray:
    """HSV histogram — test_vllm.py ile birebir aynı."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    bins = config.HSV_HIST_BINS
    hist = cv2.calcHist([hsv], [0, 1], None, list(bins), [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist


class SceneGallery:
    """Bilinen sahneler. Yeni frame'i karşılaştırır, eşleşme varsa indeks döner.

    Galeriye ekleme VLM çağrısı BAŞARILI olduktan sonra yapılır
    (vlm worker tarafından). Bu yüzden burada sadece "eşleşme var mı" kontrolü.
    """
    def __init__(self):
        # list[tuple[hist, description_text]]
        self._items: list[tuple[np.ndarray, str]] = []
        self._lock = asyncio.Lock()

    async def match(self, frame_bgr: np.ndarray) -> tuple[Optional[int], float, Optional[str]]:
        """Bu frame galeride var mı? (index, min_dist, known_text) döner."""
        hist = _compute_hsv_histogram(frame_bgr)
        async with self._lock:
            if not self._items:
                return None, float("inf"), None
            distances = [
                cv2.compareHist(known, hist, cv2.HISTCMP_BHATTACHARYYA)
                for known, _ in self._items
            ]
            min_idx = int(np.argmin(distances))
            min_dist = float(distances[min_idx])
            if min_dist < config.SCENE_CHANGE_THRESHOLD:
                return min_idx, min_dist, self._items[min_idx][1]
            return None, min_dist, None

    async def add(self, frame_bgr: np.ndarray, text: str):
        hist = _compute_hsv_histogram(frame_bgr)
        async with self._lock:
            self._items.append((hist, text))
            log.info("Sahne galerisine eklendi (#%d): %s", len(self._items) - 1, text[:50])

    async def size(self) -> int:
        async with self._lock:
            return len(self._items)


# ============================================================
# Context paylaşımı (vad ↔ vlm)
# ============================================================

class ContextRef:
    """Son N betimleme. vlm worker yazar, vad worker GapItem üretirken snapshot alır.

    Neden ayrı sınıf: vad ve vlm arasında shared state. Önceki tasarım
    fonksiyon attribute (vad.run.context_ref) idi — fragile. Bu açık sözleşme.
    """
    def __init__(self):
        self._items: deque[str] = deque(maxlen=config.CONTEXT_WINDOW)
        self._lock = asyncio.Lock()

    async def append(self, text: str):
        async with self._lock:
            # Aynı metin üst üste eklenmesin
            if not self._items or self._items[-1] != text:
                self._items.append(text)

    async def snapshot(self) -> list[str]:
        async with self._lock:
            return list(self._items)


# ============================================================
# Silero VAD wrapper (lazy load)
# ============================================================

_vad_model = None

def _load_vad_model():
    global _vad_model
    if _vad_model is None:
        from silero_vad import load_silero_vad
        log.info("Silero VAD yükleniyor...")
        _vad_model = load_silero_vad()
        log.info("Silero VAD hazır")
    return _vad_model


def _detect_speech_segments(audio_np: np.ndarray, sample_rate: int) -> list[tuple[float, float]]:
    """Audio array üzerinde Silero VAD çalıştır, konuşma segmentleri döner.
    Senkron (CPU'da hızlı), executor'a atılacak.
    """
    import torch
    from silero_vad import get_speech_timestamps

    model = _load_vad_model()
    audio_t = torch.from_numpy(audio_np)
    ts = get_speech_timestamps(
        audio_t, model,
        sampling_rate=sample_rate,
        return_seconds=True,
        threshold=config.VAD_THRESHOLD,
        min_silence_duration_ms=config.VAD_MIN_SILENCE_MS,
        min_speech_duration_ms=config.VAD_MIN_SPEECH_MS,
    )
    return [(t["start"], t["end"]) for t in ts]


# ============================================================
# Frame history: son ~5sn frame'leri tut
# ============================================================

class FrameHistory:
    """Frame'leri video_time'a göre sakla. Boşluk merkezi belli olunca
    o noktanın çevresinden frame penceresi çıkar.
    """
    def __init__(self, max_age_sec: float = 6.0):
        self.max_age_sec = max_age_sec
        # deque[(video_time, frame)] — sıralı (eklenme sırası ≈ video sırası)
        self._frames: deque[tuple[float, np.ndarray]] = deque()
        self._lock = asyncio.Lock()
        self._latest_video_time = 0.0

    async def add(self, item: FrameItem):
        async with self._lock:
            self._frames.append((item.video_time, item.image))
            self._latest_video_time = item.video_time
            # Eski frame'leri at
            cutoff = item.video_time - self.max_age_sec
            while self._frames and self._frames[0][0] < cutoff:
                self._frames.popleft()

    async def latest_video_time(self) -> float:
        async with self._lock:
            return self._latest_video_time

    async def get_window(self, center_video_time: float, offsets: list[float]) -> list[np.ndarray]:
        """Verilen merkez zamanın çevresinden en yakın frame'leri seç.
        offsets'in her biri için, target = center + offset, en yakın frame'i bul.
        """
        async with self._lock:
            if not self._frames:
                return []
            frames_list = list(self._frames)
            result = []
            for off in offsets:
                target = center_video_time + off
                # En yakın frame
                closest = min(frames_list, key=lambda x: abs(x[0] - target))
                result.append(closest[1])
            return result


# ============================================================
# Audio ring buffer
# ============================================================

class AudioRingBuffer:
    """Son N saniyelik audio'yu birleşik bir array olarak tut.
    VAD bunun üzerinde sliding window çalıştırır.
    """
    def __init__(self, max_sec: float, sample_rate: int):
        self.max_samples = int(max_sec * sample_rate)
        self.sample_rate = sample_rate
        self._buf = np.zeros(0, dtype=np.float32)
        self._start_video_time = 0.0  # buffer'ın başındaki sample'ın video_time'ı
        self._lock = asyncio.Lock()

    async def append(self, chunk: AudioChunk):
        async with self._lock:
            self._buf = np.concatenate([self._buf, chunk.pcm])
            if len(self._buf) > self.max_samples:
                # Eski kısmı at
                drop = len(self._buf) - self.max_samples
                self._buf = self._buf[drop:]
                self._start_video_time += drop / self.sample_rate
            # Eğer ilk chunk ise start_video_time'ı set et
            if self._start_video_time == 0.0 and len(self._buf) == len(chunk.pcm):
                self._start_video_time = chunk.video_time_start

    async def snapshot(self) -> tuple[np.ndarray, float, float]:
        """(audio_array, video_time_start, video_time_end) döner."""
        async with self._lock:
            arr = self._buf.copy()
            start = self._start_video_time
            end = start + len(arr) / self.sample_rate
            return arr, start, end


# ============================================================
# Boşluk planlayıcı
# ============================================================

def _gaps_from_speech(speech: list[tuple[float, float]],
                      window_start: float, window_end: float,
                      min_gap: float) -> list[tuple[float, float]]:
    """Konuşma segmentlerinin tersini al = boşluklar. Buffer penceresine göre."""
    gaps = []
    cursor = window_start
    for s, e in speech:
        if s - cursor >= min_gap:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if window_end - cursor >= min_gap:
        gaps.append((cursor, window_end))
    return gaps


def _split_long_gap(start: float, end: float, max_chunk: float) -> list[tuple[float, float]]:
    """Uzun boşluğu chunk'lara böl."""
    duration = end - start
    if duration <= max_chunk:
        return [(start, end)]
    n = int(np.ceil(duration / max_chunk))
    step = duration / n
    return [(start + step * i, start + step * (i + 1)) for i in range(n)]


# ============================================================
# Worker
# ============================================================

async def run(
    audio_q_lookahead: asyncio.Queue,
    frame_queue: asyncio.Queue,
    gap_queue: asyncio.Queue,
    scene_gallery: SceneGallery,
    context_ref: ContextRef,
    stop_event: asyncio.Event,
):
    """VAD worker — audio lookahead'i tüketir, boşlukları gap_queue'ya basar."""
    log.info("VAD worker başlıyor (lookahead=%.1fs)", config.AUDIO_LOOKAHEAD_SEC)

    audio_buf = AudioRingBuffer(config.VAD_BUFFER_SEC, config.AUDIO_SAMPLE_RATE)
    frame_hist = FrameHistory(max_age_sec=config.VAD_BUFFER_SEC + 2.0)

    # Daha önce GapItem üretilmiş boşlukları tekrar üretme
    # (audio buffer kayarken aynı boşluğu yeniden görebiliriz)
    emitted_gaps: list[tuple[float, float]] = []

    audio_done = False
    frame_done = False
    last_vad_at = 0.0
    loop = asyncio.get_running_loop()

    # İlk betimleme bayrağı — galeri boş olduğu sürece is_first=True
    while not stop_event.is_set():
        # === Audio queue'dan al ===
        try:
            audio_item = await asyncio.wait_for(audio_q_lookahead.get(), timeout=0.1)
            if isinstance(audio_item, StreamEnded):
                audio_done = True
                log.info("Audio lookahead bitti")
            else:
                await audio_buf.append(audio_item)
        except asyncio.TimeoutError:
            pass

        # === Frame queue'dan boşaltabildiğin kadar al ===
        while True:
            try:
                f_item = frame_queue.get_nowait()
                if isinstance(f_item, StreamEnded):
                    frame_done = True
                    log.info("Frame stream bitti")
                else:
                    await frame_hist.add(f_item)
            except asyncio.QueueEmpty:
                break

        # === Periyodik VAD ===
        now = time.time()
        if now - last_vad_at >= config.VAD_INTERVAL_SEC:
            last_vad_at = now
            audio_arr, win_start, win_end = await audio_buf.snapshot()
            if len(audio_arr) >= config.AUDIO_SAMPLE_RATE * 1.0:
                # En az 1sn audio biriktiyse VAD çalıştır
                try:
                    speech = await loop.run_in_executor(
                        None, _detect_speech_segments, audio_arr, config.AUDIO_SAMPLE_RATE,
                    )
                    # Mutlak (video) zamana çevir
                    speech_abs = [(s + win_start, e + win_start) for s, e in speech]
                    raw_gaps = _gaps_from_speech(speech_abs, win_start, win_end,
                                                  config.MIN_GAP_SEC)
                    # Uzun boşlukları parçala
                    all_gaps = []
                    for gs, ge in raw_gaps:
                        all_gaps.extend(_split_long_gap(gs, ge, config.MAX_GAP_CHUNK_SEC))

                    log.debug("VAD tarama: pencere=[%.2f-%.2f], %d konuşma, %d ham boşluk, %d chunk",
                              win_start, win_end, len(speech), len(raw_gaps), len(all_gaps))

                    # Sondan bir tane bırak — çünkü buffer kayar ve şu an bitiyor
                    # gibi görünen boşluk aslında devam ediyor olabilir.
                    # Buffer'ın son 0.5sn'sinde MERKEZİ olan boşlukları erteleyelim.
                    # (chunk sonu değil — chunk uzun boşluğun parçası olabilir, sonu hep
                    #  pencere sınırına yakındır; biz merkezin hizalı olmasını isteriz.)
                    safe_cutoff = win_end - 0.5
                    candidate_gaps = [
                        (gs, ge) for gs, ge in all_gaps if (gs + ge) / 2 <= safe_cutoff
                    ]

                    # Daha önce emit edilmiş mi?
                    for gs, ge in candidate_gaps:
                        already = any(
                            abs(gs - eg[0]) < 0.3 and abs(ge - eg[1]) < 0.3
                            for eg in emitted_gaps
                        )
                        if already:
                            continue

                        center = (gs + ge) / 2
                        available = ge - gs

                        # Frame penceresi yeterli mi?
                        latest_video_time = await frame_hist.latest_video_time()
                        # center, latest_video_time'dan max FRAME_WINDOW_OFFSETS kadar geride olabilir
                        max_offset = max(config.FRAME_WINDOW_OFFSETS)
                        if center + max_offset > latest_video_time:
                            # Frame'ler henüz yetişmedi, sonra denenecek
                            log.debug("Frame'ler yetişmedi (center=%.2f, latest=%.2f), erteleniyor",
                                      center, latest_video_time)
                            continue

                        frames = await frame_hist.get_window(center, config.FRAME_WINDOW_OFFSETS)
                        if not frames:
                            continue

                        # Sahne galerisi kontrolü (orta frame ile)
                        keyframe = frames[len(frames) // 2]
                        matched_idx, dist, known_text = await scene_gallery.match(keyframe)
                        if matched_idx is not None:
                            log.info("Bilinen sahne #%d (Δ=%.2f) @ %.2fs → SUS: '%s'",
                                     matched_idx, dist, center, known_text[:40])
                            emitted_gaps.append((gs, ge))
                            # Bağlama ekle (akış için)
                            await context_ref.append(known_text)
                            continue

                        # Context snapshot
                        ctx_snapshot = await context_ref.snapshot()
                        is_first = (await scene_gallery.size()) == 0

                        gap_item = GapItem(
                            video_time_start=gs,
                            video_time_end=ge,
                            video_time_center=center,
                            available_seconds=available,
                            frames=frames,
                            is_first=is_first,
                            context=ctx_snapshot,
                            wall_time=time.time(),
                        )

                        # Backpressure: gap_queue full ise eskiyi at
                        if gap_queue.full():
                            try:
                                dropped = gap_queue.get_nowait()
                                log.warning("Gap queue full, eski GapItem atıldı: t=%.2f",
                                            getattr(dropped, "video_time_center", 0))
                            except asyncio.QueueEmpty:
                                pass

                        await gap_queue.put(gap_item)
                        emitted_gaps.append((gs, ge))
                        log.info("Boşluk → VLM: [%.2f-%.2f] (%.1fs), Δ_min=%.2f, first=%s",
                                 gs, ge, available, dist, is_first)

                    # emitted_gaps'i temizle — buffer dışında kalanları at
                    emitted_gaps = [
                        (gs, ge) for gs, ge in emitted_gaps if ge > win_start
                    ]

                except Exception as e:
                    log.error("VAD hata: %s", e)

        # === Çıkış koşulu ===
        if audio_done and frame_done:
            log.info("VAD worker: tüm kaynaklar bitti, çıkıyor")
            break

    await gap_queue.put(StreamEnded(reason="vad_eof"))
    log.info("VAD worker durdu")
