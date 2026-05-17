// ===================== STATE =====================
let selectedFile = null;
let currentJobId = null;
let isProcessing = false;
let pollingInterval = null;

// Subtitle state
let subtitlesEnabled = false;
let subtitleData = [];

// ===================== DOM REFS =====================
const videoInput = document.getElementById('video-input');
const videoPlaceholder = document.getElementById('video-placeholder');
const videoPlayer = document.getElementById('video-player');
const subtitleOverlay = document.getElementById('subtitle-overlay');
const uploadBtn = document.getElementById('upload-btn');
const processBtn = document.getElementById('process-btn');
const downloadBtn = document.getElementById('download-btn');
const statusMessage = document.getElementById('status-message');
const videoIcon = document.getElementById('video-icon');
const videoStatusText = document.getElementById('video-status-text');
const progressBar = document.getElementById('process-progress');
const progressFill = document.getElementById('process-progress-fill');
const progressInfo = document.getElementById('progress-info');
const progressStatusText = document.getElementById('progress-status-text');
const progressPercent = document.getElementById('progress-percent');

// ===================== FILE HANDLING =====================
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
    if (e.dataTransfer.files.length > 0) handleFileSelect(e.dataTransfer.files[0]);
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
    subtitleData = [];
    hideSubtitle();

    const url = URL.createObjectURL(file);
    videoPlayer.src = url;
    videoPlayer.classList.remove('hidden');
    videoPlaceholder.classList.add('hidden');

    processBtn.disabled = false;
    showStatus(`Seçildi: ${file.name} (${formatSize(file.size)})`, 'success');
}

function triggerUpload() { videoInput.click(); }

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ===================== PROCESSING =====================
async function processVideo() {
    if (!selectedFile || isProcessing) return;

    isProcessing = true;
    processBtn.disabled = true;
    uploadBtn.disabled = true;
    subtitleData = [];
    hideSubtitle();

    showProgress(0, 'Yükleniyor...');
    showStatus('Video yükleniyor...', 'info');

    try {
        const response = await uploadVideo(selectedFile, (percent) => {
            showProgress(percent, percent < 100 ? 'Yükleniyor...' : 'İşleniyor...');
        });

        currentJobId = response.job_id;
        showStatus('Video yüklendi. İşleniyor...', 'info');

        pollingInterval = setInterval(async () => {
            try {
                const status = await pollJobStatus(currentJobId);
                if (!status) return;

                if (status.status === 'error') {
                    clearInterval(pollingInterval);
                    handleError(new Error(status.message || 'İşleme sırasında hata oluştu.'));
                    return;
                }

                // Update progress
                if (status.progress != null) {
                    showProgress(status.progress, 'İşleniyor...');
                }

                // Collect subtitle data
                if (status.descriptions && Array.isArray(status.descriptions)) {
                    subtitleData = status.descriptions.map(d => ({
                        time: d.start_time || 0,
                        endTime: d.end_time || ((d.start_time || 0) + 5),
                        text: d.text
                    }));
                }

                if (status.status === 'done') {
                    clearInterval(pollingInterval);
                    await finishProcessing();
                }
            } catch (err) {
                // Don't crash on individual poll errors
                console.error('Poll döngüsü hatası:', err);
            }
        }, 1500);

    } catch (error) {
        handleError(error);
    }
}

async function finishProcessing() {
    isProcessing = false;

    showProgress(100, 'Tamamlandı!');
    showStatus('Video indiriliyor ve oynatılıyor...', 'info');

    try {
        const blob = await fetchProcessedVideo(currentJobId);
        const url = URL.createObjectURL(blob);

        videoPlayer.src = url;
        videoPlayer.classList.remove('hidden');
        videoPlaceholder.classList.add('hidden');

        // Small delay for src to settle
        setTimeout(() => {
            videoPlayer.play().catch(() => {});
        }, 200);

        // Try loading subtitles from backend
        await loadSubtitles(currentJobId);

        // Enable subtitles automatically
        enableSubtitles();

        showStatus('Betimleme eklendi. Videoyu izleyebilirsiniz.', 'success');

    } catch (err) {
        showStatus('Video yüklenirken hata: ' + err.message, 'error');
    }

    hideProgress();
    processBtn.disabled = false;
    uploadBtn.disabled = false;
    downloadBtn.disabled = false;
}

