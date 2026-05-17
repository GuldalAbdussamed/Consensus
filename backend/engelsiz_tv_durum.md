# Engelsiz TV — Proje Durum Notu

> Hackathon projesi. Görme engelliler için canlı TV yayınlarına gerçek zamanlı sesli betimleme ekleyen sistem.

## Hedef

Canlı TV yayınında **konuşma boşluklarına** AI tarafından üretilmiş sesli betimleme yerleştirmek. Görme engelli kullanıcı sahnede ne olduğunu duyarak takip edebilsin.

## Sistemin Şu Anki Hali

`test_vllm.py` adlı bir script var. Şu anki haliyle **offline** çalışıyor: video dosyasını alır, baştan sona analiz eder, betimleme metinlerini terminale basar. TTS yok, ses üretimi yok, video üzerine bindirme yok.

Çalışan kısımlar (validasyonu yapılmış):
- Silero VAD ile konuşma/sessizlik tespiti
- Sessiz boşlukların >=1.5sn olanlarını "betimleme yapılabilir" olarak işaretleme
- Boşluk uzunluğuna göre kelime bütçesi (3 kelime/saniye)
- 3 kareli pencere ile VLM'e gönderme (t-0.5, t, t+0.5)
- Sahne galerisi: A-B-A-B kamera açısı geçişlerinde tekrarı önler (HSV histogram + Bhattacharyya mesafesi)
- "Konuşuyor" gibi zayıf çıktıları eleyen post-process filtresi
- Türkçe meta-konuşma temizliği ("Bu karede...", "Sahnede..." gibi başlangıçların regex temizliği)
- Önceki betimlemeleri bağlam olarak modele geri besleme (deque, son 2)
- Jaccard benzerliği ile metinsel tekrar filtresi

## Ana Hedef: Canlı Sistem (Yol B)

Hackathon demosu için canlı pipeline kurulacak. Gerçek HLS/RTSP entegrasyonu yerine **bir mp4 dosyasını canlı yayın gibi gerçek zamanlı oynatan** simüle pipeline yapılacak. Jüri için bu yeterli, mimari aynı.

### Hedef Pipeline Mimarisi

```
Video kaynak (mp4 dosyası, "canlı" simüle)
   ├── Video frame stream → ekran (gerçek zamanlı oynat)
   └── Audio stream → ses buffer → hoparlör
                          ↓
                    [VAD worker, sliding]
                          ↓ (boşluk algılandı)
                    [Frame snapshot]
                          ↓
                    [VLM worker, async] → açıklama metni
                          ↓
                    [TTS worker, async] → WAV
                          ↓
                    [Mixer] → orijinal sesi alçalt (ducking) + TTS'i bindir
                          ↓
                       Hoparlör
```

### Kritik Mimari Değişiklik

Şu anki script TÜM videoyu önce planlıyor sonra işliyor. Canlı sistem **olay tetiklemeli** olmalı — sadece sesi sürekli dinler, VAD boşluk bulduğunda anında VLM çağırır. Sıfırdan async/event-driven mimariye geçilecek.

## Teknik Detaylar

### vLLM Endpoint
- URL: `VLLM_URL (bkz. config.py)`
- Model: `Qwen/Qwen2.5-VL-7B-Instruct-AWQ`
- Çağrı süresi: ~400-1500ms (3 kareli pencere ile)
- AWS sunucusu: NVIDIA L40S, 46GB VRAM (bol bol yer var)

### TTS Kararı: XTTS-v2 (Coqui)
- Aynı L40S GPU'sunda host edilecek (vLLM yan yana, ~4GB ek VRAM)
- Türkçe kaliteli, streaming destekli, ses klonlama opsiyonu (başta default ses kullan)
- ~400-600ms ilk token gecikmesi
- Ek maliyet: 0 (zaten ayakta olan GPU)

### VAD Parametreleri (Silero)
- Sample rate: 16kHz mono
- threshold: 0.5 (default)
- min_silence_duration_ms: 300
- min_speech_duration_ms: 250
- Kullanılabilir boşluk min: 1.5sn

### Sahne Galerisi Parametresi
- HSV histogram, Bhattacharyya mesafesi
- Eşik: 0.25 (düşük = hassas, yüksek = tembel)
- Test edilen videoda: A-B-A-B kamera açıları doğru tespit edildi, 9 boşluktan 4 gerçek VLM çağrısı

