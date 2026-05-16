"""
scan_speakers.py — XTTS-v2'deki tüm speaker'ları Türkçe bir cümleyle dener.

Çıktı: ./speaker_samples/<speaker_name>.wav dosyaları.
Dinle, en iyiyi seç, tts_server.py'da DEFAULT_SPEAKER olarak hard-code et.

GEREKEN: tts_server.py'da /speakers (GET) ve /synthesize'da `speaker` parametresi.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

import httpx


def safe_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://ec2-3-144-104-180.us-east-2.compute.amazonaws.com:8020",
        help="TTS sunucu URL'si",
    )
    parser.add_argument(
        "--text",
        default=(
            "İki kişi mutfakta sohbet ediyor. "
            "Kadın elindeki bardağı masaya bırakıyor."
        ),
        help="Test cümlesi — gerçek betimlemeye benzeyen Türkçe seç",
    )
    parser.add_argument("--language", default="tr")
    parser.add_argument("--outdir", default="./speaker_samples")
    parser.add_argument("--limit", type=int, default=None,
                        help="Sadece ilk N speaker'ı dene (test için)")
    args = parser.parse_args()

    out = Path(args.outdir)
    out.mkdir(exist_ok=True)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Speaker listesi
        print(f"→ {args.url}/speakers")
        r = await client.get(f"{args.url}/speakers")
        r.raise_for_status()
        speakers = r.json().get("speakers", [])
        print(f"  {len(speakers)} speaker bulundu")

        if args.limit:
            speakers = speakers[: args.limit]
            print(f"  --limit ile {len(speakers)} ile sınırlandı")

        # 2. Her birini dene
        failures = []
        for i, sp in enumerate(speakers, 1):
            fname = out / f"{i:03d}_{safe_name(sp)}.wav"
            if fname.exists():
                print(f"  [{i}/{len(speakers)}] {sp}  (zaten var, atlandı)")
                continue
            try:
                resp = await client.post(
                    f"{args.url}/synthesize",
                    json={
                        "text": args.text,
                        "language": args.language,
                        "speaker": sp,
                    },
                )
                resp.raise_for_status()
                fname.write_bytes(resp.content)
                print(f"  [{i}/{len(speakers)}] {sp}  → {fname.name} ({len(resp.content)//1024} KB)")
            except Exception as e:
                print(f"  [{i}/{len(speakers)}] {sp}  HATA: {e}", file=sys.stderr)
                failures.append(sp)

        print(f"\nBitti. {len(speakers) - len(failures)} ses kaydı: {out}/")
        if failures:
            print(f"Hata: {len(failures)} speaker")


if __name__ == "__main__":
    asyncio.run(main())
