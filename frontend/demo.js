let selectedFile = null;
let processedBlob = null;
let isProcessing = false;

const videoInput = document.getElementById('video-input');
const videoPlaceholder = document.getElementById('video-placeholder');
const videoPlayer = document.getElementById('video-player');
const uploadProgressContainer = document.getElementById('upload-progress-container');
const uploadProgress = document.getElementById('upload-progress');
const uploadPercent = document.getElementById('upload-percent');
const uploadBtn = document.getElementById('upload-btn');
const processBtn = document.getElementById('process-btn');
const downloadBtn = document.getElementById('download-btn');
const statusMessage = document.getElementById('status-message');
const backendStatus = document.getElementById('backend-status');
const videoIcon = document.getElementById('video-icon');
const videoStatusText = document.getElementById('video-status-text');

videoPlaceholder.addEventListener('click', () => videoInput.click());
videoPlaceholder.addEventListener('dragover', (e) => {
    e.preventDefault();
    videoPlaceholder.classList.add('dragover');
});
videoPlaceholder.addEventListener('dragleave', () => {
    videoPlaceholder.classList.remove('dragover');
});
videoPlaceholder.addEventListener('drop', (e) => {
    e.preventDefault();
    videoPlaceholder.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) handleFileSelect(files[0]);
});

videoInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleFileSelect(e.target.files[0]);
});

function handleFileSelect(file) {
    const allowed = ['.mp4', '.mkv', '.avi', '.mov', '.webm'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) {
        showStatus('Desteklenmeyen format! İzin verilenler: ' + allowed.join(', '), 'error');
        return;
    }
    
    selectedFile = file;
    processedBlob = null;
    downloadBtn.disabled = true;
    
    const url = URL.createObjectURL(file);
    videoPlayer.src = url;
    videoPlayer.classList.remove('hidden');
    videoPlaceholder.classList.add('hidden');
    
    processBtn.disabled = false;
    showStatus(`Seçildi: ${file.name} (${formatSize(file.size)})`, 'success');
}

function triggerUpload() {
    videoInput.click();
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function processVideo() {
    if (!selectedFile || isProcessing) return;
    
    isProcessing = true;
    processBtn.disabled = true;
    uploadBtn.disabled = true;
    
    uploadProgressContainer.classList.remove('hidden');
    videoPlayer.classList.add('hidden');
    videoPlaceholder.classList.remove('hidden');
    videoIcon.textContent = '⏳';
    videoStatusText.textContent = 'Video İşleniyor...';
    document.querySelector('.upload-hint')?.remove();
    
    setStep('vad', 'active');
    showStatus('Video yükleniyor...', 'info');
    
    try {
        const result = await uploadVideo(selectedFile, (percent) => {
            uploadProgress.style.width = percent + '%';
            uploadPercent.textContent = percent + '%';
            if (percent === 100) {
                document.querySelector('.progress-label').textContent = 'İşleniyor...';
            }
        });
        
        processedBlob = result.blob;
        downloadBtn.disabled = false;
        
        const procTime = result.procTime || '?';
        showStatus(`İşlem tamamlandı! (${procTime})`, 'success');
        
        setStep('vad', 'done');
        setStep('vlm', 'done');
        setStep('tts', 'done');
        setStep('mixer', 'done');
        
        videoIcon.textContent = '✅';
        videoStatusText.textContent = 'İşlem Tamamlandı - İndirmek için tıklayın';
        videoPlaceholder.onclick = downloadResult;
        
        addDescription(`Video başarıyla işlendi. İşlem süresi: ${procTime}`, new Date().toLocaleTimeString('tr-TR'));
        
        const url = URL.createObjectURL(result.blob);
        videoPlayer.src = url;
        videoPlayer.classList.remove('hidden');
        videoPlaceholder.classList.add('hidden');
        
    } catch (error) {
        showStatus('Hata: ' + error.message, 'error');
        resetAllSteps();
        videoIcon.textContent = '❌';
        videoStatusText.textContent = 'Hata Oluştu';
    } finally {
        isProcessing = false;
        uploadProgressContainer.classList.add('hidden');
        uploadProgress.style.width = '0%';
        uploadPercent.textContent = '0%';
        processBtn.disabled = false;
        uploadBtn.disabled = false;
    }
}

function downloadResult() {
    if (!processedBlob) return;
    const filename = selectedFile ? `engelsiz_${selectedFile.name}` : 'engelsiz_video.mp4';
    downloadBlob(processedBlob, filename);
    showStatus('Video indirildi!', 'success');
}

function resetAll() {
    selectedFile = null;
    processedBlob = null;
    isProcessing = false;
    
    videoPlayer.src = '';
    videoPlayer.classList.add('hidden');
    videoPlaceholder.classList.remove('hidden');
    videoIcon.textContent = '📺';
    videoStatusText.textContent = 'Video Yüklemek İçin Tıklayın';
    videoPlaceholder.onclick = () => videoInput.click();
    
    const hint = document.createElement('div');
    hint.className = 'upload-hint';
    hint.textContent = 'veya sürükle bırak';
    videoPlaceholder.querySelector('.video-content').appendChild(hint);
    
    uploadProgressContainer.classList.add('hidden');
    processBtn.disabled = true;
    downloadBtn.disabled = true;
    
    resetAllSteps();
    setMixer(100, 0, '0 dB', '— dB');
    
    const feed = document.getElementById('desc-feed');
    if (feed) feed.innerHTML = '<div class="desc-empty"><div class="empty-icon">🔊</div><p>Yayın başladığında betimleme akışı burada görünecek...</p></div>';
    document.getElementById('desc-count').textContent = '0 betimleme';
    
    showStatus('Sıfırlandı', 'info');
}

function setStep(stepId, state) {
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
    
    const countEl = document.getElementById('desc-count');
    const count = feed.querySelectorAll('.desc-item').length;
    if (countEl) countEl.textContent = count + ' betimleme';
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

function showStatus(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = 'ctrl-info ' + (type || '');
}

async function checkBackendStatus() {
    const health = await checkHealth();
    const statusDot = backendStatus.querySelector('.status-dot');
    const statusText = backendStatus.querySelector('.status-text');
    
    if (health && health.status === 'ok') {
        statusDot.classList.add('connected');
        statusText.textContent = 'Backend: Bağlı';
        showStatus('Backend bağlantısı hazır', 'success');
    } else {
        statusDot.classList.add('disconnected');
        statusText.textContent = 'Backend: Bağlantı Yok';
        showStatus('Backend erişilemiyor. Sunucuyu başlatın: python api_server.py', 'error');
    }
}

setMixer(100, 0, '0 dB', '— dB');
checkBackendStatus();
setInterval(checkBackendStatus, 30000);
