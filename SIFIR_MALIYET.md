# Engelsiz TV — Sıfır Maliyetli Kurulum

> 12 Ekim 2026. NVIDIA/Brev kredileri bittiği için proje, GPU sunucusu olmadan tek bir
> bilgisayarda çalışacak şekilde yeniden kuruldu. Bu belge eski ve yeni yöntemi
> karşılaştırır, kurulum rehberini ve kalan işleri içerir.

## Durum

- **Çalışıyor ve test edildi (macOS, Apple M4):** VAD, Piper TTS, mix/ducking, web arayüzü
  (yükle → işle → oynat + altyazı) ve canlı mod (`main.py`).
- **Test edilmedi:** gerçek görüntü modeli ve Windows. Testler, sabit cümleler dönen sahte bir
  OpenAI-uyumlu uç noktayla yapıldı; `gemma3:4b` hiç indirilmedi. Betimleme kalitesi ve VLM
  süresi bu yüzden bilinmiyor.

İlk iş: aşağıdaki kurulumu yapıp gerçek modelle kısa bir video denemek.

## Eski ve yeni yöntem

Akış aynı: video → Silero VAD → konuşma boşluğu → 3 kare → VLM → TTS → ducking/mix.
Değişen yalnızca iki uç: görüntü modeli ve ses sentezi.

