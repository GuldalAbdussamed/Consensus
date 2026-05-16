// ===================== DEMO PAGE SIMULATION =====================

let simRunning = false;
let simTimer = null;
let elapsedSec = 0;
const totalSec = 60;
let descCount = 0;

// Simüle edilmiş betimleme verileri (timestamp → metin)
const simulationEvents = [
    { time: 5,  vadState: 'Sessizlik', step: 'vad',   desc: null },
    { time: 8,  vadState: 'Boşluk Tespit Edildi!', step: 'vlm', desc: null },
    { time: 10, vadState: 'VLM Analiz Ediyor...', step: 'vlm', desc: null },
    { time: 12, vadState: 'Seslendiriliyor', step: 'tts', desc: "Stüdyoda bir spiker, masanın karşısında oturuyor. Ellerinde notlar var, kameraya bakıyor." },
    { time: 14, vadState: 'Mix Yapılıyor', step: 'mixer', desc: null },
    { time: 16, vadState: 'Sessizlik', step: null, desc: null },
    { time: 22, vadState: 'Boşluk Tespit Edildi!', step: 'vlm', desc: null },
    { time: 25, vadState: 'VLM Analiz Ediyor...', step: 'vlm', desc: null },
    { time: 27, vadState: 'Seslendiriliyor', step: 'tts', desc: "Ekranda bir grafik belirdi. Yüzde seksen beş oranında artış gösteren çubuk grafik gösteriliyor." },
    { time: 30, vadState: 'Mix Yapılıyor', step: 'mixer', desc: null },
    { time: 33, vadState: 'Sessizlik', step: null, desc: null },
    { time: 40, vadState: 'Boşluk Tespit Edildi!', step: 'vlm', desc: null },
    { time: 43, vadState: 'VLM Analiz Ediyor...', step: 'vlm', desc: null },
    { time: 45, vadState: 'Seslendiriliyor', step: 'tts', desc: "İki kişi tartışıyor. Sağdaki kişi ayağa kalktı, sol taraftaki pencereden dışarıya bakıyor." },
    { time: 48, vadState: 'Mix Yapılıyor', step: 'mixer', desc: null },
    { time: 50, vadState: 'Sessizlik', step: null, desc: null },
    { time: 54, vadState: 'Boşluk Tespit Edildi!', step: 'vlm', desc: null },
    { time: 56, vadState: 'Seslendiriliyor', step: 'tts', desc: "Sahne dışarıya geçti. Gün batımında şehir silueti görünüyor, arabalar yolda ilerliyor." },
    { time: 58, vadState: 'Mix Yapılıyor', step: 'mixer', desc: null },
];

// Waveform setup
const waveformEl = document.getElementById('waveform');
const NUM_BARS = 48;
let waveBars = [];
if (waveformEl) {
    for (let i = 0; i < NUM_BARS; i++) {
        const bar = document.createElement('div');
        bar.style.cssText = 'flex:1; border-radius:2px; background:#333; transition: height 0.15s ease;';
        bar.style.height = '4px';
        waveformEl.appendChild(bar);
        waveBars.push(bar);
    }
}

function animateWave(active) {
    waveBars.forEach((bar, i) => {
        const h = active ? Math.random() * 44 + 4 : Math.random() * 6 + 2;
        bar.style.height = h + 'px';
        bar.style.background = active ? '#CC0000' : '#333';
    });
}

// Pipeline state helpers
function setStep(stepId, state) { // 'idle' | 'active' | 'done'
    const badge = document.getElementById('badge-' + stepId);
    const dot = document.querySelector('#step-' + stepId + ' .pipe-dot');
    if (!badge || !dot) return;
    badge.className = 'pipe-badge ' + (state === 'active' ? 'badge-active' : state === 'done' ? 'badge-done' : 'badge-idle');
    badge.textContent = state === 'active' ? 'Çalışıyor' : state === 'done' ? 'Tamamlandı' : 'Bekliyor';
    dot.className = 'pipe-dot ' + (state === 'active' ? 'active' : state === 'done' ? 'done' : '');
}

function resetAllSteps() {
    ['vad', 'vlm', 'tts', 'mixer'].forEach(s => setStep(s, 'idle'));
}

function addDescription(text, timeStr) {
    const feed = document.getElementById('desc-feed');
    if (!feed) return;
    const empty = feed.querySelector('.desc-empty');
    if (empty) empty.remove();

    const item = document.createElement('div');
    item.className = 'desc-item';
    item.innerHTML = `<div class="desc-item-time">⏱ ${timeStr}</div><div class="desc-item-text">${text}</div>`;
    feed.prepend(item);
    descCount++;
    const countEl = document.getElementById('desc-count');
    if (countEl) countEl.textContent = descCount + ' betimleme';
}

