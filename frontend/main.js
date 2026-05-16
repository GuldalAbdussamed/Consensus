// ===================== NAVBAR SCROLL =====================
const navbar = document.getElementById('navbar');
if (navbar) {
    window.addEventListener('scroll', () => {
        navbar.classList.toggle('scrolled', window.scrollY > 20);
    });
}

// ===================== HERO BUBBLE ANIMATION =====================
const bubbleTexts = [
    "Ekranda iki kişi masa başında oturuyor, belgeler inceleniyor...",
    "Kamera dışarıya kesiyor, şehir manzarası görünüyor...",
    "Sunucu ayağa kalkıyor, elinde dosya tutuyor...",
    "Araba yolda ilerliyor, arka planda dağlar var...",
    "Çocuklar parkta oynuyor, güneş batıyor...",
];
const bubbleEl = document.getElementById('bubble-text');
if (bubbleEl) {
    let idx = 0;
    setInterval(() => {
        idx = (idx + 1) % bubbleTexts.length;
        bubbleEl.style.opacity = '0';
        setTimeout(() => {
            bubbleEl.textContent = bubbleTexts[idx];
            bubbleEl.style.transition = 'opacity 0.5s';
            bubbleEl.style.opacity = '1';
        }, 400);
    }, 3500);
}
