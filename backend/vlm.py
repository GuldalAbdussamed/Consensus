"""
vlm.py — Qwen2.5-VL client + prompt + post-process filtreler.

Gelen GapItem'ı VLM'e gönder, temizlenmiş betimleme döndür.
test_vllm.py'daki tüm filtreler burada:
- Meta-pattern regex temizliği
- is_too_weak (sadece "konuşuyor" çıktısını ele)
- Jaccard tekrar filtresi (önceki betimlemelere göre)

VLM çağrısı başarılı olunca:
- sahne galerisine eklenir
- bağlam deque'ya eklenir (vad.run.context_ref)
- DescriptionItem desc_queue'ya konur
"""

import asyncio
import base64
import io
import logging
import re
import time

import cv2
import numpy as np
from openai import AsyncOpenAI

import config
from messages import GapItem, DescriptionItem, StreamEnded
from vad import SceneGallery, ContextRef

log = logging.getLogger("vlm")


# ============================================================
# Text filtreleri (test_vllm.py'dan birebir)
# ============================================================

META_PATTERNS = [
    r"^bu (video |kare|sahne|görüntü|an)[a-zçğıöşü]*[,:\s]+",
    r"^(görme engelli|kullanıcı|izleyici)[a-zçğıöşü\s]*için[,:\s]+",
    r"^(görüyoruz ki|görülmektedir ki|anlaşılan|bu karede|sahnede)[,:\s]+",
    r"^(şimdi|bu anda|şu anda)[,:\s]+",
]

WEAK_VERBS = {
    "konuşuyor", "konuşuyorlar", "konuştular", "konuşmuş",
    "konuşmaktalar", "konuşur",
}


def clean_description(text: str) -> str:
    """Meta-pattern temizliği + tek cümleye kes."""
    text = text.strip()
    lower = text.lower()
    for pattern in META_PATTERNS:
        m = re.match(pattern, lower)
        if m:
            text = text[m.end():].strip()
            if text:
                text = text[0].upper() + text[1:]
            break
    # İlk cümleyi al
    end = re.search(r"[.!?]", text)
    if end:
        text = text[: end.end()]
    return text.strip()


def is_too_weak(text: str) -> bool:
    """Sadece 'konuşuyor' tipi yumuşak çıktıyı ele.
    Sahnede VAD zaten 'sessiz' diyor — bu yanlış demektir.
    """
    words = re.findall(r"\w+", text.lower())
    if not words:
        return True
    for w in words:
        if w in WEAK_VERBS:
            # Başka bir fiil var mı? Yoksa zayıf.
            other_verbs = [
                x for x in words
                if x != w and (x.endswith("yor") or x.endswith("uyor")
                               or x.endswith("ıyor") or x.endswith("iyor"))
            ]
            if not other_verbs:
                return True
    return False


def is_jaccard_repeat(new_text: str, prev_texts: list[str]) -> bool:
    """Önceki betimlemelerle kelime kesişimi yüksek mi?"""
    new_tokens = set(re.findall(r"\w+", new_text.lower()))
    if not new_tokens:
        return False
    for prev in prev_texts:
        prev_tokens = set(re.findall(r"\w+", prev.lower()))
        if not prev_tokens:
            continue
        overlap = len(new_tokens & prev_tokens) / max(len(new_tokens), len(prev_tokens))
        if overlap > config.JACCARD_REPEAT_THRESHOLD:
            return True
    return False


# ============================================================
# Prompt builder (test_vllm.py'dan, sadeleştirilmiş)
# ============================================================

def _word_budget(seconds: float) -> int:
    budget = int(seconds * config.WORDS_PER_SECOND)
    return min(config.MAX_WORD_BUDGET, max(config.MIN_WORD_BUDGET, budget))


def build_prompt(gap: GapItem) -> str:
    budget = _word_budget(gap.available_seconds)

    base = (
        "Sen görme engelliler için canlı TV betimleyicisisin. "
        "Şu an arkaplanda konuşma YOK — bu yüzden 'konuşuyor' veya 'konuşuyorlar' "
        "DEMEYECEKSİN. Bu yasak.\n"
        "Sana aynı sahnenin ardışık 3 karesi veriliyor.\n\n"
        "Şu sırayla bak ve EN BELİRGİN OLANI söyle:\n"
        "  1. AKSİYON varsa: kim ne yapıyor? (yürüyor, oturuyor, bakıyor, alıyor...)\n"
        "  2. Aksiyon yoksa SAHNEYİ tanıt: nasıl bir mekan, kim var, nerede duruyor.\n"
        "  3. Belirgin GÖRSEL DETAY: kıyafet, nesne, ortam.\n\n"
        "Kurallar:\n"
        f"- TEK cümle, en fazla {budget} kelime.\n"
        "- 'Bu karede', 'görüyoruz', 'sahnede' diye BAŞLAMA.\n"
        "- Türkçe gramer doğru olsun. ÖZNE-YÜKLEM uyumlu: "
        "'kadın oturuyor' (kadını oturuyor DEĞİL), 'iki adam masada oturuyor'.\n"
        "- 'konuşuyor', 'konuşuyorlar', 'konuştular' kelimeleri YASAK.\n"
        "- Emin olmadığın detayları (isim, marka, mikrofon vb.) söyleme.\n\n"
        "İyi örnekler:\n"
        "  'Üç kişi masanın etrafında oturuyor.'\n"
        "  'Kadın elindeki kağıdı inceliyor.'\n"
        "  'Genç adam dışarı çıkıyor.'\n"
    )

    if gap.is_first:
        task = (
            "\nBU İLK BETİMLEME. Sahneyi tanıt: ne tür mekan, kaç kişi var, "
            "kim nerede, en belirgin görsel ne?\n"
            f"\nGörev: En fazla {budget} kelimeyle sahneyi tanıt."
        )
    elif gap.context:
        ctx = "\n".join(f"  - {d}" for d in gap.context)
        task = (
            f"\nSon söylediklerin:\n{ctx}\n"
            "BU KEZ FARKLI BİR ŞEY söyle. Önceden bahsetmediğin bir kişiye, "
            "nesneye, harekete veya detaya odaklan. Aynı kelimeleri tekrar kullanma.\n"
            f"\nGörev: En fazla {budget} kelimeyle sahnedeki YENİ bir şeyi söyle."
        )
    else:
        task = f"\nGörev: En fazla {budget} kelimeyle sahnedeki en önemli görseli söyle."

    return base + task


