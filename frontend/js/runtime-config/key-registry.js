/**
 * 运行时密钥规范注册表，启动时从后端加载并与后端规则保持一致。
 */
const RuntimeKeyRegistry = (() => {
    let specsById = {};
    let loadPromise = null;

    async function loadSpecs() {
        if (loadPromise) return loadPromise;
        loadPromise = (async () => {
            try {
                const response = await api.get('/api/system/key-specs');
                const list = response?.data?.specs;
                if (response?.success && Array.isArray(list)) {
                    specsById = Object.fromEntries(list.map((item) => [item.id, item]));
                    return specsById;
                }
            } catch (error) {
                console.warn('load key specs failed, using embedded fallback', error);
            }
            specsById = getEmbeddedSpecs();
            return specsById;
        })();
        return loadPromise;
    }

    function getEmbeddedSpecs() {
        return {
            amap_api_key: {
                id: 'amap_api_key',
                label: '高德地图 Key',
                pattern: '^[0-9a-fA-F]{32}$',
                format_hint: '32 位十六进制字符（仅 0-9、a-f），无空格与引号',
                doc_url: 'https://lbs.amap.com/api/webservice/guide/create-project/get-key',
                min_length: 32,
                max_length: 32,
            },
            bailian_api_key: {
                id: 'bailian_api_key',
                label: '百炼 / DashScope API Key',
                pattern: '^sk-[0-9a-fA-F]{32}$',
                format_hint: '以 sk- 开头，后接 32 位十六进制',
                doc_url: 'https://help.aliyun.com/zh/model-studio/get-api-key',
                min_length: 35,
                max_length: 35,
            },
        };
    }

    function getSpec(id) {
        return specsById[id] || null;
    }

    function allSpecs() {
        return { ...specsById };
    }

    return { loadSpecs, getSpec, allSpecs };
})();

window.RuntimeKeyRegistry = RuntimeKeyRegistry;
