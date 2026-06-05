/**
 * 运行时服务失败文案解析，覆盖行程生成、景点识别与地图能力。
 * 规则与后端服务失败分类逻辑保持一致。
 */
const RuntimeServiceErrors = (() => {
    const AMAP_DOC = 'https://lbs.amap.com/api/webservice/guide/create-project/get-key';
    const BAILIAN_DOC = 'https://help.aliyun.com/zh/model-studio/get-api-key';

    function classify(message, hint = '') {
        const text = `${message || ''} ${hint || ''}`.trim();
        const lower = text.toLowerCase();

        if (
            /INVALID_USER_KEY|USERKEY|USER_KEY|10001|10002|10003/.test(text) ||
            (lower.includes('invalid') && lower.includes('key') && lower.includes('amap'))
        ) {
            return {
                service: 'amap',
                code: 'amap_key_invalid',
                title: '高德 Key 不可用',
                message: '高德地图 Key 格式正确，但当前不可用，请检查权限、服务开通状态或额度。',
                doc_url: AMAP_DOC,
            };
        }

        if (
            /配额|额度|限流|QPS|CUQPS|调用量|超限|10044|10045|10046/.test(text) ||
            /quota|rate limit|limit exceeded/i.test(text)
        ) {
            return {
                service: 'amap',
                code: 'amap_quota',
                title: '高德调用受限',
                message: '高德地图 Key 格式正确，但当前不可用，请检查权限、服务开通状态或额度。',
                doc_url: AMAP_DOC,
            };
        }

        if (
            /dashscope|bailian|aliyun/i.test(lower) &&
            /api\s*key|apikey|invalid|unauthorized|forbidden|permission|denied|401|403|402/i.test(lower)
        ) {
            return {
                service: 'bailian',
                code: 'bailian_key_invalid',
                title: '百炼 Key 不可用',
                message: 'DashScope API Key 格式正确，但当前不可用，请检查是否有效、是否已失效、是否有权限或是否已超出额度。',
                doc_url: BAILIAN_DOC,
            };
        }

        if (/未配置|未启用|not configured|disabled|not opened/i.test(text) && /bailian|vision|识别|dashscope/i.test(lower)) {
            return {
                service: 'bailian',
                code: 'bailian_not_configured',
                title: '百炼 Key 未配置',
                message: 'DashScope API Key 暂时无法验证可用性，请稍后重试。',
                doc_url: BAILIAN_DOC,
            };
        }

        if (/unexpected_eof|eof occurred|ssl\/tls eof/i.test(lower) || (lower.includes('ssl') && lower.includes('eof'))) {
            return {
                service: 'bailian',
                code: 'bailian_network_ssl',
                title: '视觉模型连接中断',
                message:
                    '与 DashScope 的 HTTPS 连接在传输时被中断。请将图片压缩到 4MB 以内（建议 JPG）、检查代理/防火墙，或稍后重试。',
                doc_url: BAILIAN_DOC,
            };
        }

        if (/未配置高德|体验模式|演示数据|demo-local|MCP 未/i.test(text)) {
            return {
                service: 'amap',
                code: 'amap_not_configured',
                title: '高德 Key 未生效',
                message: '当前可能使用演示数据。请配置有效的高德 Key 后重新生成。',
                doc_url: AMAP_DOC,
            };
        }

        return {
            service: 'unknown',
            code: 'unknown',
            title: '无法验证可用性',
            message: text ? `${text}。暂时无法验证可用性，请稍后重试。` : '暂时无法验证可用性，请稍后重试。',
            doc_url: '',
        };
    }

    function notificationText(info) {
        if (!info || info.code === 'unknown') return info?.message || '当前无法验证可用性，请稍后重试';
        const doc = info.doc_url ? ` 详见官方文档。` : '';
        return `${info.title}：${info.message}${doc}`;
    }

    function formatForBanner(info) {
        if (!info?.doc_url) return info?.message || '';
        return `${info.message} <a href="${escapeHtml(info.doc_url)}" target="_blank" rel="noopener">查看官方说明</a>`;
    }

    return { classify, notificationText, formatForBanner };
})();

window.RuntimeServiceErrors = RuntimeServiceErrors;
