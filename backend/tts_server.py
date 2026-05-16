"""
tts_server.py — XTTS-v2 FastAPI sunucusu.

Brev / AWS L40S üzerinde çalıştırılacak.
Pipeline'daki tts.py bu sunucuya POST /synthesize yapıyor.

Kullanım:
    pip install TTS fastapi uvicorn soundfile
    python tts_server.py

Sunucu 0.0.0.0:8020'de dinler.
"""

import io
import logging
import time

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tts_server")

# ── FastAPI ──────────────────────────────────────────────
app = FastAPI(title="Engelsiz TV — XTTS-v2 Server")

# ── Model (global, startup'ta yüklenir) ─────────────────
tts_model = None
DEVICE = None
SAMPLE_RATE = 24000  # XTTS-v2 default


class SynthRequest(BaseModel):
    text: str
    language: str = "tr"
    speaker_wav: str | None = None  # ileride ses klonlama için


DEFAULT_SPEAKER = None  # startup'ta doldurulur


@app.on_event("startup")
def load_model():
    global tts_model, DEVICE, DEFAULT_SPEAKER
    log.info("XTTS-v2 modeli yükleniyor...")
    t0 = time.time()

    from TTS.api import TTS

    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(DEVICE)

    # Multi-speaker model — mevcut speaker'ları listele, ilkini default yap
    if hasattr(tts_model, "speakers") and tts_model.speakers:
        DEFAULT_SPEAKER = tts_model.speakers[0]
        log.info("Mevcut speaker'lar: %s", tts_model.speakers[:5])
        log.info("Default speaker: %s", DEFAULT_SPEAKER)
    else:
        log.warning("Speaker listesi bulunamadı!")

    elapsed = time.time() - t0
    log.info("Model yüklendi (%.1fs), device=%s", elapsed, DEVICE)


@app.get("/health")
def health():
    """Pipeline'ın probe ettiği health endpoint."""
    return {
        "status": "ok",
        "device": DEVICE,
        "model": "xtts_v2",
    }


@app.post("/synthesize")
async def synthesize(req: SynthRequest):
    """
    Metin → WAV bytes.

    Pipeline'daki tts.py tam olarak bu endpoint'e POST yapıyor:
      POST /synthesize  {"text": "...", "language": "tr"}
    Response: audio/wav binary.
    """
    t0 = time.time()

    # XTTS-v2 inference
    kwargs = {
        "text": req.text,
        "language": req.language,
    }
    if req.speaker_wav:
        kwargs["speaker_wav"] = req.speaker_wav
    elif DEFAULT_SPEAKER:
        kwargs["speaker"] = DEFAULT_SPEAKER

    wav = tts_model.tts(**kwargs)

    # numpy → WAV bytes
    buf = io.BytesIO()
    sf.write(buf, wav, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    buf.seek(0)
    wav_bytes = buf.read()

    elapsed_ms = (time.time() - t0) * 1000
    log.info(
        "Synthesize %.0fms, %d bytes, text='%s'",
        elapsed_ms,
        len(wav_bytes),
        req.text[:60],
    )

    return Response(content=wav_bytes, media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run(
        "tts_server:app",
        host="0.0.0.0",
        port=8020,
        log_level="info",
    )
