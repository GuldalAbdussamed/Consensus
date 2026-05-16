import os
import time
import glob
import subprocess
from pathlib import Path

# =========================
# AYARLAR
# =========================

# Webcam için:
VIDEO_SOURCE = "/dev/video0"

# RTSP örneği:
# VIDEO_SOURCE = "rtsp://user:pass@ip:554/stream"

# Video dosyası örneği:
# VIDEO_SOURCE = "input.mp4"

OUTPUT_DIR = "segments"
SEGMENT_TIME = 10  # saniye
MAX_SEGMENTS = 3   # sadece son 3 video saklanacak

Path(OUTPUT_DIR).mkdir(exist_ok=True)

# =========================
# FFMPEG KOMUTU
# =========================

ffmpeg_cmd = [
    "ffmpeg",
    "-y",
    "-i", VIDEO_SOURCE,
    "-c", "copy",
    "-f", "segment",
    "-segment_time", str(SEGMENT_TIME),
    "-reset_timestamps", "1",
    os.path.join(OUTPUT_DIR, "%Y%m%d_%H%M%S.mp4")
]

# =========================
# PROCESS BAŞLAT
# =========================

process = subprocess.Popen(ffmpeg_cmd)

print("Canlı segment sistemi başladı...")

try:
    while True:
        files = sorted(glob.glob(f"{OUTPUT_DIR}/*.mp4"))

        # Fazla eski videoları sil
        while len(files) > MAX_SEGMENTS:
            old_file = files.pop(0)

            try:
                os.remove(old_file)
                print(f"Silindi: {old_file}")
            except Exception as e:
                print("Silme hatası:", e)

        time.sleep(2)

except KeyboardInterrupt:
    print("Kapatılıyor...")
    process.terminate()