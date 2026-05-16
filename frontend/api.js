// Eğer frontend zaten backend (8000) üzerinden servis ediliyorsa relative path kullan, 
// yoksa (dev server vb.) hostname:8000'e git.
const BASE = (window.location.port === '8000' || window.location.hostname.includes('8000-'))
    ? window.location.origin 
    : `http://${window.location.hostname}:8000`;

async function checkHealth() {
    try {
        // 5 saniye timeout ekleyelim ki sonsuza kadar asılı kalmasın
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        const response = await fetch(`${BASE}/health`, { signal: controller.signal });
        clearTimeout(timeoutId);
        
        if (!response.ok) throw new Error('Backend yanıt vermedi');
        return await response.json();
    } catch (error) {
        console.error('Health check hatası:', error);
        return null;
    }
}

async function uploadVideo(file, onProgress) {
    const formData = new FormData();
    formData.append('video', file);

    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        
        xhr.upload.onprogress = (event) => {
            if (event.lengthComputable && onProgress) {
                const percent = Math.round((event.loaded / event.total) * 100);
                onProgress(percent);
            }
        };

        xhr.onload = () => {
            if (xhr.status === 200) {
                const blob = xhr.response;
                const jobId = xhr.getResponseHeader('X-Job-Id');
                const procTime = xhr.getResponseHeader('X-Processing-Time');
                resolve({ blob, jobId, procTime });
            } else if (xhr.status === 429) {
                reject(new Error('Başka bir video işleniyor. Lütfen bekleyin.'));
            } else {
                try {
                    const err = JSON.parse(xhr.responseText);
                    reject(new Error(err.detail || 'Yükleme hatası'));
                } catch {
                    reject(new Error('Sunucu hatası'));
                }
            }
        };

        xhr.onerror = () => reject(new Error('Bağlantı hatası'));
        xhr.ontimeout = () => reject(new Error('Zaman aşımı'));

        xhr.open('POST', `${BASE}/test`);
        xhr.responseType = 'blob';
        xhr.timeout = 600000;
        xhr.send(formData);
    });
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
