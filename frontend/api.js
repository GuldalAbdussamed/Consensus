const API_BASE_URL = 'http://localhost:8080';

async function checkHealth() {
    try {
        const response = await fetch(`${API_BASE_URL}/health`);
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
                try {
                    const response = JSON.parse(xhr.responseText);
                    resolve(response);
                } catch {
                    reject(new Error('Sunucu geçersiz yanıt döndürdü'));
                }
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

        xhr.open('POST', `${API_BASE_URL}/upload`);
        xhr.timeout = 300000; // 5 min for upload
        xhr.send(formData);
    });
}

async function pollJobStatus(jobId) {
    try {
        const response = await fetch(`${API_BASE_URL}/status/${jobId}`);
        if (!response.ok) throw new Error('Status kontrol hatası');
        return await response.json();
    } catch (error) {
        console.error('Poll hatası:', error);
        return null;
    }
}

async function downloadJob(jobId, filename) {
    const response = await fetch(`${API_BASE_URL}/download/${jobId}`);
    if (!response.ok) throw new Error('İndirme hatası');
    const blob = await response.blob();
    downloadBlob(blob, filename);
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
