// ===================== THEME =====================
const THEME_KEY = 'engelsiz-theme';

function getPreferredTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved) return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
    const icon = document.getElementById('theme-icon');
    if (icon) icon.textContent = theme === 'dark' ? '☀️' : '🌙';
}

setTheme(getPreferredTheme());

const themeToggle = document.getElementById('theme-toggle');
if (themeToggle) {
    themeToggle.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        setTheme(current === 'dark' ? 'light' : 'dark');
    });
}

// ===================== NAVBAR SCROLL =====================
const navbar = document.getElementById('navbar');
if (navbar) {
    window.addEventListener('scroll', () => {
        navbar.classList.toggle('scrolled', window.scrollY > 20);
    });
}

// ===================== HAMBURGER MENU =====================
const hamburger = document.getElementById('hamburger-btn');
const navLinks = document.getElementById('nav-links');
if (hamburger && navLinks) {
    hamburger.addEventListener('click', () => {
        navLinks.classList.toggle('open');
        hamburger.classList.toggle('active');
    });
    // Close on nav-link click (mobile)
    navLinks.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            navLinks.classList.remove('open');
            hamburger.classList.remove('active');
        });
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

// ===================== FADE-IN ON SCROLL =====================
const fadeEls = document.querySelectorAll('.fade-in');
if (fadeEls.length > 0 && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });
    fadeEls.forEach(el => observer.observe(el));
} else {
    // Fallback: show all
    fadeEls.forEach(el => el.classList.add('visible'));
}