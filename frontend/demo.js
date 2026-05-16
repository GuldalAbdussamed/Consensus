let selectedFile = null;
let processedBlob = null;
let isProcessing = false;
let visualizerInterval = null;

// UI Elements
const elements = {
    videoInput: document.getElementById('video-input'),
    videoPlaceholder: document.getElementById('video-placeholder'),
    videoPlayer: document.getElementById('video-player'),
    videoStatusText: document.getElementById('video-status-text'),
    processingOverlay: document.getElementById('processing-overlay'),
    uploadProgressContainer: document.getElementById('upload-progress-container'),
    uploadProgress: document.getElementById('upload-progress'),
    uploadPercent: document.getElementById('upload-percent'),
    uploadBtn: document.getElementById('upload-btn'),
    processBtn: document.getElementById('process-btn'),
    downloadBtn: document.getElementById('download-btn'),
    statusMessage: document.getElementById('status-message'),
    backendStatus: document.getElementById('backend-status'),
    descFeed: document.getElementById('desc-feed'),
    descCount: document.getElementById('desc-count'),
    waveform: document.getElementById('waveform'),
    vadLabel: document.getElementById('vad-label')
};

// Event Listeners
elements.videoPlaceholder.addEventListener('click', () => elements.videoInput.click());
elements.videoPlaceholder.addEventListener('dragover', (e) => {
    e.preventDefault();
    elements.videoPlaceholder.classList.add('dragover');
});
elements.videoPlaceholder.addEventListener('dragleave', () => {
    elements.videoPlaceholder.classList.remove('dragover');
});
elements.videoPlaceholder.addEventListener('drop', (e) => {
    e.preventDefault();
    elements.videoPlaceholder.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) handleFileSelect(files[0]);
});

elements.videoInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleFileSelect(e.target.files[0]);
});

function handleFileSelect(file) {
    const allowed = ['.mp4', '.mkv', '.avi', '.mov', '.webm'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) {
        showStatus('Desteklenmeyen format!', 'error');
        return;
    }
    
    selectedFile = file;
    processedBlob = null;
    elements.downloadBtn.disabled = true;
    
    const url = URL.createObjectURL(file);
    elements.videoPlayer.src = url;
    elements.videoPlayer.classList.remove('hidden');
    elements.videoPlaceholder.classList.add('hidden');
    
    elements.processBtn.disabled = false;
    showStatus(`Dosya seçildi: ${file.name}`, 'success');
    document.getElementById('video-panel-status').textContent = 'Video Hazır';
}

function triggerUpload() {
    elements.videoInput.click();
}

async function processVideo() {
    if (!selectedFile || isProcessing) return;
    
    isProcessing = true;
    updateUIForProcessing(true);
    startVisualizerAnimation();
    
    setStep('vad', 'active');
    showStatus('Video yükleniyor...', 'info');
    
    try {
        const result = await uploadVideo(selectedFile, (percent) => {
            elements.uploadProgress.style.width = percent + '%';
            elements.uploadPercent.textContent = percent + '%';
            if (percent === 100) {
                showStatus('Yapay Zeka analizi başladı...', 'info');
                document.querySelector('.progress-label').textContent = 'Analiz Ediliyor...';
                setStep('vad', 'done');
                setStep('vlm', 'active');
            }
        });
        
        processedBlob = result.blob;
        elements.downloadBtn.disabled = false;
        
        const procTime = result.procTime || '?';
        showStatus(`İşlem başarıyla tamamlandı!`, 'success');
        
        setStep('vlm', 'done');
        setStep('tts', 'done');
        setStep('mixer', 'done');
        
        addDescription(`Video analizi tamamlandı. Toplam süre: ${procTime}`, new Date().toLocaleTimeString('tr-TR'), 'SİSTEM');
        
        const url = URL.createObjectURL(result.blob);
        elements.videoPlayer.src = url;
        elements.videoPlayer.classList.remove('hidden');
        elements.processingOverlay.classList.add('hidden');
        
    } catch (error) {
        showStatus('Hata: ' + error.message, 'error');
        resetAllSteps();
    } finally {
        isProcessing = false;
        updateUIForProcessing(false);
        stopVisualizerAnimation();
    }
}

function updateUIForProcessing(active) {
    elements.processBtn.disabled = active;
    elements.uploadBtn.disabled = active;
    
    if (active) {
        elements.uploadProgressContainer.classList.add('active');
        elements.processingOverlay.classList.remove('hidden');
        document.getElementById('video-panel-status').textContent = 'İşleniyor';
    } else {
        elements.uploadProgressContainer.classList.remove('active');
        elements.processingOverlay.classList.add('hidden');
        document.getElementById('video-panel-status').textContent = processedBlob ? 'Tamamlandı' : 'Hazır';
    }
}

