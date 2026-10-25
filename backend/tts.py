"""
tts.py — TTS worker. Piper (yerel), XTTS-v2 HTTP veya mock modu.

config.TTS_BACKEND:
- piper: süreç içinde, CPU'da çalışır. GPU/sunucu gerektirmez (varsayılan).
- xtts : config.TTS_URL'deki XTTS-v2 sunucusu. Endpoint çağrılamıyorsa mock'a düşer.
- mock : sabit ton WAV.

Mock mod: kelime sayısına göre yaklaşık doğru uzunlukta sinüs tonu üretir.
Bu sayede pipeline'ın geri kalanı (mix timing, ducking) gerçek TTS olmadan
test edilebilir.

Üretilen ses boşluktan uzunsa sığdırılır: Piper'da konuşma hızlandırılır
(config.TTS_MAX_SPEED'e kadar), yetmezse modelden daha kısa cümle istenir.
"""

import asyncio
import io
import logging
import time
import wave
from pathlib import Path

import httpx
import numpy as np
from openai import AsyncOpenAI

import config
import vlm
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
# Piper — yerel TTS
# ============================================================

VOICE_DIR = Path(__file__).parent / "voices"

_piper_voice = None


def _load_piper_voice():
    """Ses modelini yükle; diskte yoksa bir kereliğine indir (~60MB)."""
    global _piper_voice
    if _piper_voice is None:
        from piper import PiperVoice
        from piper.download_voices import download_voice

        model_path = VOICE_DIR / f"{config.TTS_VOICE}.onnx"
        if not model_path.exists():
            log.info("Piper sesi indiriliyor: %s", config.TTS_VOICE)
            VOICE_DIR.mkdir(exist_ok=True)
            download_voice(config.TTS_VOICE, VOICE_DIR)
        _piper_voice = PiperVoice.load(model_path)
        log.info("Piper sesi hazır: %s", config.TTS_VOICE)
    return _piper_voice


def _piper_tts(text: str, rate: float = 1.0) -> tuple[np.ndarray, int]:
    """Senkron (CPU'da ~100-700ms), executor'a atılacak. rate > 1 konuşmayı hızlandırır."""
    voice = _load_piper_voice()
    syn_config = None
    if rate != 1.0:
        from piper import SynthesisConfig
        syn_config = SynthesisConfig(length_scale=voice.config.length_scale / rate)
    chunks = list(voice.synthesize(text, syn_config=syn_config))
    pcm = np.concatenate([c.audio_float_array for c in chunks])
    return pcm, chunks[0].sample_rate


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
# Boşluğa sığdırma — önce hızlandır, yetmezse modele kısalttır
# ============================================================

async def _speed_to_fit(synth, text: str, pcm: np.ndarray, sr: int,
                        limit_sec: float) -> tuple[np.ndarray, int]:
    """Konuşmayı limit_sec'e sığacak kadar, en fazla TTS_MAX_SPEED kat hızlandır."""
    natural = len(pcm) / sr
    target = max(limit_sec, natural / config.TTS_MAX_SPEED)
    dur, rate = natural, 1.0
    # Piper'da süre hız ayarıyla tam orantılı kısalmıyor (duraklamalar sabit kalıyor)
    # ve aynı cümle her seferinde biraz farklı sürüyor; sığana kadar birkaç kez dene.
    for _ in range(4):
        if dur <= target:
            break
        rate = min(rate * (dur / target) ** 1.4 * 1.02, 2 * config.TTS_MAX_SPEED)
        pcm, sr = await synth(text, rate)
        dur = len(pcm) / sr
    return pcm, sr


async def _fit_to_gap(synth, llm: AsyncOpenAI, can_speed: bool, text: str,
                      pcm: np.ndarray, sr: int,
                      limit_sec: float) -> tuple[str, np.ndarray, int]:
    """Ses boşluktan uzunsa sığdır. (text, pcm, sr) döner; text kısalmış olabilir."""
    natural = len(pcm) / sr
    if natural <= limit_sec:
        return text, pcm, sr

    max_speed = config.TTS_MAX_SPEED if can_speed else 1.0

    # En yüksek hızda da sığmayacaksa önce modelden sığacak uzunlukta cümle iste
    if natural / max_speed > limit_sec:
        n_words = len(text.split())
        max_words = max(config.MIN_WORD_BUDGET,
                        int(n_words * limit_sec * max_speed / natural))
        shorter = await vlm.shorten(llm, text, max_words) if max_words < n_words else ""
        if shorter and len(shorter.split()) < n_words:
            log.info("Sığdırma: kısaltıldı (%d → %d kelime): %s",
                     n_words, len(shorter.split()), shorter)
            text = shorter
            pcm, sr = await synth(text)
            natural = len(pcm) / sr

    if max_speed > 1.0 and natural > limit_sec:
        pcm, sr = await _speed_to_fit(synth, text, pcm, sr, limit_sec)
        dur = len(pcm) / sr
        log.info("Sığdırma: %.1fs → %.1fs (%.2fx hız, boşluk %.1fs)",
                 natural, dur, natural / dur, limit_sec)
    return text, pcm, sr