| | Eski (hackathon) | Yeni |
|---|---|---|
| Görüntü modeli | Qwen2.5-VL-7B-AWQ, vLLM, AWS/Brev L40S (46 GB VRAM) | OpenAI-uyumlu herhangi bir uç; varsayılan Ollama + `gemma3:4b` (3.35 GB), aynı bilgisayarda |
| Ses (TTS) | XTTS-v2, ayrı FastAPI sunucusu, GPU | Piper `tr_TR-dfki-medium` (63 MB), backend sürecinin içinde, CPU |
| Çalışan süreç | vLLM + `tts_server.py` + `api_server.py` | Ollama + `api_server.py` |
| Maliyet | GPU kredisi | 0 |
| VLM gecikmesi | 400–1500 ms (L40S'te ölçülmüş) | ölçülmedi |
| TTS gecikmesi | ~400–600 ms ilk ses | 100–700 ms tüm cümle (M4 CPU'da ölçüldü) |
| Konuşma hızı | ~3 kelime/sn | ~2.1 kelime/sn; kelime bütçesi buna göre düşürüldü |
| Ses kalitesi | doğal, ses klonlama mümkün | daha robotik, klonlama yok |
| Yapılandırma | shell'de `export` | `backend/.env` (hepsi opsiyonel, varsayılanlar çalışır) |
| Eşzamanlı VLM çağrısı | 5 | 1 (`VLM_MAX_CONCURRENCY`) |
| VLM zaman aşımı | 5 sn | 60 sn (`VLM_TIMEOUT_SEC`) |

Eski kurulum silinmedi: `tts_server.py`, `brev_setup.sh` duruyor ve `.env` ile geri dönülebilir
(bkz. [Eski GPU kurulumuna dönmek](#eski-gpu-kurulumuna-dönmek)).

## Düzeltilen hatalar

Bunlar krediyle ilgili değildi; `main`'de zaten vardı.

1. **Her video sonsuza kadar takılıyordu.** `Revert "black fix"` commit'i (17 Mayıs)
   `vad.py` içindeki `audio_buf = AudioRingBuffer(...)` satırını silmiş. VAD worker'ı
   `NameError` ile ölüyor, diğer worker'lar bitiş işaretini beklemeye devam ediyordu.
2. **Web demo (batch) yalnızca videonun son 5 saniyesini betimliyordu.** Batch modda ses
   kuyruğu tam hızda tükeniyor, kareler geriden geliyordu. VAD boşluğu buluyor ama o ana ait
   kare henüz gelmediği için atlıyordu; 5 sn'lik ses penceresi kaydığı için boşluk bir daha
   görülmüyordu. Artık batch modda ses, karelerin en fazla `AUDIO_LOOKAHEAD_SEC` önüne geçiyor
   (canlı moddaki ilişkinin aynısı).
3. **Tüm kareler RAM'de tutuluyordu.** Batch modda kare geçmişi 3600 sn, canlı modda 300 sn idi.
   720p bir kare ≈ 2.8 MB olduğundan bu dakikada ≈ 4 GB eder (hesap). Geçmiş artık
   `2 × VAD_BUFFER_SEC` (10 sn); boşluk merkezi zaten hep VAD penceresinin içinde.
4. **Altyazılar hep 0–5. saniyede görünüyordu.** `/status` yanıtında yalnızca `"time": "MM:SS"`
   vardı, `demo.js` ise `start_time` / `end_time` (saniye) okuyor. İkisi eklendi.

## Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `backend/config.py` | `.env` yükleme; Ollama varsayılanları; `TTS_BACKEND`, `TTS_VOICE`, `VLM_MAX_CONCURRENCY`; `VLM_TIMEOUT_SEC`, `WORDS_PER_SECOND`, `TTS_LANGUAGE`, `LOG_LEVEL` artık env'den okunuyor |
| `backend/tts.py` | Piper motoru (ses modeli ilk kullanımda `backend/voices/` altına iner); `piper` / `xtts` / `mock` seçimi |
| `backend/vad.py` | 1, 2 ve 3 numaralı düzeltmeler |
| `backend/vlm.py` | Eşzamanlılık sabiti (5) yerine `config.VLM_MAX_CONCURRENCY` |
| `backend/pipeline_batch.py` | 4 numaralı düzeltme |
| `backend/requirements.txt` | `python-dotenv`, `piper-tts` |
| `backend/.env.example` | Yeni değişkenler; eski GPU kurulumu yorum satırı olarak |
| `backend/.gitignore` | `voices/` |

## Kurulum

Gerekenler: Git, Python 3.13 (testler bununla yapıldı), FFmpeg (`PATH`'te olmalı), Ollama.
Disk: sanal ortam ≈ 1.1 GB, model 3.35 GB, ses modeli 63 MB.

### Windows (PowerShell) — test edilmedi

```powershell
winget install Git.Git
winget install Python.Python.3.13
winget install Gyan.FFmpeg
winget install Ollama.Ollama
```

`PATH` güncellensin diye terminali kapatıp yeniden aç, sonra:

```powershell
ollama pull gemma3:4b

git clone https://github.com/GuldalAbdussamed/Consensus.git
cd Consensus
git checkout yeniden

cd backend
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
$env:PYTHONUTF8 = "1"
.venv\Scripts\python api_server.py
```

`PYTHONUTF8=1`, Türkçe karakterli log satırlarının Windows konsolunda hata vermemesi içindir.
Ollama Windows'ta kurulumdan sonra arka planda kendiliğinden çalışır.

İkinci bir terminalde arayüz:

```powershell
cd Consensus\frontend
py -m http.server 3000
```

### macOS

```bash
brew install ffmpeg ollama
brew services start ollama
ollama pull gemma3:4b

git clone https://github.com/GuldalAbdussamed/Consensus.git
cd Consensus && git checkout yeniden

cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python api_server.py
```

Arayüz: `cd frontend && python3 -m http.server 3000`

### Çalıştığını doğrulamak

1. `http://localhost:11434/v1/models` adresi `gemma3:4b` içeren bir JSON dönmeli.
2. `http://localhost:8080/health` → `"status": "ok"`.
3. `http://localhost:3000/demo.html` aç, sağ üstte "Backend bağlı" yazmalı.
4. 30–60 sn'lik, içinde en az 2.5 sn'lik sessiz boşluklar olan bir video yükle.
5. Backend logunda her boşluk için şu üçlü görünmeli:
   ```
   vad: Boşluk → VLM: [6.00-10.10] (4.1s) ...
   vlm: VLM (…ms, bütçe=8): <betimleme cümlesi>
   tts: TTS (…ms, 3.4s ses): <betimleme cümlesi>
   ```
   İlk VLM çağrısı model belleğe yüklendiği için uzun sürer.

Komut satırından canlı mod: `python main.py --video video.mp4` (hoparlörden çalar).

## Farklı ya da daha büyük model

`backend/.env` dosyasına `VLLM_MODEL=<ad>` yaz, `ollama pull <ad>` çalıştır. Boyutlar
12 Ekim 2026'da Ollama kayıt defterinden okundu:

| Model | İndirme | Not |
|---|---|---|
| `gemma3:4b` | 3.35 GB | Varsayılan |
| `qwen2.5vl:3b` | 3.20 GB | |
| `qwen2.5vl:7b` | 5.97 GB | Hackathon'daki modelle aynı aile ve boyut |
| `gemma4:e2b` | 4.59 GB | |
| `gemma4:e4b` | 6.58 GB | |
| `qwen3-vl:4b` | 3.30 GB | "Thinking" modeli, şu haliyle uygun değil (aşağıya bak) |

Hiçbiri bu projede denenmedi. NVIDIA ekran kartı varsa Ollama onu kendiliğinden kullanır.

**Thinking modelleri:** `vlm.py` çıktıyı `max_tokens = kelime bütçesi × 3` (12–45 token) ile
sınırlar. Düşünme adımı olan modeller (`qwen3-vl`, `gemini-2.5-flash` vb.) bu bütçeyi
düşünmeye harcayıp boş cevap dönebilir. Düşünmesi kapalı bir model seç ya da isteğe
düşünmeyi kapatan parametreyi ekle.

**Bulut API:** `VLLM_URL`, `VLLM_MODEL`, `VLLM_API_KEY` OpenAI-uyumlu her servise
yönlendirilebilir. Ücretsiz katmanların güncel limitleri doğrulanamadı; video kareleri
üçüncü tarafa gider.

## Eski GPU kurulumuna dönmek

`backend/.env`:

```
VLLM_URL=http://<sunucu>:8000/v1
VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ
VLM_MAX_CONCURRENCY=5
VLM_TIMEOUT_SEC=5
TTS_BACKEND=xtts
TTS_URL=http://<sunucu>:8020
WORDS_PER_SECOND=3.0
```

## Testte ölçülenler

Test videosu: 30 sn, 720p, üç konuşma bölümü ve üç sessiz boşluk (3.9 / 4.8 / 5.2 sn).

| | Sonuç |
|---|---|
| Web demo (batch) | 3 boşluğa 3 betimleme (6.0 / 15.6 / 25.0. saniyeler), işlem 10 sn'nin altında |
| Boşluklardaki ses seviyesi | orijinalde sessizlik → işlenmişte ≈ −21 dB konuşma; konuşma bölümleri değişmedi |
| Altyazı | oynatıcıda doğru saniyede göründü |
| Canlı mod | 3 boşluk gerçek zamanlı betimlendi, TTS 118–225 ms |
| Tepe RAM | ≈ 1.0–1.2 GB (model hariç) |

İşlem süresi sahte VLM (≈ 160 ms) ile ölçüldü; gerçek modelde her boşluk için model süresi eklenir.

## Bilinen sorunlar ve yapılacaklar

1. **Gerçek modelle uçtan uca test.** Türkçe dil bilgisi, uydurma detaylar ve süre
   değerlendirilmeli; gerekirse model değiştirilmeli.
2. **Windows'ta doğrulama.** İlk bakılacak yerler: `ffmpeg` `PATH`'te mi, konsol kodlaması.
3. **README'nin kurulum bölümü eski.** Yukarıdaki adımlar doğrulandıktan sonra güncellenmeli.
   Oradaki EC2 test linki artık açılmıyor.
4. **Canlı modda kapanış hatası** (`mixer.py`, bu çalışmadan önce de vardı). Video, bir
   betimleme çalarken biterse `Task 'mixer' hata ile bitti: The truth value of an array...`
   loglanır; çıktı yine de yazılır. Sebep `run()` içindeki iki `not active_tts_pcm`
   kontrolü (numpy dizisi). Dikkat: yalnızca `is None` yapmak hatayı sonsuz döngüye çevirir,
   çünkü orijinal ses bitince aktif TTS'i ilerletecek chunk gelmez. Ses ve TTS akışı bitince
   döngüden koşulsuz çıkılmalı.
5. **Canlı mod yerel modelle gecikebilir.** Look-ahead 2 sn; VLM bundan uzun sürerse
   betimleme boşluğun içinde geç başlar. Web demo (batch) bundan etkilenmez.
6. **Canlı modda videonun sonundaki boşluk geç yakalanıyor.** Henüz bitmemiş bir boşluk
   ancak 5 sn'ye ulaşınca işleniyor, betimleme videonun sonuna sıkışıyor.
7. **Herkese açık demo linki yok.** Ücretsiz barındırma çözülmedi.
8. `demo.js`, backend'de olmayan `/subtitles/{job}` uç noktasını çağırıyor (404, zararsız;
   altyazılar `/status` yanıtından geliyor).
9. `piper-tts` GPL-3.0 lisanslı; proje dağıtılacaksa dikkate alınmalı.

## Denenip vazgeçilenler

- **edge-tts** (Microsoft'un gayriresmî ücretsiz ses servisi): en güncel sürümle (7.2.8) bile
  403 döndü. Koda alınmadı.
- **Hugging Face Spaces:** forum kayıtlarına göre ücretsiz hesaplarda Docker/Gradio CPU
  Space'leri kaldırılmış. Doğrulanmadı, denenmedi.
