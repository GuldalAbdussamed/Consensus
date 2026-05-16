"""
main.py — Engelsiz TV pipeline orkestrası.

Akış:
  video_source → (frame_q, audio_lookahead_q, audio_realtime_q)
       │
       ├─→ vad           (gap_q)
       │     ↓
       ├─→ vlm           (desc_q)
       │     ↓
       ├─→ tts           (tts_audio_q)
       │     ↓
       └─→ mixer         → hoparlör (veya fallback WAV)

Tüm worker'lar asyncio.gather ile paralel çalışır.
Video bittiğinde sentinel'lar (StreamEnded) zincirleme akar, hepsi graceful kapanır.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import config
import video_source
import vad
import vlm
import tts
import mixer
from messages import StreamEnded

log = logging.getLogger("main")


# ============================================================
# Monitor — debug için queue uzunlukları
# ============================================================

async def monitor(queues: dict[str, asyncio.Queue], stop_event: asyncio.Event):
    while not stop_event.is_set():
        sizes = " ".join(f"{name}={q.qsize()}" for name, q in queues.items())
        log.info("[QUEUES] %s", sizes)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.MONITOR_INTERVAL_SEC)
        except asyncio.TimeoutError:
            pass


# ============================================================
# Pipeline
# ============================================================

async def run_pipeline(args):
    # Queue'lar
    frame_q       = asyncio.Queue(maxsize=config.FRAME_QUEUE_SIZE)
    audio_la_q    = asyncio.Queue(maxsize=config.AUDIO_QUEUE_SIZE)
    audio_rt_q    = asyncio.Queue(maxsize=config.AUDIO_QUEUE_SIZE)
    gap_q         = asyncio.Queue(maxsize=config.GAP_QUEUE_SIZE)
    desc_q        = asyncio.Queue(maxsize=config.DESC_QUEUE_SIZE)
    tts_audio_q   = asyncio.Queue(maxsize=config.TTS_AUDIO_QUEUE_SIZE)

    # Paylaşılan state
    scene_gallery = vad.SceneGallery()
    context_ref   = vad.ContextRef()

    stop_event = asyncio.Event()

    # SIGINT/SIGTERM — graceful kapat
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows
            pass

    # video_source 4 alt task döner
    vs_tasks = await video_source.play(
        args.video, frame_q, audio_la_q, audio_rt_q, stop_event,
    )

    # Diğer worker'lar
    worker_tasks = [
        asyncio.create_task(
            vad.run(audio_la_q, frame_q, gap_q, scene_gallery, context_ref, stop_event),
            name="vad",
        ),
        asyncio.create_task(
            vlm.run(gap_q, desc_q, scene_gallery, context_ref, stop_event),
            name="vlm",
        ),
        asyncio.create_task(
            tts.run(desc_q, tts_audio_q, stop_event, force_mock=args.mock_tts),
            name="tts",
        ),
        asyncio.create_task(
            mixer.run(audio_rt_q, tts_audio_q, stop_event,
                      fallback_wav=args.output_wav),
            name="mixer",
        ),
    ]

    monitor_task = None
    if args.debug:
        queues = {
            "frame": frame_q,
            "audio_la": audio_la_q,
            "audio_rt": audio_rt_q,
            "gap": gap_q,
            "desc": desc_q,
            "tts": tts_audio_q,
        }
        monitor_task = asyncio.create_task(
            monitor(queues, stop_event), name="monitor",
        )

    # Monitor ana akıştan bağımsız — diğer worker'lar bittikten sonra cancel edilir
    all_tasks = vs_tasks + worker_tasks

    log.info("=" * 60)
    log.info("Pipeline başladı: %s", args.video)
    log.info("=" * 60)

    try:
        # video_source bitene + worker'lar graceful kapanana kadar bekle
        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        for t, r in zip(all_tasks, results):
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                log.error("Task '%s' hata ile bitti: %s", t.get_name(), r)
    finally:
        stop_event.set()
        for t in all_tasks:
            if not t.done():
                t.cancel()
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()
        # cancel'leri toplayalım
        await asyncio.gather(*all_tasks, return_exceptions=True)
        if monitor_task:
            await asyncio.gather(monitor_task, return_exceptions=True)

    log.info("=" * 60)
    log.info("Pipeline bitti")
    log.info("=" * 60)


# ============================================================
# Entry
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Engelsiz TV canlı pipeline")
    parser.add_argument("--video", required=True, help="Video dosyası (mp4)")
    parser.add_argument("--debug", action="store_true",
                        help="Queue monitor logları aç")
    parser.add_argument("--mock-tts", action="store_true",
                        help="Gerçek TTS sunucusunu bypass et, sinüs üret")
    parser.add_argument("--output-wav", default=None,
                        help="Ses cihazı yoksa mix sonucunu bu WAV'a yaz")
    args = parser.parse_args()

    logging.basicConfig(
        level=config.LOG_LEVEL,
        format=config.LOG_FORMAT,
        datefmt=config.LOG_DATEFMT,
    )

    if not Path(args.video).exists():
        print(f"HATA: video bulunamadı: {args.video}", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(run_pipeline(args))
    except KeyboardInterrupt:
        log.info("Kullanıcı durdurdu")


if __name__ == "__main__":
    main()