### Prompt Stratejisi
- 3 ardışık kare birlikte gönderiliyor (hareket görsün diye)
- İlk betimleme "sahne tanıt" modu (kim, nerede, ne var)
- Sonrakiler "farklı bir şey söyle" modu (bağlamı verip tekrar etmemesini iste)
- "konuşuyor/konuşuyorlar" yasak — sahnede VAD zaten sessizlik diyor
- Kelime bütçesi boşluk uzunluğuna göre dinamik (4-15 kelime)

## Bilinen Problemler (Daha Çözülmemiş)

1. **Halüsinasyon**: Qwen-VL bazen olmayan detaylar uyduruyor ("mikrofon", "aydınlatma lambası" gibi). Tam çözüm yok, prompt ile azaltıldı.
2. **Türkçe gramer**: "çalışiyor", "kadını oturuyorlar" gibi ek hataları. Prompt'ta uyarı var ama tam kontrol edilemiyor.
3. **Çok kısa boşluklar** (1.5sn altı) atılıyor — TTS sığmaz. İleride "ducking" ile orijinal sesin üstüne bindirilebilir.

## Yeni Session'a Geçerken İlk Adımlar

1. Mevcut `test_vllm.py`'ı oku, mantığını anla.
2. Kullanıcının elinde olan **pipeline dosyası**'nı incele — canlı oynatma altyapısı var mı?
3. Karar ver:
   - Eğer pipeline'da stream/sync altyapısı varsa → üstüne VAD + VLM + TTS bağla
   - Yoksa → sıfırdan asyncio tabanlı event-driven pipeline yaz
4. **XTTS-v2 TTS sunucusunu** L40S üzerinde başlat (FastAPI veya coqui-tts CLI server)
5. Tek cümle POC: bir metin → TTS → WAV indirme. Çalıştığı kanıtlanır.
6. Tek boşluk POC: video oynat, sahte bir boşluk simüle et, gerçek pipeline tetiklensin (VAD → VLM → TTS → mix).
7. Sürekli/canlı moda geç.

## Mix/Ducking Stratejisi (TTS Geldiğinde)

- Orijinal ses: -10dB veya -15dB alçalt (ducking)
- TTS sesi: normalize edilmiş seviyede
- Crossfade: 100-200ms (sert kesim olmasın)
- TTS bittiğinde orijinal ses normale dönsün (ramp up)
- Eğer TTS bitmeden konuşma başlarsa: TTS hızlandır (ffmpeg atempo) veya kes

## Hackathon Demo Stratejisi

- Bir test videosu seçilecek (örnek video1.mp4 var, 60sn, 4 konuşma segmenti)
- Pipeline başlatılır, ekranda video oynatılır
- Jüri konuşma boşluklarında AI betimlemesini duyar
- "Şu anda dosyadan ama gerçek HLS stream'i bağlasak aynı pipeline çalışır" denilebilir
- Stretch goal: ses klonlama ile kanal spikerinin sesinde betimleme

## Önemli Dosyalar

- `test_vllm.py`: Mevcut offline script (devamını burdan geliştirme YAPMA — canlı mimari için sıfırdan yaz, ama mantığı oradan al)
- Kullanıcının "pipeline dosyası" — yeni session başında incelenecek
- `samples/video1.mp4`: Test videosu, 60sn, 18% konuşma kapsama

## Önemli Uyarılar

- Canlı pipeline'da **timing kritik**: TTS boşluğa sığmazsa konuşma üstüne biner, kötü deneyim
- Sahne galerisini canlı modda da koru — A-B-A-B sorunu canlıda da olur
- VLM çağrısı async olmalı, video akışını bloklamamalı
- Audio buffer boyutu önemli: VAD için son ~3 saniye yeterli, geçmişi de tut ki frame snapshot'ı zamana hizalı olsun

## Kullanıcı Tercihleri

- Türkçe iletişim
- Kısa, doğrudan teknik konuşma; gevezelik istemiyor
- Önce tartışıp karar veriyor sonra kodluyor
- Hackathon temposu — pragmatik çözümler, mükemmellik değil çalışır olmak öncelik
