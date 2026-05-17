"""
pipeline_batch.py — Batch (offline) pipeline: video → işle → mixed WAV.

main.py'deki pipeline ile aynı worker'ları kullanır ama:
- video_source batch modda (wall-clock sleep yok, tam hız)
- Mixer streaming DEĞİL: önce tüm orijinal ses + TTS toplanır, sonra mix edilir
- Pipeline tamamlandığında ffmpeg ile orijinal video + mixed WAV → çıkış MP4

API sunucusu (api_server.py) bu modülü çağırır.
"""

import asyncio
import logging
import subprocess
import time
import wave
from pathlib import Path

import numpy as np

import config
import video_source
import vad
import vlm
import tts
from messages import AudioChunk, AudioItem, StreamEnded

log = logging.getLogger("pipeline_batch")


# ============================================================
# Audio collector — queue'dan tüm chunk'ları topla
# ============================================================

async def _collect_audio_chunks(
    audio_q: asyncio.Queue,
    stop_event: asyncio.Event,
) -> list[AudioChunk]:
    """audio_q'dan tüm chunk'ları topla, StreamEnded gelene kadar."""
    chunks = []
    while not stop_event.is_set():
        try:
            item = await asyncio.wait_for(audio_q.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        if isinstance(item, StreamEnded):
            break
        chunks.append(item)
    log.info("Audio collector: %d chunk toplandı", len(chunks))
    return chunks


async def _collect_tts_items(
    tts_q: asyncio.Queue,
    stop_event: asyncio.Event,
    job_dir: Path,
) -> list[AudioItem]:
    """tts_q'dan tüm TTS audio item'larını topla, StreamEnded gelene kadar."""
    import json
    items = []
    status_file = job_dir / "status.json"
    while not stop_event.is_set():
        try:
            item = await asyncio.wait_for(tts_q.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        if isinstance(item, StreamEnded):
            break
        items.append(item)
        
        # Write status to json for frontend
        try:
            descriptions = [
                {
                    "time": f"{int(i.video_time_start//60):02d}:{int(i.video_time_start%60):02d}", 
                    "text": i.text
                }
                for i in items
            ]
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "processing",
                    "step": "pipeline",
                    "vad": "active",
                    "vlm": "active",
                    "tts": "active",
                    "mixer": "idle",
                    "descriptions": descriptions
                }, f, ensure_ascii=False)
        except Exception as e:
            log.error("Status update error: %s", e)
            
    log.info("TTS collector: %d ses parçası toplandı", len(items))
    return items


# ============================================================
# Batch mixer — tüm ses + TTS'i birleştir
# ============================================================

