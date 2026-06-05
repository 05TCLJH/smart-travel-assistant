/**
 * 会话级密钥配置界面控制器，负责校验、回填与状态展示。
 */
const RuntimeConfigController = (() => {
    const FIELD_MAP = {
        amap_api_key: { inputId: 'amap-key-input', errorId: 'amap-key-error', hintId: 'amap-config-hint' },
        bailian_api_key: { inputId: 'bailian-key-input', errorId: 'bailian-key-error', hintId: 'bailian-config-hint' },
    };

    function bindField(specId) {
        const field = FIELD_MAP[specId];
        if (!field) return;
        const input = document.getElementById(field.inputId);
        if (!input) return;
        const validateAndPaint = () => {
            const value = input.value;
            if (!value.trim()) {
                clearFieldError(specId);
                return;
            }
            const { valid, issue } = RuntimeKeyValidator.validate(specId, value);
            if (valid) clearFieldError(specId);
            else setFieldError(specId, issue.message);
        };
        input.addEventListener('input', validateAndPaint);
        input.addEventListener('blur', validateAndPaint);
    }

    function setFieldError(specId, message) {
        const field = FIELD_MAP[specId];
        if (!field) return;
        const input = document.getElementById(field.inputId);
        const errorEl = document.getElementById(field.errorId);
        if (input) input.classList.add('config-input--invalid');
        if (errorEl) {
            errorEl.textContent = message;
            errorEl.hidden = false;
        }
    }

    function clearFieldError(specId) {
        const field = FIELD_MAP[specId];
        if (!field) return;
        const input = document.getElementById(field.inputId);
        const errorEl = document.getElementById(field.errorId);
        if (input) input.classList.remove('config-input--invalid');
        if (errorEl) {
            errorEl.textContent = '';
            errorEl.hidden = true;
        }
    }

    function clearAllFieldErrors() {
        Object.keys(FIELD_MAP).forEach(clearFieldError);
    }

    function getKeyValidationStatus(specId, rawValue) {
        const spec = RuntimeKeyRegistry.getSpec(specId);
        const raw = String(rawValue || '');
        const value = raw.trim();
        if (!spec) {
            return { specId, label: specId, status: 'unknown', valid: true, message: '' };
        }
        if (!value) {
            return {
                specId,
                label: spec.label,
                status: 'missing',
                valid: false,
                message: specId === 'bailian_api_key' ? '百炼 Key 未填写，请补充。' : '高德地图 Key 未填写，请补充。',
            };
        }
        const result = RuntimeKeyValidator.validate(specId, raw);
        if (result.valid) {
            return { specId, label: spec.label, status: 'valid', valid: true, message: '' };
        }
        return {
            specId,
            label: spec.label,
            status: 'invalid',
            valid: false,
            message: result.issue?.message || `${spec.label} 格式不正确`,
        };
    }

    function getKeyValidationSnapshot(state = RuntimeSessionKeys.getState()) {
        return {
            amap: getKeyValidationStatus('amap_api_key', state?.amap_api_key || ''),
            bailian: getKeyValidationStatus('bailian_api_key', state?.bailian_api_key || ''),
        };
    }

    function getBlockingIssues(snapshot) {
        return Object.values(snapshot || {}).filter((item) => item && item.status !== 'valid');
    }

    function formatValidationIssues(snapshot) {
        return getBlockingIssues(snapshot)
            .map((item) => item.message)
            .filter(Boolean)
            .join('；');
    }

    function setRequiredBanner(message, tone = 'warning') {
        const banner = document.getElementById('config-required-banner');
        if (!banner) return;
        const text = String(message || '').trim();
        if (!text) {
            banner.textContent = '';
            banner.hidden = true;
            banner.classList.remove('is-ready', 'is-error');
            return;
        }
        banner.hidden = false;
        banner.textContent = text;
        banner.classList.toggle('is-ready', tone === 'ready');
        banner.classList.toggle('is-error', tone === 'error');
    }

    function renderRequiredBanner(state) {
        const snapshot = getKeyValidationSnapshot(state);
        if (snapshot.amap.valid && snapshot.bailian.valid) {
            setRequiredBanner('高德地图 Key 和百炼 Key 已就绪，可以生成方案。', 'ready');
            return;
        }
        setRequiredBanner(formatValidationIssues(snapshot) || '请同时填写高德地图 Key 和百炼 Key，才能生成方案。', 'error');
    }

    function requireKeysForFeature(feature) {
        const snapshot = getKeyValidationSnapshot(RuntimeSessionKeys.getState());
        const featureName = String(feature || '').trim();
        if (featureName === 'trip') {
            if (snapshot.amap.valid && snapshot.bailian.valid) return true;
            getBlockingIssues(snapshot).forEach((item) => setFieldError(item.specId, item.message));
            const message = formatValidationIssues(snapshot) || '请同时填写高德地图 Key 和百炼 Key，才能生成方案。';
            setRequiredBanner(message, 'error');
            showNotification(message, 'error', 7000);
            return false;
        }
        if (featureName === 'vision') {
            if (snapshot.bailian.valid) return true;
            setFieldError('bailian_api_key', snapshot.bailian.message);
            setRequiredBanner(snapshot.bailian.message, 'error');
            showNotification(snapshot.bailian.message, 'error', 7000);
            return false;
        }
        return true;
    }

    function applyServerValidationErrors(errors) {
        if (!errors || typeof errors !== 'object') return;
        Object.entries(errors).forEach(([field, issue]) => {
            const message = issue?.message || '格式不正确';
            setFieldError(field, message);
        });
    }

    function renderHints() {
        const amapSpec = RuntimeKeyRegistry.getSpec('amap_api_key');
        const bailianSpec = RuntimeKeyRegistry.getSpec('bailian_api_key');
        const amapHint = document.getElementById('amap-config-hint');
        const bailianHint = document.getElementById('bailian-config-hint');
        const state = RuntimeSessionKeys.getState();
        const snapshot = getKeyValidationSnapshot(state);

        if (amapHint) {
            const text = buildFieldHintText(amapSpec, snapshot.amap);
            amapHint.textContent = text;
            amapHint.hidden = !text;
        }
        if (bailianHint) {
            const text = buildFieldHintText(bailianSpec, snapshot.bailian);
            bailianHint.textContent = text;
            bailianHint.hidden = !text;
        }

        renderRequiredBanner(state);
        renderDocLinks();
    }

    function buildFieldHintText(spec, snapshot) {
        if (snapshot.status === 'valid') {
            return spec?.id === 'bailian_api_key' ? '百炼 Key 校验通过。' : '高德地图 Key 校验通过。';
        }
        if (snapshot.status === 'missing') {
            return spec?.id === 'bailian_api_key' ? '百炼 Key 未填写，请补充。' : '高德地图 Key 未填写，请补充。';
        }
        return '';
    }

    function renderDocLinks() {
        const linkIds = { amap_api_key: 'amap-doc-link', bailian_api_key: 'bailian-doc-link' };
        Object.entries(linkIds).forEach(([specId, linkId]) => {
            const spec = RuntimeKeyRegistry.getSpec(specId);
            const link = document.getElementById(linkId);
            if (link && spec?.doc_url) link.href = spec.doc_url;
        });
    }

    async function save() {
        const payload = RuntimeSessionKeys.syncStorageFromInputs();
        if (!payload.has_any) {
            renderHints();
            if (typeof window.updateConfigBriefSummary === 'function') {
                window.updateConfigBriefSummary(window.getSystemStatus?.() || null);
            }
            showNotification('本次会话 Key 已清空。', 'info');
            return;
        }

        const clientErrors = RuntimeKeyValidator.validatePayload(RuntimeSessionKeys.buildRequestPayload(payload));
        if (Object.keys(clientErrors).length) {
            applyServerValidationErrors(clientErrors);
            const message = Object.values(clientErrors).map((item) => item?.message).filter(Boolean).join('；') || '请先修正 Key。';
            setRequiredBanner(message, 'error');
            showNotification(message, 'error', 7000);
            return;
        }

        clearAllFieldErrors();
        renderHints();
        if (typeof window.updateConfigBriefSummary === 'function') {
            window.updateConfigBriefSummary(window.getSystemStatus?.() || null);
        }
        if (typeof window.updateSystemUI === 'function' && typeof window.getSystemStatus === 'function') {
            const status = window.getSystemStatus();
            if (status) window.updateSystemUI(status);
        }
        showNotification('Key 已保存到当前浏览器会话。', 'info', 5000);
    }

    async function init() {
        await RuntimeKeyRegistry.loadSpecs();
        renderDocLinks();
        RuntimeSessionKeys.syncInputsFromStorage();
        RuntimeSessionKeys.bindInputs();
        bindField('amap_api_key');
        bindField('bailian_api_key');
        const saveBtn = document.getElementById('save-config-btn');
        if (saveBtn) saveBtn.addEventListener('click', () => save());
        renderHints();
        if (typeof window.updateConfigBriefSummary === 'function') {
            window.updateConfigBriefSummary(window.getSystemStatus?.() || null);
        }
    }

    return { init, renderHints, save, requireKeysForFeature, renderRequiredBanner };
})();

window.RuntimeConfigController = RuntimeConfigController;