function setMixer(originalPct, descPct, originalDb, descDb) {
    const ov = document.getElementById('original-vol');
    const dv = document.getElementById('desc-vol');
    const odb = document.getElementById('original-db');
    const ddb = document.getElementById('desc-db');
    if (ov) ov.style.width = originalPct + '%';
    if (dv) dv.style.width = descPct + '%';
    if (odb) odb.textContent = originalDb;
    if (ddb) ddb.textContent = descDb;
}

function formatTime(sec) {
    const m = Math.floor(sec / 60).toString().padStart(2, '0');
    const s = (sec % 60).toString().padStart(2, '0');
    return m + ':' + s;
}

let processedEvents = new Set();

function tick() {
    elapsedSec++;

    // Progress bar & time
    const pct = (elapsedSec / totalSec) * 100;
    const pBar = document.getElementById('video-progress');
    const cTime = document.getElementById('current-time');
    if (pBar) pBar.style.width = Math.min(pct, 100) + '%';
    if (cTime) cTime.textContent = formatTime(elapsedSec);

    // VAD label
    const vadLabel = document.getElementById('vad-label');

    // Check events
    simulationEvents.forEach((evt, idx) => {
        if (evt.time === elapsedSec && !processedEvents.has(idx)) {
            processedEvents.add(idx);

            if (vadLabel) vadLabel.textContent = 'VAD: ' + evt.vadState;

            resetAllSteps();

            if (evt.step) {
                setStep('vad', 'done');
                if (evt.step === 'vlm') { setStep('vlm', 'active'); setMixer(100, 0, '0 dB', '— dB'); }
                if (evt.step === 'tts') { setStep('vlm', 'done'); setStep('tts', 'active'); }
                if (evt.step === 'mixer') { setStep('tts', 'done'); setStep('mixer', 'active'); setMixer(30, 100, '-12 dB', '0 dB'); }
            } else {
                setMixer(100, 0, '0 dB', '— dB');
            }

            if (evt.desc) {
                setTimeout(() => {
                    addDescription(evt.desc, formatTime(elapsedSec));
                    setStep('mixer', 'done');
                    setMixer(100, 0, '0 dB', '— dB');
                }, 800);
            }
        }
    });

    // Animate waveform
    const isSpeaking = simulationEvents.some(e => {
        return elapsedSec >= e.time && e.vadState === 'Sessizlik';
    });
    animateWave(!isSpeaking);

    if (elapsedSec >= totalSec) {
        clearInterval(simTimer);
        simRunning = false;
        const btn = document.getElementById('start-btn');
        if (btn) { btn.textContent = '✓ Simülasyon Bitti'; btn.disabled = true; }
    }
}

function startSimulation() {
    if (simRunning) return;
    simRunning = true;
    const btn = document.getElementById('start-btn');
    if (btn) btn.textContent = '⏸ Çalışıyor...';
    setStep('vad', 'active');
    simTimer = setInterval(tick, 1000);
}

function resetSimulation() {
    clearInterval(simTimer);
    simRunning = false;
    elapsedSec = 0;
    descCount = 0;
    processedEvents.clear();

    const pBar = document.getElementById('video-progress');
    const cTime = document.getElementById('current-time');
    const feed = document.getElementById('desc-feed');
    const vadLabel = document.getElementById('vad-label');
    const btn = document.getElementById('start-btn');
    const countEl = document.getElementById('desc-count');

    if (pBar) pBar.style.width = '0%';
    if (cTime) cTime.textContent = '00:00';
    if (vadLabel) vadLabel.textContent = 'VAD: Bekliyor';
    if (btn) { btn.textContent = '▶ Simülasyonu Başlat'; btn.disabled = false; }
    if (countEl) countEl.textContent = '0 betimleme';
    if (feed) feed.innerHTML = '<div class="desc-empty"><div class="empty-icon">🔊</div><p>Yayın başladığında betimleme akışı burada görünecek...</p></div>';

    resetAllSteps();
    setMixer(100, 0, '0 dB', '— dB');
    waveBars.forEach(b => { b.style.height = '4px'; b.style.background = '#333'; });
}

// Initial mixer state
setMixer(100, 0, '0 dB', '— dB');

// Idle waveform
setInterval(() => {
    if (!simRunning) {
        waveBars.forEach(bar => {
            bar.style.height = (Math.random() * 4 + 2) + 'px';
        });
    }
}, 200);
