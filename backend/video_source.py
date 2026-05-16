"""
video_source.py — mp4'ü "canlı yayın" gibi gerçek zamanlı akıtır.

Üç akış üretir:
- frame_q          : FrameItem, wall-clock'a göre release edilir
- audio_q_lookahead: AudioChunk, gerçek zamandan AUDIO_LOOKAHEAD_SEC ileride (VAD için)
- audio_q_realtime : AudioChunk, normal hızda (mixer için)

ffmpeg ile audio'yu PCM 16kHz mono olarak decode ediyoruz.
Video frame'lerini OpenCV ile okuyoruz.

Mantık: iki ayrı cursor — biri audio için (decode ile beraber buffer'a yazılıyor),
biri video için (asyncio.sleep ile wall-clock'a senkron release ediliyor).
Audio buffer'dan iki tüketici çekiyor: lookahead (öne) ve realtime (geriden).
"""

import asyncio
import logging
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

import config
from messages import FrameItem, AudioChunk, StreamEnded

log = logging.getLogger("video_source")


# ============================================================
# Audio decoder: ffmpeg subprocess'i ile PCM stream'i
# ============================================================

async def _spawn_ffmpeg_audio(video_path: str) -> asyncio.subprocess.Process:
    """ffmpeg'i raw PCM (float32 LE) olarak stdout'a yazacak şekilde başlat."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vn",
        "-ac", str(config.AUDIO_CHANNELS),
        "-ar", str(config.AUDIO_SAMPLE_RATE),
        "-f", "f32le",
        "-loglevel", "error",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return proc


async def _audio_decoder_task(
    video_path: str,
    audio_buffer: list,           # list[AudioChunk], büyür
    audio_buffer_lock: asyncio.Lock,
    buffer_done: asyncio.Event,   # decoder bitince set
):
    """ffmpeg'den gelen PCM'i chunk'lara böl, ortak buffer'a yaz.
    İki tüketici (lookahead + realtime) bu buffer'dan okur.
    """
    proc = await _spawn_ffmpeg_audio(video_path)

    bytes_per_sample = 4  # float32
    samples_per_chunk = int(config.AUDIO_SAMPLE_RATE * config.AUDIO_CHUNK_MS / 1000)
    bytes_per_chunk = samples_per_chunk * bytes_per_sample

    chunk_idx = 0
    try:
        while True:
            data = await proc.stdout.readexactly(bytes_per_chunk)
            pcm = np.frombuffer(data, dtype=np.float32).copy()

            video_time_start = chunk_idx * config.AUDIO_CHUNK_MS / 1000.0
            video_time_end = video_time_start + len(pcm) / config.AUDIO_SAMPLE_RATE

            chunk = AudioChunk(
                wall_time=time.time(),
                video_time_start=video_time_start,
                video_time_end=video_time_end,
                pcm=pcm,
                sample_rate=config.AUDIO_SAMPLE_RATE,
            )

            async with audio_buffer_lock:
                audio_buffer.append(chunk)

            chunk_idx += 1

    except asyncio.IncompleteReadError as e:
        # ffmpeg bitti; son artık veriyi de işle
        if e.partial:
            pcm = np.frombuffer(e.partial, dtype=np.float32).copy()
            if len(pcm) > 0:
                video_time_start = chunk_idx * config.AUDIO_CHUNK_MS / 1000.0
                video_time_end = video_time_start + len(pcm) / config.AUDIO_SAMPLE_RATE
                chunk = AudioChunk(
                    wall_time=time.time(),
                    video_time_start=video_time_start,
                    video_time_end=video_time_end,
                    pcm=pcm,
                    sample_rate=config.AUDIO_SAMPLE_RATE,
                )
                async with audio_buffer_lock:
                    audio_buffer.append(chunk)
        log.info("Audio decoder bitti, %d chunk", chunk_idx)
    finally:
        try:
            await proc.wait()
        except Exception:
            pass
        buffer_done.set()


# ============================================================
# Audio publisher: buffer'dan belirli bir cursor'a göre tüket
# ============================================================

async def _audio_publisher(
    name: str,
    target_offset_sec: float,     # gerçek zamana göre OFFSET (lookahead için +, normal için 0)
    start_wall: float,
    audio_buffer: list,
    audio_buffer_lock: asyncio.Lock,
    buffer_done: asyncio.Event,
    out_queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    """Audio buffer'dan, hedef video_time'a ulaşmış chunk'ları sırayla out_queue'ya bas.

    target_offset_sec=+2.0 → lookahead, video'da 2sn ileride okur (eğer mevcutsa)
    target_offset_sec=0.0  → realtime, wall-clock'a göre tam zamanında

    Decoder buffer'a önden yazıyor (genelde decode video'dan hızlıdır), yani
    lookahead için gerçek bekleme nadirdir. Realtime için her chunk doğal olarak
    wall-clock'u bekler.
    """
    cursor_idx = 0
    while not stop_event.is_set():
        # Hedef video_time = (şimdiki wall - start) + offset
        now_wall = time.time()
        target_video_time = (now_wall - start_wall) + target_offset_sec

        # Cursor'daki chunk'a bak
        async with audio_buffer_lock:
            if cursor_idx < len(audio_buffer):
                chunk = audio_buffer[cursor_idx]
            else:
                chunk = None
                buf_size = len(audio_buffer)
            done = buffer_done.is_set()

        if chunk is None:
            if done:
                # Buffer tükendi, decoder bitti, biz de bitiyoruz
                await out_queue.put(StreamEnded(reason=f"{name}_eof"))
                log.info("%s publisher bitti (eof, %d chunk yayımlandı)", name, cursor_idx)
                return
            # Henüz veri yok, kısa bekle
            await asyncio.sleep(0.02)
            continue

        # Chunk'ın hedef zamanı geldi mi?
        # Chunk video_time_end'i target'tan küçük/eşitse "geçmişte kaldı, hemen yayımla"
        # Değilse target'a kadar bekle
        if chunk.video_time_end <= target_video_time:
            await out_queue.put(chunk)
            cursor_idx += 1
        else:
            # Bekleme süresi: chunk_end - target
            wait_sec = chunk.video_time_end - target_video_time
            # Çok kısa bekleme — chunk küçük olduğu için (100ms) max ~chunk uzunluğu kadar
            await asyncio.sleep(min(wait_sec, 0.05))


# ============================================================
# Video frame publisher: wall-clock'a göre release
# ============================================================

async def _frame_publisher(
    video_path: str,
    start_wall: float,
    frame_queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    """Video frame'lerini wall-clock'a göre release et.

    Not: VAD bir boşluk bulduğunda o anın çevresinden frame penceresi alacak.
    Bunun için son N saniyenin frame'lerini hatırlamak lazım — ama bu
    vad.py'de değil burada da olabilir. Şimdilik queue'ya basıyoruz, vad
    son k frame'i kendi içinde tutar (basitlik için).

    Aslında daha sağlam: video_source bir frame_history (dict[video_time → frame])
    tutar, vad istediğinde oradan alır. Ama bu queue ile yeterli — vad worker
    frame'leri akıttıkça kendi sliding window'unu güncelliyor.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.error("Video açılamadı: %s", video_path)
        await frame_queue.put(StreamEnded(reason="frame_open_error"))
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    log.info("Video: %.1fs, %.1f fps, %d frame", duration, fps, total_frames)

    frame_idx = 0
    try:
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                log.info("Video frame stream bitti, %d frame yayımlandı", frame_idx)
                break

            video_time = frame_idx / fps

            # Wall-clock'a senkronize et
            elapsed = time.time() - start_wall
            ahead = video_time - elapsed
            if ahead > 0.005:
                await asyncio.sleep(ahead)

            # Queue full ise eskiyi at (canlı sistem, geride kalmış frame değersiz)
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            await frame_queue.put(FrameItem(
                wall_time=time.time(),
                video_time=video_time,
                image=frame,
            ))
            frame_idx += 1
    finally:
        cap.release()
        await frame_queue.put(StreamEnded(reason="frame_eof"))