# ============================================================
# TTS mode probe
# ============================================================

async def _probe_real_tts(client: httpx.AsyncClient) -> bool:
    """TTS sunucusu açık mı? Model yüklenene kadar tekrar dene.

    XTTS-v2 model yüklenmesi 30-60sn sürebilir. Bu sürede sunucu
    TCP bağlantısı kabul eder ama HTTP yanıt veremez (ReadTimeout).
    12 deneme × 5sn = ~60sn bekle.
    """
    max_retries = 12
    for attempt in range(1, max_retries + 1):
        try:
            r = await client.get(f"{config.TTS_URL}/health", timeout=5.0)
            if r.status_code == 200:
                log.info("TTS /health OK (deneme %d): %s", attempt, r.text[:100])
                return True
            log.warning("TTS /health beklenmeyen kod: %d (deneme %d)", r.status_code, attempt)
        except Exception as e:
            log.info("TTS /health bekleniyor (%d/%d): %s", attempt, max_retries, type(e).__name__)

        if attempt < max_retries:
            await asyncio.sleep(5)

    log.warning("TTS sunucusu %d denemede yanıt vermedi, MOCK moduna düşülüyor", max_retries)
    return False


# ============================================================
# Worker
# ============================================================

async def run(
    desc_queue: asyncio.Queue,
    audio_queue: asyncio.Queue,
    stop_event: asyncio.Event,
    force_mock: bool = False,
    realtime: bool = True,
):
    log.info("TTS worker başlıyor (force_mock=%s, realtime=%s)", force_mock, realtime)

    backend = "mock" if force_mock else config.TTS_BACKEND
    loop = asyncio.get_running_loop()

    async with httpx.AsyncClient() as client:
        if backend == "piper":
            try:
                await loop.run_in_executor(None, _load_piper_voice)
            except Exception as e:
                log.error("Piper yüklenemedi (%s), MOCK moduna düşülüyor", e)
                backend = "mock"
        elif backend == "xtts":
            t_probe = time.time()
            if not await _probe_real_tts(client):
                backend = "mock"
            probe_dur = time.time() - t_probe
            log.info("TTS probe %.1fs sürdü", probe_dur)

            # Probe beklerken kuyrukta biriken stale description'ları temizle (sadece realtime modda)
            if realtime and probe_dur > 2.0:
                flushed = 0
                while True:
                    try:
                        stale = desc_queue.get_nowait()
                        if isinstance(stale, StreamEnded):
                            # Sentinel'ı geri koyma — pipeline bitiyor
                            await desc_queue.put(stale)
                            break
                        flushed += 1
                    except asyncio.QueueEmpty:
                        break
                if flushed:
                    log.info("Probe sırasında biriken %d stale desc temizlendi", flushed)

        log.info("TTS modu: %s", backend)

        llm = AsyncOpenAI(base_url=config.VLLM_URL, api_key=config.VLLM_API_KEY)

        async def synth(text: str, rate: float = 1.0) -> tuple[np.ndarray, int]:
            if backend == "piper":
                return await loop.run_in_executor(None, _piper_tts, text, rate)
            if backend == "xtts":
                return await _real_tts(client, text)
            # Mock executor'a atmaya gerek yok, hızlı CPU işi
            return _mock_tts(text, config.TTS_SAMPLE_RATE), config.TTS_SAMPLE_RATE

        while not stop_event.is_set():
            try:
                item = await asyncio.wait_for(desc_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if isinstance(item, StreamEnded):
                log.info("TTS worker: desc stream bitti")
                break

            desc: DescriptionItem = item

            # Stale kontrolü (sadece realtime modda)
            if realtime:
                age = time.time() - desc.wall_time
                if age > config.MAX_AUDIO_AGE_SEC:
                    log.warning("Stale desc atlandı (%.1fs): %s", age, desc.text[:50])
                    continue

            t0 = time.time()
            try:
                text = desc.text
                pcm, sr = await synth(text)
                if backend != "mock":
                    text, pcm, sr = await _fit_to_gap(
                        synth, llm, backend == "piper", text, pcm, sr,
                        desc.available_seconds)

                latency_ms = (time.time() - t0) * 1000
                duration = len(pcm) / sr
                log.info("TTS (%.0fms, %.1fs ses): %s",
                         latency_ms, duration, text[:60])

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
                    text=text,
                    pcm=pcm,
                    sample_rate=sr,
                    wall_time=time.time(),
                ))

            except Exception as e:
                log.error("TTS hata: %s", e)

    await audio_queue.put(StreamEnded(reason="tts_eof"))
    log.info("TTS worker durdu")