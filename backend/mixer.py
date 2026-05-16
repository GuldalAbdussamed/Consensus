"""
mixer.py — Orijinal video sesini ve TTS sesini mix et, hoparlöre yaz.

Mantık:
- Orijinal ses sürekli akıyor (audio_q_realtime'dan)
- TTS sesi event olarak geliyor (tts_audio_queue'dan, AudioItem)
- Bir AudioItem geldiğinde:
  1. video_time_start gelene kadar bekle (wall-clock'a göre)
  2. Orijinal sesi DUCKING_DB kadar alçalt (fade ile)
  3. TTS'i üstüne ekle
  4. TTS bitince orijinali normale döndür (fade ile)

Sounddevice ile output stream — non-blocking callback değil, async push.
Hackathon için sounddevice.OutputStream + write yeterli.

Eğer ses cihazı yoksa (CI/headless), sessizce WAV'a yazma fallback'i.

Bütün sample rate çevrimleri MIXER_SAMPLE_RATE'e (48k) yapılır.
"""

import asyncio
import logging
import time
import wave
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

import config
from messages import AudioChunk, AudioItem, StreamEnded

log = logging.getLogger("mixer")


# ============================================================
# Resample (linear, hafif)
# ============================================================

def _resample(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Basit linear resample. Hackathon için yeterli, kaliteli istiyorsan
    librosa.resample veya soxr."""
    if src_sr == dst_sr:
        return pcm.astype(np.float32, copy=False)
    n_dst = int(len(pcm) * dst_sr / src_sr)
    if n_dst <= 1:
        return pcm.astype(np.float32, copy=False)
    src_idx = np.linspace(0, len(pcm) - 1, n_dst)
    out = np.interp(src_idx, np.arange(len(pcm)), pcm).astype(np.float32)
    return out


# ============================================================
# Output sink (sounddevice veya WAV dosyası fallback)
# ============================================================

class OutputSink:
    """Sounddevice OutputStream wrapper. Cihaz yoksa WAV'a yazar."""

    def __init__(self, sample_rate: int, fallback_wav: Optional[str] = None,
                 force_wav: bool = False):
        self.sample_rate = sample_rate
        self._stream = None
        self._wav_writer = None
        self._wav_path = fallback_wav
        self._use_sd = False

        if force_wav and fallback_wav:
            # Batch mod — direkt WAV'a yaz, sounddevice açma
            Path(fallback_wav).parent.mkdir(parents=True, exist_ok=True)
            self._wav_writer = wave.open(fallback_wav, "wb")
            self._wav_writer.setnchannels(1)
            self._wav_writer.setsampwidth(2)
            self._wav_writer.setframerate(sample_rate)
            log.info("Output: WAV dosyası (%.0fHz) → %s", sample_rate, fallback_wav)
            return

        try:
            import sounddevice as sd  # type: ignore
            self._sd = sd
            self._stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=0,
            )
            self._stream.start()
            self._use_sd = True
            log.info("Output: sounddevice (%.0fHz)", sample_rate)
        except Exception as e:
            log.warning("sounddevice yok/açılamadı (%s), WAV'a yazılacak: %s",
                        e, fallback_wav)
            if fallback_wav:
                Path(fallback_wav).parent.mkdir(parents=True, exist_ok=True)
                self._wav_writer = wave.open(fallback_wav, "wb")
                self._wav_writer.setnchannels(1)
                self._wav_writer.setsampwidth(2)
                self._wav_writer.setframerate(sample_rate)

    def write(self, pcm: np.ndarray):
        """Bloklamasız varsayalım (mixer worker zaten sıralı çalışıyor)."""
        if self._use_sd:
            self._stream.write(pcm)
        elif self._wav_writer:
            pcm_i16 = np.clip(pcm * 32767, -32768, 32767).astype(np.int16)
            self._wav_writer.writeframes(pcm_i16.tobytes())

    def close(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        if self._wav_writer:
            try:
                self._wav_writer.close()
                log.info("Çıktı WAV yazıldı: %s", self._wav_path)
            except Exception:
                pass


# ============================================================
# Ducking envelope
# ============================================================

class DuckingEnvelope:
    """Aktif TTS varken orijinal sesin gain'ini düşürür, biterken normale döner.

    Kullanım:
        env.start_duck(tts_duration_sec)  # TTS başladığında
        gain = env.gain_for(n_samples)    # mixer çağrısında, bu kadar sample için
                                          # envelope değerleri döner
    """

    def __init__(self, sample_rate: int, duck_db: float, fade_ms: float):
        self.sr = sample_rate
        self.duck_lin = float(10 ** (duck_db / 20.0))  # örn -12dB ≈ 0.251
        self.fade_samples = max(1, int(fade_ms / 1000.0 * sample_rate))

        # Durum: target_gain (her sample'da exponential approach veya linear)
        self._current = 1.0
        self._target = 1.0
        # Active TTS bitiş zamanı (wall) — bunu geçince target=1.0
        self._tts_end_wall: Optional[float] = None

    def start_duck(self, tts_duration_sec: float):
        self._target = self.duck_lin
        self._tts_end_wall = time.time() + tts_duration_sec

    def gain_for(self, n_samples: int) -> np.ndarray:
        """n_samples uzunluğunda gain dizisi üret, current → target arası linear fade."""
        # TTS bittiyse target'ı 1.0'a çek
        if self._tts_end_wall and time.time() >= self._tts_end_wall:
            self._target = 1.0
            self._tts_end_wall = None

        if self._current == self._target:
            return np.full(n_samples, self._current, dtype=np.float32)

        # Linear fade fade_samples üzerinden
        step = (self._target - self._current) / self.fade_samples
        out = np.zeros(n_samples, dtype=np.float32)
        cur = self._current
        for i in range(n_samples):
            out[i] = cur
            cur += step
            if (step > 0 and cur >= self._target) or (step < 0 and cur <= self._target):
                cur = self._target
                out[i:] = cur
                break
        self._current = cur
        return out


# ============================================================
# Mixer worker
# ============================================================

async def run(
    audio_q_realtime: asyncio.Queue,
    tts_audio_queue: asyncio.Queue,
    stop_event: asyncio.Event,
    fallback_wav: Optional[str] = None,
    realtime: bool = True,
):
    log.info("Mixer başlıyor (sr=%dHz)", config.MIXER_SAMPLE_RATE)

    sink = OutputSink(config.MIXER_SAMPLE_RATE, fallback_wav,
                       force_wav=not realtime)
    envelope = DuckingEnvelope(
        config.MIXER_SAMPLE_RATE,
        config.DUCKING_DB,
        config.DUCKING_FADE_MS,
    )

    # Bekleyen TTS'ler (henüz video_time_start'a ulaşmamış)
    # Liste, sırayla işlenir — TTS hazır olduğunda en eskisi geçerli olur
    pending_tts: deque[AudioItem] = deque()

    # Şu an aktif çalan TTS'in kalan PCM'i
    active_tts_pcm: Optional[np.ndarray] = None
    active_tts_idx = 0

    # Pipeline başlangıç wall_time'ı — video_source başlatıldığında set edilmeli
    # Şimdilik mixer'a ilk audio chunk geldiğinde set ediyoruz
    start_wall: Optional[float] = None

    audio_done = False
    tts_done = False

    try:
        while not stop_event.is_set():
            # === Yeni TTS geldi mi (non-blocking) ===
            while True:
                try:
                    tts_item = tts_audio_queue.get_nowait()
                    if isinstance(tts_item, StreamEnded):
                        tts_done = True
                        log.info("Mixer: TTS stream bitti")
                    else:
                        ti: AudioItem = tts_item
                        age = time.time() - ti.wall_time
                        if age > config.MAX_AUDIO_AGE_SEC:
                            log.warning("Mixer: stale TTS atlandı (%.1fs): %s",
                                        age, ti.text[:40])
                        else:
                            # Mixer SR'ye resample
                            pcm_mix = _resample(ti.pcm, ti.sample_rate, config.MIXER_SAMPLE_RATE)
                            ti_mix = AudioItem(
                                video_time_start=ti.video_time_start,
                                text=ti.text,
                                pcm=pcm_mix,
                                sample_rate=config.MIXER_SAMPLE_RATE,
                                wall_time=ti.wall_time,
                            )
                            pending_tts.append(ti_mix)
                            log.info("Mixer: TTS sıraya alındı, t=%.2fs (%.1fs ses)",
                                     ti_mix.video_time_start,
                                     len(pcm_mix) / config.MIXER_SAMPLE_RATE)
                except asyncio.QueueEmpty:
                    break

            # === Orijinal audio chunk al ===
            try:
                a_item = await asyncio.wait_for(audio_q_realtime.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if audio_done and tts_done and not active_tts_pcm and not pending_tts:
                    break
                continue

            if isinstance(a_item, StreamEnded):
                audio_done = True
                log.info("Mixer: orijinal audio bitti")
                if tts_done and not active_tts_pcm and not pending_tts:
                    break
                continue

            chunk: AudioChunk = a_item

            if start_wall is None:
                start_wall = chunk.wall_time

            # === Bekleyen TTS'lerden hangisi şimdi başlamalı? ===
            # video_time_start <= chunk.video_time_end olanlar başlasın
            # (sadece active yoksa, üst üste binmemesi için)
            if active_tts_pcm is None and pending_tts:
                # En eski pending'i bak
                next_tts = pending_tts[0]
                # Geç olduysa mı, tam zamanı mı?
                if chunk.video_time_end >= next_tts.video_time_start - 0.05:
                    pending_tts.popleft()
                    active_tts_pcm = next_tts.pcm
                    active_tts_idx = 0
                    duration = len(active_tts_pcm) / config.MIXER_SAMPLE_RATE
                    envelope.start_duck(duration)
                    log.info("Mixer: TTS başlıyor → '%s' (%.1fs)",
                             next_tts.text[:50], duration)

            # === Orijinal chunk'ı mixer SR'sine resample ===
            orig = _resample(chunk.pcm, chunk.sample_rate, config.MIXER_SAMPLE_RATE)
            n = len(orig)

            # === Ducking envelope uygula ===
            gain = envelope.gain_for(n)
            mixed = orig * gain

            # === Aktif TTS varsa karıştır ===
            if active_tts_pcm is not None:
                remaining = len(active_tts_pcm) - active_tts_idx
                take = min(n, remaining)
                if take > 0:
                    mixed[:take] += active_tts_pcm[active_tts_idx:active_tts_idx + take]
                    active_tts_idx += take
                if active_tts_idx >= len(active_tts_pcm):
                    active_tts_pcm = None
                    active_tts_idx = 0
                    log.info("Mixer: TTS bitti, orijinale dönülüyor")

            # === Soft clip ===
            mixed = np.clip(mixed, -1.0, 1.0)

            # === Yaz ===
            sink.write(mixed)

    finally:
        sink.close()
        log.info("Mixer durdu")