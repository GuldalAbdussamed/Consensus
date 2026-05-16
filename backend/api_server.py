"""
api_server.py — Engelsiz TV FastAPI sunucusu.

Endpoint'ler:
  POST /test   — Video yükle, pipeline'dan geçir, işlenmiş videoyu döndür
  GET  /health — Sunucu durumu

Kullanım:
    pip install fastapi uvicorn python-multipart
    python api_server.py
"""

import asyncio
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import config
from pipeline_batch import process_video

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=config.LOG_LEVEL,
    format=config.LOG_FORMAT,
    datefmt=config.LOG_DATEFMT,
)
log = logging.getLogger("api_server")

# ── FastAPI ──────────────────────────────────────────────
app = FastAPI(
    title="Engelsiz TV API",
    description="Video yükle → sesli betimleme ekle → işlenmiş videoyu indir",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Concurrency kontrolü ─────────────────────────────────
# GPU kaynakları sınırlı — aynı anda tek video işle
_processing_lock = asyncio.Lock()

# Geçici dosyalar için ana dizin
WORK_DIR = Path(tempfile.gettempdir()) / "engelsiz_tv_api"
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Dosya boyutu limiti (500MB)
MAX_FILE_SIZE = 500 * 1024 * 1024

# İzin verilen uzantılar
ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}


@app.get("/health")
async def health():
    """Sunucu durumu."""
    return {
        "status": "ok",
        "service": "engelsiz_tv_api",
        "vllm_url": config.VLLM_URL,
        "tts_url": config.TTS_URL,
    }


@app.post("/test")
async def test_endpoint(video: UploadFile = File(...)):
    """Video yükle → pipeline → işlenmiş video döndür.

    - multipart/form-data ile video dosyası gönderin
    - Pipeline batch modda çalışır (gerçek zamanlı değil, tam hız)
    - İşlenmiş video MP4 olarak döner
    """

    # === Validasyon ===
    if not video.filename:
        raise HTTPException(400, "Dosya adı belirtilmedi")

    ext = Path(video.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Desteklenmeyen dosya formatı: {ext}. "
            f"İzin verilenler: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # === Concurrency kontrolü ===
    if _processing_lock.locked():
        raise HTTPException(
            429,
            "Başka bir video şu an işleniyor. Lütfen bekleyin."
        )

    # === Geçici dizin oluştur ===
    job_id = str(uuid.uuid4())[:8]
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_dir / f"input{ext}"
    output_path = None

    try:
        # === Video dosyasını kaydet ===
        log.info("Video yükleniyor: %s (job=%s)", video.filename, job_id)
        total_size = 0
        with open(input_path, "wb") as f:
            while True:
                chunk = await video.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        413,
                        f"Dosya çok büyük. Maksimum: {MAX_FILE_SIZE // (1024*1024)}MB"
                    )
                f.write(chunk)

        log.info("Video kaydedildi: %.1fMB → %s", total_size / (1024*1024), input_path)

        # === Pipeline çalıştır ===
        async with _processing_lock:
            t0 = time.time()
            log.info("Pipeline başlıyor (job=%s)", job_id)

            try:
                output_path = await process_video(input_path, job_dir)
            except Exception as e:
                log.error("Pipeline hatası (job=%s): %s", job_id, e)
                raise HTTPException(500, f"Video işleme hatası: {str(e)}")

            elapsed = time.time() - t0
            log.info("Pipeline tamamlandı (job=%s, %.1fs)", job_id, elapsed)

        # === Sonucu döndür ===
        if not output_path or not output_path.exists():
            raise HTTPException(500, "İşlenmiş video oluşturulamadı")

        return FileResponse(
            path=str(output_path),
            media_type="video/mp4",
            filename=f"engelsiz_{Path(video.filename).stem}.mp4",
            headers={
                "X-Processing-Time": f"{elapsed:.1f}s",
                "X-Job-Id": job_id,
            },
        )

    except HTTPException:
        # HTTP hataları olduğu gibi yükselt
        raise
    except Exception as e:
        log.error("Beklenmeyen hata (job=%s): %s", job_id, e, exc_info=True)
        raise HTTPException(500, f"Sunucu hatası: {str(e)}")
    finally:
        # FileResponse dosyayı gönderdikten sonra temizlik yapılmalı
        # Not: FileResponse async olduğu için burada silmemeliyiz
        # Temizlik için background task kullanıyoruz
        pass


@app.on_event("shutdown")
def cleanup():
    """Sunucu kapanırken geçici dosyaları temizle."""
    if WORK_DIR.exists():
        try:
            shutil.rmtree(WORK_DIR)
            log.info("Geçici dizin temizlendi: %s", WORK_DIR)
        except Exception as e:
            log.warning("Temizlik hatası: %s", e)


if __name__ == "__main__":
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )
