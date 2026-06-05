/**
 * 浏览器会话级 Key 管理器。
 * 仅使用 sessionStorage，不会落到后端或长期存储。
 */
const RuntimeSessionKeys = (() => {
    const STORAGE_KEYS = {
        amap_api_key: 'smart-travel-session-amap-key',
        bailian_api_key: 'smart-travel-session-bailian-key',
    };

    const FIELD_IDS = {
        amap_api_key: 'amap-key-input',
        bailian_api_key: 'bailian-key-input',
    };

    function normalize(value) {
        return String(value || '').trim();
    }

    function safeGet(key) {
        try {
            return sessionStorage.getItem(key) || '';
        } catch (error) {
            return '';
        }
    }

    function safeSet(key, value) {
        try {
            if (value) sessionStorage.setItem(key, value);
            else sessionStorage.removeItem(key);
        } catch (error) {
            // sessionStorage 在隐私模式/受限环境下可能不可用，静默降级即可。
        }
    }

    function getState() {
        const amap_api_key = safeGet(STORAGE_KEYS.amap_api_key);
        const bailian_api_key = safeGet(STORAGE_KEYS.bailian_api_key);
        return {
            amap_api_key,
            bailian_api_key,
            has_amap: Boolean(amap_api_key),
            has_bailian: Boolean(bailian_api_key),
            has_any: Boolean(amap_api_key || bailian_api_key),
        };
    }

    function setState(state = {}) {
        safeSet(STORAGE_KEYS.amap_api_key, normalize(state.amap_api_key));
        safeSet(STORAGE_KEYS.bailian_api_key, normalize(state.bailian_api_key));
    }

    function syncInputsFromStorage() {
        const state = getState();
        const amapInput = document.getElementById(FIELD_IDS.amap_api_key);
        const bailianInput = document.getElementById(FIELD_IDS.bailian_api_key);
        if (amapInput) amapInput.value = state.amap_api_key;
        if (bailianInput) bailianInput.value = state.bailian_api_key;
        return state;
    }

    function syncStorageFromInputs() {
        const amapValue = normalize(document.getElementById(FIELD_IDS.amap_api_key)?.value);
        const bailianValue = normalize(document.getElementById(FIELD_IDS.bailian_api_key)?.value);
        setState({ amap_api_key: amapValue, bailian_api_key: bailianValue });
        return getState();
    }

    function bindInputs() {
        Object.values(FIELD_IDS).forEach((inputId) => {
            const input = document.getElementById(inputId);
            if (!input) return;
            const persist = () => {
                syncStorageFromInputs();
                if (window.RuntimeConfigController?.renderHints) {
                    window.RuntimeConfigController.renderHints(window.getSystemStatus?.() || null);
                }
                if (typeof window.updateConfigBriefSummary === 'function') {
                    window.updateConfigBriefSummary(window.getSystemStatus?.() || null);
                }
            };
            input.addEventListener('input', persist);
            input.addEventListener('change', persist);
        });
    }

    function buildRequestPayload(payload = {}) {
        const state = getState();
        const body = { ...payload };
        delete body.has_amap;
        delete body.has_bailian;
        delete body.has_any;
        return {
            ...body,
            ...(state.amap_api_key ? { amap_api_key: state.amap_api_key } : {}),
            ...(state.bailian_api_key ? { bailian_api_key: state.bailian_api_key } : {}),
        };
    }

    function buildFormData(extraData = {}) {
        return buildRequestPayload(extraData);
    }

    function appendToUrl(url) {
        return url;
    }

    function hasAny() {
        return getState().has_any;
    }

    return {
        bindInputs,
        getState,
        setState,
        syncInputsFromStorage,
        syncStorageFromInputs,
        buildRequestPayload,
        buildFormData,
        appendToUrl,
        hasAny,
    };
})();

window.RuntimeSessionKeys = RuntimeSessionKeys;