function handleError(error) {
    showStatus('Hata: ' + error.message, 'error');
    isProcessing = false;
    hideProgress();
    processBtn.disabled = false;
    uploadBtn.disabled = false;
}

// ===================== DOWNLOAD =====================
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

// ===================== SUBTITLES =====================
function toggleSubtitles() {
    subtitlesEnabled = !subtitlesEnabled;
    document.getElementById('subtitle-toggle').classList.toggle('active', subtitlesEnabled);
    if (!subtitlesEnabled) hideSubtitle();
}

function enableSubtitles() {
    subtitlesEnabled = true;
    document.getElementById('subtitle-toggle').classList.add('active');
}

function hideSubtitle() {
    subtitleOverlay.classList.add('hidden');
    subtitleOverlay.textContent = '';
}

function setSubtitleSize(size, btnEl) {
    const sizes = { small: '0.875rem', medium: '1rem', large: '1.25rem' };
    document.documentElement.style.setProperty('--subtitle-size', sizes[size]);

    document.querySelectorAll('.font-size-btn').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
}

// Sync subtitles with video playback
videoPlayer.addEventListener('timeupdate', () => {
    if (!subtitlesEnabled || subtitleData.length === 0) return;

    const t = videoPlayer.currentTime;
    const active = subtitleData.find(s => t >= s.time && t <= s.endTime);

    if (active) {
        subtitleOverlay.textContent = active.text;
        subtitleOverlay.classList.remove('hidden');
    } else {
        subtitleOverlay.classList.add('hidden');
    }
});

async function loadSubtitles(jobId) {
    try {
        const response = await fetch(`${API_BASE_URL}/subtitles/${jobId}`);
        if (response.ok) {
            const data = await response.json();
            if (Array.isArray(data)) {
                subtitleData = data.map(d => ({
                    time: d.start_time || d.time || 0,
                    endTime: d.end_time || d.endTime || ((d.start_time || d.time || 0) + 5),
                    text: d.text
                }));
            }
        }
    } catch (e) {
        console.log('Altyazı endpoint bulunamadı, polling verileri kullanılacak');
    }
}

// ===================== SETTINGS POPOVER =====================
function toggleSettings() {
    document.getElementById('settings-popover').classList.toggle('hidden');
}

document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.settings-wrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        document.getElementById('settings-popover').classList.add('hidden');
    }
});

// ===================== PROGRESS =====================
function showProgress(percent, label) {
    progressBar.classList.remove('hidden');
    progressInfo.classList.remove('hidden');
    progressFill.style.width = percent + '%';
    progressPercent.textContent = Math.round(percent) + '%';
    if (label) progressStatusText.textContent = label;
}

function hideProgress() {
    setTimeout(() => {
        progressBar.classList.add('hidden');
        progressInfo.classList.add('hidden');
    }, 1000);
}

// ===================== STATUS =====================
function showStatus(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = 'status-msg ' + (type || '');
}

// ===================== BACKEND STATUS =====================
async function checkBackendStatus() {
    const health = await checkHealth();
    const dot = document.getElementById('backend-dot');
    const text = document.getElementById('backend-text');
    if (!dot || !text) return;

    if (health && health.status === 'ok') {
        dot.className = 'status-dot connected';
        text.textContent = 'Backend bağlı';
    } else {
        dot.className = 'status-dot disconnected';
        text.textContent = 'Backend bağlantısı yok';
    }
}

checkBackendStatus();
setInterval(checkBackendStatus, 30000);