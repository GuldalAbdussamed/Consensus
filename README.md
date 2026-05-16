# 👁️👂 Engelsiz TV

**Engelsiz TV**, televizyon yayınlarını ve video içeriklerini herkes için erişilebilir kılmayı amaçlayan, yapay zeka destekli bir erişilebilirlik platformudur. Görme engelliler için canlı sesli betimleme, işitme engelliler için ise eşzamanlı 3D işaret dili çevirisi sunar.

---

## 🎯 Projenin Amacı ve Vizyonu

Türkiye'de yaklaşık 700.000 görme engelli ve 3.5 milyondan fazla işitme engelli birey yaşamaktadır. Televizyon kanallarındaki ve dijital platformlardaki içeriklerin çok büyük bir kısmında sesli betimleme veya işaret dili çevirisi bulunmamaktadır.

**Engelsiz TV'nin amacı:**
Yapay zeka (VLM, TTS, STT) ve 3D teknolojilerini kullanarak, herhangi bir video yayınına anında, tamamen otonom ve gerçek zamanlı olarak erişilebilirlik katmanları (sesli betimleme ve işaret dili) eklemektir. Hedefimiz 7/24 kesintisiz, sıfır insan müdahalesi gerektiren "Herkes için televizyon" deneyimini yaratmaktır.

---

## 🚀 Özellikler

- **Gerçek Zamanlı Sesli Betimleme:** Silero VAD ile konuşma boşlukları (sessizlikler) tespit edilir ve Qwen2.5-VL-7B görsel dil modeli ile sahnedeki olaylar saniyenin altında analiz edilerek XTTS-v2 ile seslendirilir.
- **İşaret Dili Avatarı:** Konuşmaların olduğu anlarda, arka planda çalışan yapay zeka metni alır, İşaret Dili gramerine (Gloss) çevirir ve Three.js altyapılı 3D Avatar (RobotExpressive) üzerinden görsel olarak ekrana yansıtır.
- **Canlı Yayın Entegrasyonu:** HLS/RTSP gibi yayın akışlarına doğrudan bağlanıp aracı bir mikser olarak çalışabilme kapasitesi.
- **Bağlam Farkındalığı:** Sahne analizlerinde önceki betimlemeleri hafızasında tutarak gereksiz tekrarları önler.

---

## 🛠 Kullanılan Teknolojiler

### Backend (Görsel ve İşitsel AI Motoru)
- **Dil ve Ortam:** Python 3.9+, AsyncIO
- **VLM (Görsel Dil Modeli):** Qwen2.5-VL-7B-Instruct-AWQ (NVIDIA L40S GPU üzerinde vLLM ile çalışır)
- **TTS (Metinden Sese):** XTTS-v2 (Coqui) - Türkçe ve klonlama destekli
- **VAD (Ses Aktivite Tespiti):** Silero VAD
- **Görüntü İşleme:** OpenCV (Kamera açısı geçişleri ve histogram analizi için)

### Frontend (UI ve 3D Avatar)
- **Web Teknolojileri:** Vanilla HTML5, CSS3, JavaScript
- **3D Render Motoru:** Three.js (Tarayıcı tabanlı, hızlı çalışan 3D altyapı)
- **Animasyon:** GLTFLoader ve Three.js AnimationMixer

---

## ⚙️ Kurulum Talimatları

Proje iki ana modülden oluşmaktadır: AI Motoru (Backend) ve Web Arayüzü/Avatar (Frontend).

### 1. Backend Kurulumu (Python)

```bash
# Proje dizinine gidin
cd backend

# Gerekli bağımlılıkları yükleyin
pip install -r requirements.txt

# (Opsiyonel) Eğer VLLM ve XTTS sunucularını lokalde çalıştıracaksanız, 
# kendi GPU ortamınıza uygun torch ve vllm sürümlerini kurmalısınız.
```

### 2. Frontend Kurulumu (Web & 3D)

Frontend kısmı herhangi bir build aracı (npm vb.) gerektirmez. Doğrudan tarayıcıda çalışabilir.

```bash
# Frontend dizinine gidin
cd frontend

# Yerel bir Python sunucusu başlatarak anında test edebilirsiniz
python3 -m http.server 8000
```
Ardından tarayıcınızda `http://localhost:8000` adresine giderek arayüzü görebilirsiniz.

---

## 📖 Kullanım Kılavuzu

### Sesli Betimleme Pipeline'ını Başlatma (Backend)

Terminal üzerinden örnek bir video dosyasını işlemek için:

```bash
cd backend
python3 main.py --video samples/video1.mp4
```

**Parametreler:**
- `--debug`: Kuyruk (queue) ve monitör loglarını terminalde detaylı görmek için ekleyebilirsiniz.
- `--mock-tts`: TTS sunucusuna bağlanmak yerine sesi simüle etmek (offline test) için kullanabilirsiniz.
- `--output-wav <dosya.wav>`: Çıktıyı doğrudan bilgisayar hoparlörüne vermek yerine bir WAV dosyasına kaydetmek için.

### Web Arayüzünü ve Avatarı Kullanma (Frontend)
Yerel sunucuyu başlattıktan sonra `http://localhost:8000` adresinde sizi üç ana bölüm karşılar:
1. **Ana Sayfa:** Projenin vizyonu, teknoloji altyapısı ve özellikleri.
2. **Canlı Demo:** Gerçek zamanlı AI pipeline'ının (VAD -> VLM -> TTS -> Mixer) nasıl işlediğini adım adım simüle eden ve izlemenizi sağlayan gösterge paneli.
3. **İşaret Dili Çevirmeni (Avatar):** `index.html` altındaki alanda, test kutucuğuna metin (Örn: "MERHABA", "EVET", "HAYIR", "ZIPLA") yazıp "Oynat" dediğinizde 3D robot karakterinin komutlarınızı anlık olarak işaret dili animasyonuna çevirdiğini test edebilirsiniz.

---

## 👥 Ekip Üyeleri

- **Abdussamed Güldal** 
*(Not: Kendi rolünüzü ve varsa diğer takım arkadaşlarınızın isimlerini buraya ekleyebilirsiniz.)*

---

## 🏅 Paydaşlarımız ve Destekçilerimiz

Bu proje alanında lider kurumların desteğiyle hayata geçmektedir:
- **NVIDIA:** L40S GPU altyapısı ve yapay zeka donanım hızlandırması (CUDA/TensorRT) desteği.
- **YTÜ Startup House:** Kuluçka, iş geliştirme, ağ ve mentorluk desteği.
- **Türksat:** Canlı yayın altyapısı (HLS/RTSP) ve ulusal ölçekte entegrasyon danışmanlığı.
