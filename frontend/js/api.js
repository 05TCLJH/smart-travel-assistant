// 前端 API 客户端，包含带凭据的 fetch 和 SSE 辅助能力。

function resolveApiBaseUrl() {
    const configured = String(window.__SMART_TRAVEL_CONFIG?.apiBaseUrl || '').trim();
    if (configured && configured !== '__API_BASE_URL__') {
        return configured.replace(/\/+$/, '');
    }
    return window.location.origin;
}

const API_BASE_URL = resolveApiBaseUrl();
const API_TIMEOUT = 30000;

class ApiClient {
    constructor() {
        this.baseURL = API_BASE_URL;
        this.defaultHeaders = { 'Content-Type': 'application/json' };
        this.defaultCredentials = 'include';
    }

    resolveUrl(endpoint) {
        return typeof endpoint === 'string' && (endpoint.startsWith('http://') || endpoint.startsWith('https://'))
            ? endpoint
            : `${this.baseURL}${endpoint}`;
    }

    extractDownloadFilename(response, fallback = 'download.pdf') {
        const disposition = response.headers.get('Content-Disposition') || '';
        const utf8Match = disposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
        if (utf8Match?.[1]) {
            try {
                return decodeURIComponent(utf8Match[1].trim());
            } catch (error) {
                console.warn('decode filename* failed', error);
            }
        }

        const plainMatch = disposition.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/i);
        const filename = plainMatch?.[1] || plainMatch?.[2];
        return filename ? filename.trim() : fallback;
    }

    saveBlob(blob, filename) {
        const objectUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 1000);
    }

    async request(endpoint, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), options.timeout || API_TIMEOUT);

        try {
            const response = await fetch(this.resolveUrl(endpoint), {
                headers: { ...this.defaultHeaders, ...options.headers },
                signal: controller.signal,
                credentials: options.credentials || this.defaultCredentials,
                ...options,
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                let errorData = {};
                try {
                    errorData = await response.json();
                } catch (error) {
                    void error;
                }

                const errorMessage = errorData.detail || errorData.message || `HTTP ${response.status}: ${response.statusText}`;
                const err = new Error(errorMessage);
                err.data = errorData.data || errorData;
                err.status = response.status;
                throw err;
            }

            return options.responseType === 'blob' ? response.blob() : response.json();
        } catch (error) {
            clearTimeout(timeoutId);

            if (error.name === 'AbortError') {
                throw new Error('Request timed out, please try again.');
            }

            if (String(error.message || '').includes('Failed to fetch') || String(error.message || '').includes('NetworkError')) {
                throw new Error('Network request failed, please check the backend service and browser origin settings.');
            }

            throw error;
        }
    }

    async get(endpoint, params = {}) {
        const queryString = new URLSearchParams(params).toString();
        return this.request(queryString ? `${endpoint}?${queryString}` : endpoint, { method: 'GET' });
    }

    async post(endpoint, data = {}, options = {}) {
        return this.request(endpoint, { method: 'POST', body: JSON.stringify(data), ...options });
    }

    async put(endpoint, data = {}) {
        return this.request(endpoint, { method: 'PUT', body: JSON.stringify(data) });
    }

    async upload(endpoint, file, extraData = {}) {
        const formData = new FormData();
        formData.append('file', file);
        Object.entries(extraData).forEach(([key, value]) => {
            formData.append(key, typeof value === 'object' ? JSON.stringify(value) : value);
        });
        const response = await fetch(this.resolveUrl(endpoint), {
            method: 'POST',
            body: formData,
            credentials: this.defaultCredentials,
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || 'Upload failed');
        }
        return response.json();
    }

    connectSSE(endpoint, onMessage, onComplete, onError, onCancelled) {
        let eventSource = null;
        let finishedGracefully = false;
        let reconnectTimer = null;
        let progressCount = 0;
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 5;

        const buildReconnectUrl = () => {
            const url = new URL(this.resolveUrl(endpoint), window.location.origin);
            if (progressCount > 0) {
                url.searchParams.set('after', String(progressCount));
            }
            return url.toString();
        };

        const clearReconnectTimer = () => {
            if (reconnectTimer) {
                window.clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        const closeGracefully = () => {
            finishedGracefully = true;
            clearReconnectTimer();
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
        };

        const openEventSource = () => {
            clearReconnectTimer();
            if (finishedGracefully) return;
            eventSource = new EventSource(buildReconnectUrl(), { withCredentials: true });

            eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    reconnectAttempts = 0;
                    if (data.type === 'progress') {
                        progressCount += 1;
                        onMessage(data);
                    } else if (data.type === 'complete') {
                        closeGracefully();
                        if (data.result == null || data.result === undefined) {
                            onError(new Error('Trip generation completed without a final result payload.'));
                            return;
                        }
                        onComplete(data.result);
                    } else if (data.type === 'error') {
                        closeGracefully();
                        onError(new Error(data.message));
                    } else if (data.type === 'cancelled') {
                        closeGracefully();
                        if (typeof onCancelled === 'function') {
                            onCancelled(data.message || '');
                        }
                    }
                } catch (error) {
                    console.error('SSE parse error:', error);
                }
            };

            eventSource.onerror = () => {
                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                }
                if (finishedGracefully) return;
                if (reconnectAttempts >= maxReconnectAttempts) {
                    onError(new Error('SSE connection was interrupted for too long. The task may still be running, please retry.'));
                    return;
                }
                const delayMs = Math.min(8000, 1000 * (2 ** reconnectAttempts));
                reconnectAttempts += 1;
                reconnectTimer = window.setTimeout(() => {
                    openEventSource();
                }, delayMs);
            };
        };

        openEventSource();
        return {
            close: closeGracefully,
            get eventSource() {
                return eventSource;
            },
        };
    }

    async downloadFile(endpoint, filename = 'download.pdf') {
        return this.download(endpoint, { filename });
    }

    async download(endpoint, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), options.timeout || API_TIMEOUT);
        const hasJsonBody = Object.prototype.hasOwnProperty.call(options, 'data');
        const headers = hasJsonBody
            ? { ...this.defaultHeaders, ...(options.headers || {}) }
            : { ...(options.headers || {}) };

        try {
            const response = await fetch(this.resolveUrl(endpoint), {
                method: options.method || 'GET',
                headers,
                body: hasJsonBody ? JSON.stringify(options.data) : options.body,
                signal: controller.signal,
                credentials: options.credentials || this.defaultCredentials,
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                let errorMessage = 'Download failed';
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorData.message || errorMessage;
                } catch (jsonError) {
                    const text = await response.text().catch(() => '');
                    if (text) errorMessage = text;
                    console.warn('download error payload parse failed', jsonError);
                }
                throw new Error(errorMessage);
            }

            const blob = await response.blob();
            const resolvedFilename = this.extractDownloadFilename(response, options.filename || 'download.pdf');
            this.saveBlob(blob, resolvedFilename);
            return { filename: resolvedFilename };
        } catch (error) {
            clearTimeout(timeoutId);

            if (error.name === 'AbortError') {
                throw new Error('Download timed out, please retry.');
            }

            if (String(error.message || '').includes('Failed to fetch') || String(error.message || '').includes('NetworkError')) {
                throw new Error('Download request failed, please check browser origin and backend availability.');
            }

            throw error;
        }
    }
}

const api = new ApiClient();
window.api = api;
