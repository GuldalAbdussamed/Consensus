# Engelsiz TV - Yapay Zeka Destekli Erişilebilirlik Platformu

Engelsiz TV, televizyon yayınlarını ve video içeriklerini herkes için erişilebilir kılmayı amaçlayan, yapay zeka tabanlı bir erişilebilirlik çözümüdür. Sistem, özellikle görme engelli bireyler için gerçek zamanlı sesli betimleme (audio description) ve işitme engelli bireyler için 3D işaret dili çevirisi sunarak medya içeriklerine erişimi kolaylaştırır.

## Proje Amacı ve Kapsamı

Dünya genelinde ve Türkiye'de milyonlarca görme ve işitme engelli birey, televizyon ve dijital içeriklerdeki görsel/işitsel bilgi eksikliği nedeniyle içerikleri tam olarak takip edememektedir. Engelsiz TV, bu boşluğu doldurmak amacıyla aşağıdaki otonom çözümleri sunar:

- **Otonom Sesli Betimleme:** Videodaki konuşma boşluklarını tespit eder, sahneyi analiz eder ve doğal bir sesle olayları açıklar.
- **Gerçek Zamanlı İşleme:** Canlı yayın akışlarına (HLS/RTSP) entegre olabilen düşük gecikmeli mimari.

## Temel Özellikler

- **Görsel Dil Modeli (VLM) Entegrasyonu:** Qwen2.5-VL-7B modeli kullanılarak saniyenin altında sahne analizi gerçekleştirilir.
- **Konuşma Boşluğu Tespiti (VAD):** Silero VAD teknolojisi ile diyaloglar arasındaki sessizlikler milisaniyelik hassasiyetle tespit edilir.
- **Doğal Ses Sentezi (TTS):** XTTS-v2 modeli ile bağlama uygun, kaliteli Türkçe sesli betimlemeler üretilir.
- **Ses Karıştırma ve Ducking:** Betimleme sırasında orijinal video sesi otomatik olarak alçaltılır (ducking) ve betimleme sonrası kademeli olarak yükseltilir.
- **Sahne Farkındalığı:** HSV histogram analizi ile kamera açısı değişimleri takip edilir ve gereksiz betimleme tekrarları önlenir.

## Kullanılan Teknolojiler

### Backend (AI ve Veri İşleme)
- **Dil:** Python 3.9+
- **Framework:** FastAPI (API Sunucusu), AsyncIO (Asenkron İşleme)
- **AI Modelleri:** 
    - vLLM (Qwen2.5-VL-7B-Instruct-AWQ)
    - Coqui XTTS-v2
    - Silero VAD
- **Kütüphaneler:** OpenCV, NumPy, PyTorch, Librosa, Pydub

### Frontend (Kullanıcı Arayüzü ve 3D)
- **Web:** Vanilla HTML5, CSS3, JavaScript
- 
## Sistem Mimarisi

Sistem, olay güdümlü (event-driven) bir asenkron pipeline üzerinde çalışır:
1. **Giriş:** Video akışı üzerinden ses ve görüntü kareleri eşzamanlı olarak okunur.
2. **Analiz:** VAD worker'ı konuşma boşluklarını yakalar.
3. **Betimleme:** Boşluk yakalandığında, o ana ait video kareleri VLM'e gönderilir ve açıklama metni üretilir.
4. **Sentez:** Üretilen metin TTS sunucusu üzerinden sese dönüştürülür.
5. **Çıkış:** Mixer modülü, orijinal ses ile betimleme sesini birleştirerek kullanıcıya sunar.

## Test Linki 

[Uygulama Linki](http://ec2-18-207-124-53.compute-1.amazonaws.com:3000)

## Kurulum ve Yapılandırma

### Backend Kurulumu

1. Bağımlılıkları yükleyin:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```
2. `.env` dosyasını oluşturun:
   `.env.example` dosyasını `.env` olarak kopyalayın ve gerekli URL'leri tanımlayın.
   
### Frontend Kurulumu

Node.js yüklü olmayan ortamlarda veya hızlı bir test için Python üzerinden statik bir sunucu başlatabilirsiniz:
```bash
cd frontend
python -m http.server 8000
```

## Yapılandırma (.env)

Projenin çalışması için gerekli çevresel değişkenler:
- `VLLM_URL`: Qwen2.5-VL sunucusunun API adresi.
- `TTS_URL`: XTTS-v2 sunucusunun adresi.
- `VLLM_API_KEY`: Model sunucusu için gerekli API anahtarı (opsiyonel).
- `LOG_LEVEL`: Uygulama loglama seviyesi (DEBUG, INFO, ERROR).

## Kullanım Kılavuzu

### API Üzerinden Video İşleme
Backend sunucusunu başlatın:
```bash
cd backend
python api_server.py
```
Sunucu varsayılan olarak `8080` portunda çalışacaktır. `/upload` endpoint'i üzerinden video yükleyerek işleme sürecini başlatabilirsiniz.

### Manuel Test
Terminal üzerinden bir video dosyasını doğrudan işlemek için:
```bash
python main.py --video video_yolu.mp4
```

README’e eklemek için en iyi yer “Kullanım Kılavuzu”ndan sonra ayrı bir bölüm olur. Aşağıya direkt koyabileceğin **hazır “Kullanım Senaryosu”** yazdım:

---

## Kullanım Senaryosu (End-to-End Akış)

Engelsiz TV’nin tipik bir kullanım senaryosu, canlı veya önceden kaydedilmiş bir video içeriğinin gerçek zamanlı olarak erişilebilir hale getirilmesi sürecini kapsar.

1. **Gerçek Zamanlı Analiz**

   * Video akışı frame bazında alınır.
   * Silero VAD, konuşma olup olmadığını sürekli izler.
   * Konuşma olmadığı anlar “betimleme fırsatı” olarak işaretlenir.

2. **Sahne Anlama**

   * Seçilen frame’ler Qwen2.5-VL modeline gönderilir.
   * Model sahneyi analiz eder:

     * Ortam (örneğin: stüdyo, saha, sokak)
     * Olay (örneğin: sunucu geçiş yapıyor, grafik gösteriliyor)

3. **Betimleme Üretimi**

   * Model çıktısı doğal dile dönüştürülür.
   * Örnek çıktı:

     > “Sunucu haber bülteninde ekonomi gündemini sunuyor, ekranda grafikler gösteriliyor.”



## Ekip Üyeleri

- **Abdussamed Güldal** - Takım kaptanı
- **Furkan Vural** - AI & Arka yüz geliştirici
- **Samet Oran** - İş geliştirme /Qa tester
- **Enes Bushi** - Marketing 
- **Furkan Vural** - AI & Ön yüz geliştirici

## İş Ortakları ve Destekçiler

Bu proje aşağıdaki kurumların teknolojik altyapı ve mentorluk destekleriyle geliştirilmiştir:
- **NVIDIA:** GPU Hızlandırma ve L40S Altyapısı
- **YTÜ Startup House:** Kuluçka ve Girişimcilik Desteği
- **Türksat:** Yayın Altyapısı ve Sektörel Danışmanlık

---
*Not: Bu proje bir hackathon kapsamında geliştirilmiş bir prototiptir.*