function downloadResult() {
    if (!processedBlob) return;
    const filename = selectedFile ? `engelsiz_${selectedFile.name}` : 'engelsiz_video.mp4';
    downloadBlob(processedBlob, filename);
    showStatus('Video indiriliyor...', 'success');
}

function resetAll() {
    selectedFile = null;
    processedBlob = null;
    isProcessing = false;
    
    elements.videoPlayer.src = '';
    elements.videoPlayer.classList.add('hidden');
    elements.videoPlaceholder.classList.remove('hidden');
    elements.processingOverlay.classList.add('hidden');
    elements.uploadProgressContainer.classList.remove('active');
    
    elements.processBtn.disabled = true;
    elements.downloadBtn.disabled = true;
    
    resetAllSteps();
    setMixer(100, 0, '0dB', '-∞');
    
    elements.descFeed.innerHTML = `
        <div class="feed-empty">
            <div class="empty-glow"></div>
            <div class="empty-text">Analiz başladığında betimlemeler burada görünecek</div>
        </div>
    `;
    elements.descCount.textContent = '0';
    document.getElementById('video-panel-status').textContent = 'Hazır';
    
    showStatus('Sistem sıfırlandı', 'info');
}

function setStep(stepId, state) {
    const item = document.getElementById('step-' + stepId);
    const badge = document.getElementById('badge-' + stepId);
    if (!item || !badge) return;
    
    item.className = 'flow-item ' + state;
    badge.className = 'flow-badge ' + (state === 'active' ? 'badge-active' : state === 'done' ? 'badge-done' : 'badge-idle');
    badge.textContent = state === 'active' ? 'Çalışıyor' : state === 'done' ? 'Tamamlandı' : 'Bekliyor';
    
    if (state === 'active') {
        item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function resetAllSteps() {
    ['vad', 'vlm', 'tts', 'mixer'].forEach(s => setStep(s, 'idle'));
}

function addDescription(text, timeStr, tag = 'BETİMLEME') {
    const empty = elements.descFeed.querySelector('.feed-empty');
    if (empty) empty.remove();

    const item = document.createElement('div');
    item.className = 'feed-item';
    item.innerHTML = `
        <div class="item-header">
            <span class="item-time">${timeStr}</span>
            <span class="item-tag">${tag}</span>
        </div>
        <div class="item-text">${text}</div>
    `;
    elements.descFeed.prepend(item);
    
    const count = elements.descFeed.querySelectorAll('.feed-item').length;
    elements.descCount.textContent = count;

    // Simulate mixer activity
    if (tag === 'BETİMLEME') {
        simulateMixerActivity();
    }
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

function simulateMixerActivity() {
    setMixer(40, 90, '-6dB', '0dB');
    setTimeout(() => {
        setMixer(100, 0, '0dB', '-∞');
    }, 4000);
}

function startVisualizerAnimation() {
    elements.vadLabel.classList.add('active');
    elements.vadLabel.textContent = 'VAD: AKTİF';
    
    visualizerInterval = setInterval(() => {
        const bars = elements.waveform.querySelectorAll('.viz-bar');
        bars.forEach(bar => {
            const h = Math.random() * 80 + 20;
            bar.style.height = h + '%';
            bar.classList.add('active');
        });
    }, 150);
}

function stopVisualizerAnimation() {
    clearInterval(visualizerInterval);
    elements.vadLabel.classList.remove('active');
    elements.vadLabel.textContent = 'VAD: PASİF';
    const bars = elements.waveform.querySelectorAll('.viz-bar');
    bars.forEach(bar => {
        bar.style.height = '20%';
        bar.classList.remove('active');
    });
}

function showStatus(message, type) {
    elements.statusMessage.textContent = message;
    elements.statusMessage.className = 'status-msg ' + (type || '');
}

async function checkBackendStatus() {
    try {
        const health = await checkHealth();
        if (health && health.status === 'ok') {
            document.getElementById('backend-status').innerHTML = `
                <span class="status-dot connected"></span>
                <span class="status-text">Backend: Bağlı</span>
            `;
        } else {
             document.getElementById('backend-status').innerHTML = `
                <span class="status-dot disconnected"></span>
                <span class="status-text">Backend: Bağlantı Yok</span>
            `;
        }
    } catch (err) {
        console.error('Backend durum kontrolü hatası:', err);
    }
}

// Initial Setup
resetAllSteps();
checkBackendStatus();
setInterval(checkBackendStatus, 30000);
