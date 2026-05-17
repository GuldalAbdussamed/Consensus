let selectedFile = null;
let currentJobId = null;
let isProcessing = false;
let pollingInterval = null;

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
    currentJobId = null;
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
    videoStatusText.textContent = 'Video Yükleniyor...';
    document.querySelector('.upload-hint')?.remove();
    
    showStatus('Video yükleniyor...', 'info');
    
    try {
        const response = await uploadVideo(selectedFile, (percent) => {
            uploadProgress.style.width = percent + '%';
            uploadPercent.textContent = percent + '%';
            if (percent === 100) {
                document.querySelector('.progress-label').textContent = 'İşleniyor...';
            }
        });
        
        currentJobId = response.job_id;
        showStatus('Video yüklendi. İşleniyor...', 'info');
        videoStatusText.textContent = 'Video İşleniyor...';
        
        // Start polling
        pollingInterval = setInterval(async () => {
            const status = await pollJobStatus(currentJobId);
            if (!status) return;
            
            if (status.status === 'error') {
                clearInterval(pollingInterval);
                throw new Error(status.message || 'İşleme sırasında hata oluştu.');
            }
            
            // Update pipeline UI
            if (status.vad) setStep('vad', status.vad);
            if (status.vlm) setStep('vlm', status.vlm);
            if (status.tts) setStep('tts', status.tts);
            if (status.mixer) setStep('mixer', status.mixer);
            
            // Update descriptions
            if (status.descriptions && Array.isArray(status.descriptions)) {
                // Clear feed
                const feed = document.getElementById('desc-feed');
                if (feed) feed.innerHTML = '';
                // Add descriptions in reverse order so newest is at top
                [...status.descriptions].reverse().forEach(desc => {
                    addDescription(desc.text, desc.time);
                });
            }
            
            if (status.status === 'done') {
                clearInterval(pollingInterval);
                finishProcessing();
            }
        }, 1500);
        
    } catch (error) {
        handleError(error);
    }
}

function finishProcessing() {
    isProcessing = false;
    uploadProgressContainer.classList.add('hidden');
    processBtn.disabled = false;
    uploadBtn.disabled = false;
    downloadBtn.disabled = false;
    
    showStatus('İşlem tamamlandı!', 'success');
    
    videoIcon.textContent = '✅';
    videoStatusText.textContent = 'İşlem Tamamlandı - İndirmek için tıklayın';
    videoPlaceholder.onclick = downloadResult;
}

function handleError(error) {
    showStatus('Hata: ' + error.message, 'error');
    resetAllSteps();
    videoIcon.textContent = '❌';
    videoStatusText.textContent = 'Hata Oluştu';
    isProcessing = false;
    uploadProgressContainer.classList.add('hidden');
    processBtn.disabled = false;
    uploadBtn.disabled = false;
}

async function downloadResult() {
    if (!currentJobId) return;
    const filename = selectedFile ? `engelsiz_${selectedFile.name}` : 'engelsiz_video.mp4';
    try {
        await downloadJob(currentJobId, filename);
        showStatus('Video indirildi!', 'success');
    } catch (err) {
        showStatus('İndirme hatası: ' + err.message, 'error');
    }
}

function resetAll() {
    selectedFile = null;
    currentJobId = null;
    isProcessing = false;
    if (pollingInterval) clearInterval(pollingInterval);
    
    videoPlayer.src = '';
    videoPlayer.classList.add('hidden');
    videoPlaceholder.classList.remove('hidden');
    videoPlaceholder.onclick = () => videoInput.click();
    
    uploadProgressContainer.classList.add('hidden');
    processBtn.disabled = true;
    downloadBtn.disabled = true;
    
    resetAllSteps();
    
    const feed = document.getElementById('desc-feed');
    if (feed) feed.innerHTML = '<div class="desc-empty"><div style="font-size: 2rem;">📝</div><p>Video işlenirken oluşturulan betimlemeler<br>burada canlı olarak akacaktır.</p></div>';
    const countEl = document.getElementById('desc-count');
    if (countEl) countEl.textContent = '0 betimleme';
    
    showStatus('Sıfırlandı', 'info');
}

function setStep(stepId, state) {
    const badge = document.getElementById('badge-' + stepId);
    if (!badge) return;
    badge.className = 'pipe-badge ' + (state === 'active' ? 'badge-active' : state === 'done' ? 'badge-done' : 'badge-idle');
    badge.textContent = state === 'active' ? 'Çalışıyor' : state === 'done' ? 'Tamamlandı' : 'Bekliyor';
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
    feed.appendChild(item);
    
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
    statusMessage.className = 'status-msg ' + (type || '');
}

async function checkBackendStatus() {
    const health = await checkHealth();
    const statusDot = document.querySelector('#backend-status .status-dot');
    const statusText = document.querySelector('#backend-status .status-text');
    
    if (!statusDot || !statusText) return;
    
    if (health && health.status === 'ok') {
        statusDot.className = 'status-dot connected';
        statusText.textContent = 'Backend: Bağlı';
        showStatus('Backend bağlantısı hazır', 'success');
    } else {
        statusDot.className = 'status-dot disconnected';
        statusText.textContent = 'Backend: Bağlantı Yok';
        showStatus('Backend erişilemiyor. Sunucuyu başlatın: python api_server.py', 'error');
    }
}

checkBackendStatus();
setInterval(checkBackendStatus, 30000);
