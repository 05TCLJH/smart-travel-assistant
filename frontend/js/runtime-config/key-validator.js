/**
 * 客户端密钥校验逻辑，与后端规则保持一致。
 */
const RuntimeKeyValidator = (() => {
    function getFieldLabel(specId) {
        if (specId === 'amap_api_key') return '高德地图 Key';
        if (specId === 'bailian_api_key') return '百炼 Key';
        return 'API Key';
    }

    function buildEmptyMessage(specId) {
        return `${getFieldLabel(specId)} 未填写，请补充。`;
    }

    function buildFormatMessage(specId) {
        if (specId === 'amap_api_key') {
            return '高德地图 Key 格式不正确，请检查是否包含空格、引号或复制不完整。';
        }
        if (specId === 'bailian_api_key') {
            return '百炼 Key 格式不正确，请检查是否以 sk- 开头，以及后续字符长度和内容是否正确。';
        }
        return 'API Key 格式不正确，请检查后重试。';
    }

    function normalize(value) {
        return String(value ?? '');
    }

    function validate(specId, rawValue) {
        const spec = RuntimeKeyRegistry.getSpec(specId);
        if (!spec) {
            return { valid: true, issue: null };
        }
        const value = normalize(rawValue);
        const trimmed = value.trim();
        if (!trimmed) {
            return { valid: false, issue: { code: 'empty', message: buildEmptyMessage(specId) } };
        }
        if (value !== trimmed || /["']/.test(value) || /\s/.test(value)) {
            return {
                valid: false,
                issue: {
                    code: 'invalid_format',
                    message: buildFormatMessage(specId),
                },
            };
        }
        if (value.length < spec.min_length || value.length > spec.max_length) {
            return {
                valid: false,
                issue: { code: 'invalid_format', message: buildFormatMessage(specId) },
            };
        }
        const regex = new RegExp(spec.pattern);
        if (!regex.test(value)) {
            return {
                valid: false,
                issue: {
                    code: 'invalid_format',
                    message: buildFormatMessage(specId),
                },
            };
        }
        return { valid: true, issue: null };
    }

    function validatePayload(payload) {
        const errors = {};
        if (payload.amap_api_key) {
            const result = validate('amap_api_key', payload.amap_api_key);
            if (!result.valid) errors.amap_api_key = result.issue;
        }
        if (payload.bailian_api_key) {
            const result = validate('bailian_api_key', payload.bailian_api_key);
            if (!result.valid) errors.bailian_api_key = result.issue;
        }
        return errors;
    }

    return { validate, validatePayload, normalize };
})();

window.RuntimeKeyValidator = RuntimeKeyValidator;
