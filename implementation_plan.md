# İşaret Dili Avatar Modülü (Sign Language Avatar Module)

Bu plan, gelen metin (gloss) verisini alıp uygun 3D animasyonları ekranda gösteren bağımsız bir arayüz/oynatıcı modülünün geliştirilmesini kapsar.

## User Review Required

> [!IMPORTANT]
> **Teknoloji Seçimi:** Bu modülü **React.js** ve **React Three Fiber (Three.js)** kullanarak geliştirmeyi öneriyorum. Bu teknoloji, tarayıcı üzerinde yüksek performanslı 3D grafikler göstermemizi sağlar ve diğer ekiplerin projelerine (API veya iframe olarak) çok kolay entegre edilebilir. Bu yaklaşımı onaylıyor musunuz?
>
> **3D Model İhtiyacı:** Animasyonların düzgün çalışması için "riglenmiş" (kemik yapısı olan) bir 3D karaktere ve bu karaktere ait işaret dili animasyon dosyalarına (GLB/GLTF formatında) ihtiyacımız olacak. Başlangıçta sistemi kurmak için internetten bulacağımız ücretsiz/basit bir test karakteri kullanacağız. Kendi karakteriniz hazır mı, yoksa test modeliyle mi başlayalım?

## Proposed Changes

Proje sıfırdan oluşturulacaktır.

### 1. Proje Kurulumu ve Bağımlılıklar (Project Setup)
- Vite kullanılarak yeni bir React projesi başlatılacak.
- 3D çizimler için `three`, `@react-three/fiber` ve `@react-three/drei` kütüphaneleri kurulacak.
- Modern ve şık bir arayüz için temel CSS dosyaları ayarlanacak.

### 2. Avatar Bileşeni (Avatar Component)
#### [NEW] `src/components/Avatar.jsx`
- Bu bileşen, 3D modeli (GLB formatında) sahneye yüklemekten sorumlu olacak.
- Modelin iskelet yapısına (bones) erişip animasyonları yönetecek.

### 3. Animasyon Kontrolcüsü (Animation Controller)
#### [NEW] `src/components/SignLanguagePlayer.jsx`
- Arkadaşlarınızdan (veya test için input kutusundan) gelecek olan "Kelimeler" (Örn: "MERHABA", "NASILSIN") dizisini dinleyecek.
- Gelen kelimeye karşılık gelen animasyon dosyasını (örneğin `merhaba.glb`) bulup Avatar bileşenine "bunu oynat" komutunu gönderecek.
- Peş peşe gelen kelimelerde animasyonların birbirine yumuşak geçiş (blending) yapmasını sağlayacak.

### 4. Ana Arayüz (Main UI)
#### [NEW] `src/App.jsx`
- Ekranın büyük kısmını kaplayan bir 3D sahne oluşturulacak.
- Işıklandırma (aydınlatma) ve kamera ayarları yapılacak.
- Alt kısma, sistemi test edebilmeniz için bir metin giriş kutusu ve "Oynat" butonu eklenecek.

## Verification Plan

### Manual Verification
1. Proje ayağa kaldırıldığında ekranda 3 boyutlu test karakteri görünmelidir.
2. Ekranda karakteri mouse ile çevirebilmeli ve yakınlaşıp uzaklaşabilmeliyiz.
3. Arayüzdeki "Test" butonlarına tıklandığında, karakter seçilen kelimenin animasyonunu oynatmalıdır.