def _resample(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Basit linear resample."""
    if src_sr == dst_sr:
        return pcm.astype(np.float32, copy=False)
    n_dst = int(len(pcm) * dst_sr / src_sr)
    if n_dst <= 1:
        return pcm.astype(np.float32, copy=False)
    src_idx = np.linspace(0, len(pcm) - 1, n_dst)
    return np.interp(src_idx, np.arange(len(pcm)), pcm).astype(np.float32)


def _batch_mix(
    audio_chunks: list[AudioChunk],
    tts_items: list[AudioItem],
    output_wav: Path,
):
    """Orijinal ses + TTS parçalarını offline mix et ve WAV'a yaz.

    1. Tüm audio chunk'ları birleştirip MIXER_SAMPLE_RATE'e resample et
    2. Her TTS item'ı video_time_start pozisyonuna bindir
    3. TTS sırasında orijinal sesi duck et
    4. Sonucu WAV dosyasına yaz
    """
    if not audio_chunks:
        raise RuntimeError("Orijinal ses yok — mix yapılamaz")

    sr = config.MIXER_SAMPLE_RATE
    duck_lin = float(10 ** (config.DUCKING_DB / 20.0))
    tts_gain = 10.0 ** (config.TTS_GAIN_DB / 20.0)
    fade_samples = max(1, int(config.DUCKING_FADE_MS / 1000.0 * sr))

    # 1. Orijinal sesi birleştir ve resample et
    resampled = [_resample(c.pcm, c.sample_rate, sr) for c in audio_chunks]
    original = np.concatenate(resampled)
    total_dur = len(original) / sr
    log.info("Orijinal ses: %.1fs (%d sample @ %dHz)", total_dur, len(original), sr)

    # 2. Çıkış buffer'ı (orijinalin kopyası)
    mixed = original.copy()

    # 3. Her TTS item'ı doğru pozisyona bindir
    for ti in tts_items:
        # TTS'i mixer SR'ye resample et
        tts_pcm = _resample(ti.pcm, ti.sample_rate, sr)
        tts_len = len(tts_pcm)
        tts_dur = tts_len / sr

        # Başlangıç pozisyonu (sample cinsinden)
        start_sample = int(ti.video_time_start * sr)
        end_sample = start_sample + tts_len

        if start_sample >= len(mixed):
            log.warning("TTS pozisyonu videonun dışında (t=%.2fs), atlanıyor",
                        ti.video_time_start)
            continue

        # Taşma kontrolü
        if end_sample > len(mixed):
            tts_pcm = tts_pcm[:len(mixed) - start_sample]
            tts_len = len(tts_pcm)
            end_sample = start_sample + tts_len

        # Ducking: orijinal sesi TTS bölgesinde alçalt
        # Fade-in (orijinal → duck)
        fade_in_end = min(start_sample + fade_samples, end_sample)
        for i in range(start_sample, fade_in_end):
            t = (i - start_sample) / fade_samples
            gain = 1.0 - t * (1.0 - duck_lin)
            mixed[i] = original[i] * gain

        # Duck bölgesi
        if fade_in_end < end_sample - fade_samples:
            mixed[fade_in_end:end_sample - fade_samples] = \
                original[fade_in_end:end_sample - fade_samples] * duck_lin

        # Fade-out (duck → orijinal)
        fade_out_start = max(end_sample - fade_samples, fade_in_end)
        for i in range(fade_out_start, end_sample):
            t = (i - fade_out_start) / fade_samples
            gain = duck_lin + t * (1.0 - duck_lin)
            mixed[i] = original[i] * gain

        # TTS'i üstüne ekle
        mixed[start_sample:end_sample] += tts_pcm * tts_gain

        log.info("Mix: TTS @ %.2fs (%.1fs ses) → '%s'",
                 ti.video_time_start, tts_dur, ti.text[:50])

    # 4. Soft clip
    mixed = np.clip(mixed, -1.0, 1.0)

    # 5. WAV'a yaz
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    pcm_i16 = np.clip(mixed * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(output_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm_i16.tobytes())

    log.info("Mixed WAV yazıldı: %s (%.1fs, %.1fMB)",
             output_wav, total_dur,
             output_wav.stat().st_size / (1024 * 1024))


# ============================================================
# Pipeline
# ============================================================

async def _run_pipeline_async(
    video_path: Path,
    output_wav: Path,
    stop_event: asyncio.Event,
    job_dir: Path,
):
    """Pipeline'ı batch modda çalıştır → mixed WAV üret.

    Strateji:
    1. video_source + VAD + VLM + TTS worker'ları paralel çalışır
    2. Orijinal ses (audio_rt_q) ve TTS çıktıları (tts_audio_q) ayrı toplanır
    3. Hepsi bitince offline batch mix yapılır
    """

    # Queue'lar
    frame_q     = asyncio.Queue(maxsize=config.FRAME_QUEUE_SIZE)
    audio_la_q  = asyncio.Queue(maxsize=config.AUDIO_QUEUE_SIZE)
    audio_rt_q  = asyncio.Queue(maxsize=config.AUDIO_QUEUE_SIZE)
    gap_q       = asyncio.Queue(maxsize=config.GAP_QUEUE_SIZE)
    desc_q      = asyncio.Queue(maxsize=config.DESC_QUEUE_SIZE)
    tts_audio_q = asyncio.Queue(maxsize=config.TTS_AUDIO_QUEUE_SIZE)

    # Paylaşılan state
    scene_gallery = vad.SceneGallery()
    context_ref   = vad.ContextRef()

    # video_source — batch mod (realtime=False)
    vs_tasks = await video_source.play(
        str(video_path), frame_q, audio_la_q, audio_rt_q, stop_event,
        realtime=False,
    )

    # Pipeline worker'ları (mixer HARİÇ — biz toplar modu kullanıyoruz)
    worker_tasks = [
        asyncio.create_task(
            vad.run(audio_la_q, frame_q, gap_q, scene_gallery, context_ref, stop_event,
                    realtime=False),
            name="vad",
        ),
        asyncio.create_task(
            vlm.run(gap_q, desc_q, scene_gallery, context_ref, stop_event),
            name="vlm",
        ),
        asyncio.create_task(
            tts.run(desc_q, tts_audio_q, stop_event, force_mock=False),
            name="tts",
        ),
    ]

    # Collector'lar — orijinal ses ve TTS çıktılarını topla
    audio_collector_task = asyncio.create_task(
        _collect_audio_chunks(audio_rt_q, stop_event),
        name="audio_collector",
    )
    tts_collector_task = asyncio.create_task(
        _collect_tts_items(tts_audio_q, stop_event, job_dir),
        name="tts_collector",
    )

    all_pipeline_tasks = vs_tasks + worker_tasks

    try:
        # Pipeline tamamlansın
        results = await asyncio.gather(*all_pipeline_tasks, return_exceptions=True)
        for t, r in zip(all_pipeline_tasks, results):
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                log.error("Task '%s' hata ile bitti: %s", t.get_name(), r)

        # Collector'lar tamamlansın
        audio_chunks = await audio_collector_task
        tts_items = await tts_collector_task

    finally:
        stop_event.set()
        for t in all_pipeline_tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*all_pipeline_tasks, return_exceptions=True)

    # Batch mix
    log.info("Batch mix başlıyor: %d audio chunk + %d TTS parçası",
             len(audio_chunks), len(tts_items))
             
    import json
    status_file = job_dir / "status.json"
    try:
        if status_file.exists():
            with open(status_file, "r", encoding="utf-8") as f:
                st = json.load(f)
        else:
            st = {"descriptions": []}
        st.update({"step": "mixer", "mixer": "active", "vad": "done", "vlm": "done", "tts": "done"})
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except:
        pass
        
    _batch_mix(audio_chunks, tts_items, output_wav)


def _mux_video_audio(
    original_video: Path,
    mixed_audio_wav: Path,
    output_video: Path,
) -> None:
    """ffmpeg ile orijinal videoyu + mixed audio'yu birleştir.

    Video stream kopyalanır (re-encode yok, hızlı), ses AAC'ye encode edilir.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(original_video),
        "-i", str(mixed_audio_wav),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        "-movflags", "+faststart",
        str(output_video),
    ]
    log.info("FFmpeg mux: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,  # max 5dk
    )
    if result.returncode != 0:
        log.error("FFmpeg hata:\n%s", result.stderr)
        raise RuntimeError(f"FFmpeg mux başarısız (exit={result.returncode})")
    log.info("FFmpeg mux tamamlandı: %s", output_video)