# ============================================================
# Frame → base64 JPEG
# ============================================================

def _frame_to_b64(frame_bgr: np.ndarray) -> str:
    h, w = frame_bgr.shape[:2]
    if max(h, w) > config.FRAME_MAX_DIM:
        scale = config.FRAME_MAX_DIM / max(h, w)
        frame_bgr = cv2.resize(frame_bgr, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, config.FRAME_JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encode başarısız")
    return base64.b64encode(buf.tobytes()).decode("utf-8")


# ============================================================
# VLM çağrısı
# ============================================================

async def _call_vlm(client: AsyncOpenAI, gap: GapItem) -> tuple[str, str, float]:
    """(cleaned, raw, latency_ms) döner."""
    prompt = build_prompt(gap)
    content = []
    for frame in gap.frames:
        b64 = _frame_to_b64(frame)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    content.append({"type": "text", "text": prompt})

    budget = _word_budget(gap.available_seconds)
    max_tokens = budget * config.TOKENS_PER_WORD

    t0 = time.time()
    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=config.VLLM_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=config.VLM_TEMPERATURE,
        ),
        timeout=config.VLM_TIMEOUT_SEC,
    )
    latency_ms = (time.time() - t0) * 1000
    raw = response.choices[0].message.content or ""
    cleaned = clean_description(raw)
    return cleaned, raw, latency_ms


# ============================================================
# Worker
# ============================================================

async def run(
    gap_queue: asyncio.Queue,
    desc_queue: asyncio.Queue,
    scene_gallery: SceneGallery,
    context_ref: ContextRef,
    stop_event: asyncio.Event,
):
    log.info("VLM worker başlıyor (server: %s)", config.VLLM_URL)
    client = AsyncOpenAI(base_url=config.VLLM_URL, api_key=config.VLLM_API_KEY)

    while not stop_event.is_set():
        try:
            item = await asyncio.wait_for(gap_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if isinstance(item, StreamEnded):
            log.info("VLM worker: gap stream bitti (reason=%s)", getattr(item, "reason", "unknown"))
            break

        gap: GapItem = item
        log.info("VLM: Boşluk alındı [%.2f-%.2f] (%.1fs)", 
                 gap.video_time_start, gap.video_time_end, gap.available_seconds)
        age = time.time() - gap.wall_time
        if age > config.MAX_AUDIO_AGE_SEC:
            log.warning("Stale GapItem atlandı (yaş=%.1fs, t=%.2f)", age, gap.video_time_center)
            continue

        try:
            cleaned, raw, latency = await _call_vlm(client, gap)
        except asyncio.TimeoutError:
            log.error("VLM timeout @ %.2fs", gap.video_time_center)
            continue
        except Exception as e:
            log.error("VLM hata @ %.2fs: %s", gap.video_time_center, e)
            continue

        log.info("VLM (%.0fms, bütçe=%d): %s",
                 latency, _word_budget(gap.available_seconds), cleaned)

        if not cleaned:
            log.debug("Boş çıktı, atlanıyor")
            continue

        if is_too_weak(cleaned):
            log.info("ZAYIF (elendi): %s  [ham: %s]", cleaned, raw.strip()[:80])
            continue

        if is_jaccard_repeat(cleaned, gap.context):
            log.info("JACCARD-TEKRAR (elendi): %s", cleaned)
            continue

        # Galeri ve bağlam güncelle
        keyframe = gap.frames[len(gap.frames) // 2]
        await scene_gallery.add(keyframe, cleaned)

        # Context güncelle
        await context_ref.append(cleaned)

        # desc_queue'ya at (backpressure: full ise eskiyi at)
        if desc_queue.full():
            try:
                dropped = desc_queue.get_nowait()
                log.warning("Desc queue full, eski item atıldı: %s",
                            getattr(dropped, "text", "?")[:40])
            except asyncio.QueueEmpty:
                pass

        await desc_queue.put(DescriptionItem(
            video_time_start=gap.video_time_start,
            video_time_end=gap.video_time_end,
            text=cleaned,
            available_seconds=gap.available_seconds,
            wall_time=time.time(),
        ))

    await desc_queue.put(StreamEnded(reason="vlm_eof"))
    log.info("VLM worker durdu")
