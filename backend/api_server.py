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
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

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


async def _run_job_background(job_id: str, input_path: Path, job_dir: Path):
    """Background task to run the pipeline."""
    try:
        async with _processing_lock:
            log.info("Background pipeline başlıyor (job=%s)", job_id)
            await process_video(input_path, job_dir)
            log.info("Background pipeline tamamlandı (job=%s)", job_id)
    except Exception as e:
        log.error("Pipeline hatası (job=%s): %s", job_id, e)
        # Write error to status
        status_file = job_dir / "status.json"
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump({"status": "error", "message": str(e)}, f)
        except:
            pass


@app.post("/upload")
async def upload_endpoint(background_tasks: BackgroundTasks, video: UploadFile = File(...)):
    """Video yükle ve asenkron işlem başlat.
    
    Dönüş: {"job_id": "..."}
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

        # Initial status
        status_file = job_dir / "status.json"
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump({"status": "queued", "step": "queued"}, f)

        # Background task
        background_tasks.add_task(_run_job_background, job_id, input_path, job_dir)

        return {"job_id": job_id, "message": "Video queued for processing"}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Beklenmeyen hata (job=%s): %s", job_id, e, exc_info=True)
        raise HTTPException(500, f"Sunucu hatası: {str(e)}")


@app.get("/status/{job_id}")
async def status_endpoint(job_id: str):
    job_dir = WORK_DIR / job_id
    status_file = job_dir / "status.json"
    
    if not job_dir.exists():
        raise HTTPException(404, "Job bulunamadı")
        
    if not status_file.exists():
        return {"status": "queued", "step": "queued"}
        
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"status": "error", "message": "Statü okunamadı"}


@app.get("/download/{job_id}")
async def download_endpoint(job_id: str):
    job_dir = WORK_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job bulunamadı")
        
    # Find processed video
    output_files = list(job_dir.glob("processed_*.mp4"))
    if not output_files:
        raise HTTPException(404, "İşlenmiş video henüz hazır değil veya bulunamadı")
        
    output_path = output_files[0]
    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=output_path.name
    )


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