async def process_video(
    input_video: Path,
    output_dir: Path,
) -> Path:
    """Video → pipeline → mixed WAV → muxed video döner.

    Args:
        input_video: İşlenecek video dosyası
        output_dir: Geçici dosyalar ve çıktı için dizin

    Returns:
        İşlenmiş video dosyasının yolu
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    mixed_wav = output_dir / "mixed_audio.wav"
    output_video = output_dir / f"processed_{input_video.stem}.mp4"

    stop_event = asyncio.Event()

    t0 = time.time()
    log.info("Batch pipeline başlıyor: %s", input_video)

    import json
    status_file = output_dir / "status.json"
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump({
            "status": "processing",
            "step": "pipeline",
            "vad": "active",
            "vlm": "active",
            "tts": "idle",
            "mixer": "idle",
            "descriptions": []
        }, f, ensure_ascii=False)

    # Pipeline çalıştır → mixed WAV üret
    await _run_pipeline_async(input_video, mixed_wav, stop_event, output_dir)

    pipeline_dur = time.time() - t0
    log.info("Pipeline tamamlandı (%.1fs), mux başlıyor", pipeline_dur)

    # WAV dosyası üretildi mi kontrol et
    if not mixed_wav.exists() or mixed_wav.stat().st_size < 100:
        raise RuntimeError("Pipeline mixed audio üretemedi")

    # FFmpeg mux: orijinal video + mixed audio → çıkış
    _mux_video_audio(input_video, mixed_wav, output_video)

    total_dur = time.time() - t0
    log.info("Toplam işlem süresi: %.1fs → %s", total_dur, output_video)

    try:
        with open(status_file, "r", encoding="utf-8") as f:
            st = json.load(f)
        st.update({"status": "done", "step": "done", "mixer": "done"})
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except:
        pass

    return output_video