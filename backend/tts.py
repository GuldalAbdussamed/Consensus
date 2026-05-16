"""
tts.py — TTS worker. Mock veya XTTS-v2 HTTP modu.

config.py'da TTS_URL bir HTTP endpoint. Eğer endpoint çağrılabiliyorsa
gerçek TTS, değilse mock (sabit ton WAV).

Mock mod: kelime sayısına göre yaklaşık doğru uzunlukta sinüs tonu üretir.
Bu sayede pipeline'ın geri kalanı (mix timing, ducking) gerçek TTS olmadan
test edilebilir.
"""

import asyncio
import io
import logging
import time
import wave

import httpx
import numpy as np

import config
from messages import DescriptionItem, AudioItem, StreamEnded

log = logging.getLogger("tts")


# ============================================================
# Mock TTS — kelime sayısına göre uzun sinüs tonu
# ============================================================

def _mock_tts(text: str, sample_rate: int) -> np.ndarray:
    """Konuşmadan ses üret — kelime başına ~0.33sn, ortada 440Hz ton."""
    n_words = max(1, len(text.split()))
    duration_sec = n_words / config.WORDS_PER_SECOND  # ~3 kelime/sn
    duration_sec = max(0.5, min(duration_sec, 6.0))

    n_samples = int(duration_sec * sample_rate)
    t = np.arange(n_samples) / sample_rate

    # 440Hz + 660Hz hafif harmonik, fade-in/out
    sig = 0.25 * np.sin(2 * np.pi * 440 * t) + 0.10 * np.sin(2 * np.pi * 660 * t)
    fade = int(0.05 * sample_rate)
    if fade * 2 < n_samples:
        sig[:fade] *= np.linspace(0, 1, fade)
        sig[-fade:] *= np.linspace(1, 0, fade)
    return sig.astype(np.float32)


# ============================================================
# Gerçek XTTS-v2 HTTP
# ============================================================

async def _real_tts(client: httpx.AsyncClient, text: str) -> tuple[np.ndarray, int]:
    """XTTS-v2 sunucusuna POST → WAV bytes → numpy array."""
    payload = {
        "text": text,
        "language": config.TTS_LANGUAGE,
    }
    if config.TTS_SPEAKER_WAV:
        payload["speaker_wav"] = config.TTS_SPEAKER_WAV

    resp = await client.post(
        f"{config.TTS_URL}/synthesize",
        json=payload,
        timeout=config.TTS_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    wav_bytes = resp.content

    # WAV → numpy float32 mono
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        n_channels = w.getnchannels()
        sr = w.getframerate()
        n_frames = w.getnframes()
        sampwidth = w.getsampwidth()
        raw = w.readframes(n_frames)

    # Int16 varsayımı (TTS sunucularının çoğu)
    if sampwidth == 2:
        pcm_i16 = np.frombuffer(raw, dtype=np.int16)
        pcm = pcm_i16.astype(np.float32) / 32768.0
    elif sampwidth == 4:
        pcm = np.frombuffer(raw, dtype=np.float32).copy()
    else:
        raise RuntimeError(f"Beklenmeyen WAV sampwidth: {sampwidth}")

    if n_channels == 2:
        pcm = pcm.reshape(-1, 2).mean(axis=1)

    return pcm, sr


# ============================================================
# TTS mode probe
# ============================================================

async def _probe_real_tts(client: httpx.AsyncClient) -> bool:
    """TTS sunucusu açık mı? Sadece /health probe ediyoruz.

    Synth fallback KALDIRILDI: XTTS-v2 ilk inference warmup'ı 3-5sn,
    kısa timeout false-negative üretiyordu → mock'a düşüyordu.
    """
    try:
        r = await client.get(f"{config.TTS_URL}/health", timeout=5.0)
        if r.status_code == 200:
            log.info("TTS /health OK: %s", r.text[:100])
            return True
        log.warning("TTS /health beklenmeyen kod: %d", r.status_code)
        return False
    except Exception as e:
        log.warning("TTS /health hata: %s: %s", type(e).__name__, e)
        return False


# ============================================================
# Worker
# ============================================================

async def run(
    desc_queue: asyncio.Queue,
    audio_queue: asyncio.Queue,
    stop_event: asyncio.Event,
    force_mock: bool = False,
):
    log.info("TTS worker başlıyor (force_mock=%s)", force_mock)

    async with httpx.AsyncClient() as client:
        if force_mock:
            use_real = False
        else:
            use_real = await _probe_real_tts(client)
        log.info("TTS modu: %s", "GERÇEK (XTTS-v2)" if use_real else "MOCK (sinüs)")

        loop = asyncio.get_running_loop()

        while not stop_event.is_set():
            try:
                item = await asyncio.wait_for(desc_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if isinstance(item, StreamEnded):
                log.info("TTS worker: desc stream bitti")
                break

            desc: DescriptionItem = item

            # Stale kontrolü
            age = time.time() - desc.wall_time
            if age > config.MAX_AUDIO_AGE_SEC:
                log.warning("Stale desc atlandı (%.1fs): %s", age, desc.text[:50])
                continue

            t0 = time.time()
            try:
                if use_real:
                    pcm, sr = await _real_tts(client, desc.text)
                else:
                    # Mock executor'a atmaya gerek yok, hızlı CPU işi
                    pcm = _mock_tts(desc.text, config.TTS_SAMPLE_RATE)
                    sr = config.TTS_SAMPLE_RATE

                latency_ms = (time.time() - t0) * 1000
                duration = len(pcm) / sr
                log.info("TTS (%.0fms, %.1fs ses): %s",
                         latency_ms, duration, desc.text[:60])

                # TTS bitiş kontrolü: ses boşluğa sığacak mı?
                if duration > desc.available_seconds + 0.5:
                    log.warning("Ses boşluğa sığmıyor (%.1fs > %.1fs), gene de yayımla",
                                duration, desc.available_seconds)

                if audio_queue.full():
                    try:
                        dropped = audio_queue.get_nowait()
                        log.warning("Audio queue full, eski atıldı: %s",
                                    getattr(dropped, "text", "?")[:40])
                    except asyncio.QueueEmpty:
                        pass

                await audio_queue.put(AudioItem(
                    video_time_start=desc.video_time_start,
                    text=desc.text,
                    pcm=pcm,
                    sample_rate=sr,
                    wall_time=time.time(),
                ))

            except Exception as e:
                log.error("TTS hata: %s", e)

    await audio_queue.put(StreamEnded(reason="tts_eof"))
    log.info("TTS worker durdu")