# ============================================================
# Public API
# ============================================================

async def play(
    video_path: str,
    frame_queue: asyncio.Queue,
    audio_q_lookahead: asyncio.Queue,
    audio_q_realtime: asyncio.Queue,
    stop_event: asyncio.Event,
) -> list[asyncio.Task]:
    """Video kaynağını başlat. 3 task döner — gather için.

    Tüm kuyruklar bounded olmalı (config.py'da boyutlar var).
    """
    vid_path = Path(video_path)
    if not vid_path.exists():
        raise FileNotFoundError(f"Video bulunamadı: {video_path}")

    # Ortak audio buffer (decoder yazar, iki publisher okur)
    audio_buffer: list = []
    audio_buffer_lock = asyncio.Lock()
    buffer_done = asyncio.Event()

    start_wall = time.time()
    log.info("Video başlatıldı: %s (start_wall=%.2f)", video_path, start_wall)

    tasks = [
        asyncio.create_task(_audio_decoder_task(
            str(vid_path), audio_buffer, audio_buffer_lock, buffer_done,
        ), name="audio_decoder"),
        asyncio.create_task(_audio_publisher(
            "lookahead", config.AUDIO_LOOKAHEAD_SEC, start_wall,
            audio_buffer, audio_buffer_lock, buffer_done,
            audio_q_lookahead, stop_event,
        ), name="audio_lookahead"),
        asyncio.create_task(_audio_publisher(
            "realtime", 0.0, start_wall,
            audio_buffer, audio_buffer_lock, buffer_done,
            audio_q_realtime, stop_event,
        ), name="audio_realtime"),
        asyncio.create_task(_frame_publisher(
            str(vid_path), start_wall, frame_queue, stop_event,
        ), name="frame_publisher"),
    ]
    return tasks
