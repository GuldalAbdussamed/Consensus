"""
Smoke test: VLM ve gerçek TTS olmadan tüm pipeline'ı çalıştır.

VLM çağrısını monkey-patch ile mock'la. Mock TTS zaten var (tts.py'da auto-probe).
Output WAV'a yazılır (sounddevice yoksa).
"""
import asyncio
import logging
import sys

# vlm'i import etmeden önce monkey-patch
import vlm
from messages import GapItem


async def _mock_call_vlm(client, gap: GapItem):
    """Frame sayısı + boşluk uzunluğuna bağlı sahte cevap döner."""
    import time, random
    await asyncio.sleep(0.3)  # gerçek VLM ~400ms simüle et
    n_frames = len(gap.frames)
    samples = [
        "Üç kişi masanın etrafında oturuyor.",
        "Kadın elindeki kağıdı inceliyor.",
        "Genç adam dışarı çıkıyor.",
        "Stüdyoda iki sunucu var.",
    ]
    text = random.choice(samples)
    return text, text, 320.0  # cleaned, raw, latency_ms


vlm._call_vlm = _mock_call_vlm


# Şimdi main'i çalıştır
import main as main_mod

# argv'yi ayarla
sys.argv = [
    "smoke",
    "--video", "samples/test10s.mp4",
    "--mock-tts",
    "--output-wav", "samples/test10s_mixed.wav",
    "--debug",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

main_mod.main()
