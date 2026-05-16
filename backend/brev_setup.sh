#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# brev_setup.sh — Brev/L40S üzerinde XTTS-v2 sunucusunu kur ve başlat
#
# Kullanım:
#   chmod +x brev_setup.sh
#   ./brev_setup.sh
#
# İlk çalıştırmada:
#   - venv oluşturur
#   - bağımlılıkları kurar
#   - XTTS-v2 modelini indirir (~2GB)
#   - Sunucuyu başlatır (0.0.0.0:8020)
#
# Sonraki çalıştırmalarda sadece sunucuyu başlatır.
# ─────────────────────────────────────────────────────────

set -euo pipefail

WORK_DIR="${HOME}/workspace/tts-server"
VENV_DIR="${WORK_DIR}/venv"
PORT=8020

echo "=== Engelsiz TV — XTTS-v2 Server Setup ==="

# ── Dizin oluştur ────────────────────────────────────────
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# ── tts_server.py'ı kopyala (eğer yoksa) ────────────────
if [ ! -f "tts_server.py" ]; then
    echo "HATA: tts_server.py bulunamadı!"
    echo "Önce tts_server.py dosyasını $WORK_DIR dizinine kopyalayın."
    echo "  scp tts_server.py <brev-user>@<brev-host>:$WORK_DIR/"
    exit 1
fi

# ── venv oluştur (ilk kez) ──────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo ">>> Python venv oluşturuluyor..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── Bağımlılıkları kur (ilk kez) ────────────────────────
if ! python -c "import TTS" 2>/dev/null; then
    echo ">>> Bağımlılıklar kuruluyor..."
    pip install --upgrade pip

    # GPU PyTorch (CUDA 11.8)
    pip install torch==2.1.1+cu118 torchaudio==2.1.1+cu118 \
        --index-url https://download.pytorch.org/whl/cu118

    # TTS + sunucu bağımlılıkları
    pip install TTS fastapi uvicorn soundfile

    echo ">>> Bağımlılıklar kuruldu."
else
    echo ">>> Bağımlılıklar zaten mevcut."
fi

# ── Sunucuyu başlat ──────────────────────────────────────
echo ">>> XTTS-v2 sunucusu başlatılıyor (port $PORT)..."
echo ">>> İlk çalıştırmada model (~2GB) indirilecek, sabırlı ol."
echo ""

python tts_server.py
