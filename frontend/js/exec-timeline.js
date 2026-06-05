/**
 * 结构化执行时间线，与宏观流程图并排展示。
 */
(function () {
    const STAGE_LABELS = {
        intent: '意图',
        research: '调研',
        food: '美食',
        planner: '规划',
        transport: '住行',
        budget: '预算',
        supervisor: '审阅',
    };

    const STATUS_LABELS = {
        pending: '待执行',
        running: '进行中',
        done: '完成',
        error: '失败',
        cancelled: '已终止',
    };

    let catalogSteps = [];
    let stepState = {};
    let showPending = false;
    let listEl = null;
    let hintEl = null;
    let toggleEl = null;

    function normalizeEvent(raw) {
        const isStr = typeof raw === 'string';
        const message = isStr ? raw : String(raw?.message || '');
        const stage = isStr ? null : raw?.stage ?? null;
        const stepId = isStr ? null : raw?.step_id ?? null;
        const status = (isStr ? 'running' : raw?.status || 'running').toLowerCase();
        const label = isStr ? null : raw?.label ?? null;
        return { message, stage, step_id: stepId, status, label };
    }

    function inferStageFromStep(stepId) {
        if (!stepId || !String(stepId).includes('.')) return null;
        return String(stepId).split('.')[0];
    }

    function groupCatalog(steps) {
        const groups = new Map();
        steps.forEach((step) => {
            const stage = step.stage || 'research';
            if (!groups.has(stage)) groups.set(stage, []);
            groups.get(stage).push(step);
        });
        groups.forEach((items) => items.sort((a, b) => (a.order || 0) - (b.order || 0)));
        return groups;
    }

    function touchedCount() {
        return Object.values(stepState).filter((s) => s.status && s.status !== 'pending').length;
    }

    function ensureDom() {
        listEl = document.getElementById('exec-timeline-list');
        hintEl = document.getElementById('exec-timeline-hint');
        toggleEl = document.getElementById('exec-timeline-show-pending');
        if (toggleEl && !toggleEl.dataset.bound) {
            toggleEl.dataset.bound = '1';
            toggleEl.addEventListener('change', () => {
                showPending = Boolean(toggleEl.checked);
                renderTimeline();
            });
        }
    }

    function renderTimeline() {
        ensureDom();
        if (!listEl) return;

        const groups = groupCatalog(catalogSteps);
        const stageOrder = ['intent', 'research', 'food', 'planner', 'transport', 'budget', 'supervisor'];
        const fragments = [];

        stageOrder.forEach((stage) => {
            const steps = groups.get(stage) || [];
            if (!steps.length) return;
            const visible = steps.filter((step) => {
                const st = stepState[step.step_id];
                if (showPending) return true;
                return st && st.status !== 'pending';
            });
            if (!visible.length) return;

            const rows = visible
                .map((step) => {
                    const st = stepState[step.step_id] || { status: 'pending', message: '' };
                    const status = st.status || 'pending';
                    const detail = st.message ? `<span class="exec-timeline-step__detail">${escapeHtml(st.message)}</span>` : '';
                    return `
                        <li class="exec-timeline-step exec-timeline-step--${status}" data-step-id="${escapeHtml(step.step_id)}">
                            <span class="exec-timeline-step__dot" aria-hidden="true"></span>
                            <span class="exec-timeline-step__body">
                                <span class="exec-timeline-step__title">${escapeHtml(step.label)}</span>
                                <span class="exec-timeline-step__status">${escapeHtml(STATUS_LABELS[status] || status)}</span>
                                ${detail}
                            </span>
                        </li>`;
                })
                .join('');

            fragments.push(`
                <section class="exec-timeline-stage" data-stage="${stage}">
                    <h4 class="exec-timeline-stage__title">${escapeHtml(STAGE_LABELS[stage] || stage)}</h4>
                    <ol class="exec-timeline-stage__steps">${rows}</ol>
                </section>`);
        });

        listEl.innerHTML = fragments.join('') || '<p class="exec-timeline-empty">等待执行事件...</p>';
        if (hintEl) {
            const n = touchedCount();
            hintEl.textContent = n ? `已完成或进行中的步骤：${n}` : '展开查看各 Agent 内部步骤';
        }
        const active = listEl.querySelector('.exec-timeline-step--running');
        if (active) {
            requestAnimationFrame(() => active.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
        }
    }

    function escapeHtml(text) {
        return String(text || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function loadCatalog() {
        if (catalogSteps.length) return catalogSteps;
        try {
            const res = await fetch('/api/system/progress-catalog');
            if (res.ok) {
                const body = await res.json();
                const steps = body?.data?.steps;
                if (Array.isArray(steps) && steps.length) {
                    catalogSteps = steps;
                    return catalogSteps;
                }
            }
        } catch (_err) {
            /* 继续使用下方内置兜底数据 */
        }
        catalogSteps = [
            { step_id: 'intent.parse', stage: 'intent', label: '解析出行需求', order: 10 },
            { step_id: 'intent.policy', stage: 'intent', label: '生成路由策略', order: 20 },
            { step_id: 'research.weather', stage: 'research', label: '获取天气', order: 30 },
            { step_id: 'research.geocode', stage: 'research', label: '地理编码', order: 40 },
            { step_id: 'research.poi_search', stage: 'research', label: '检索候选景点', order: 50 },
            { step_id: 'research.poi_normalize', stage: 'research', label: '归一化与过滤', order: 60 },
            { step_id: 'research.poi_activity_load', stage: 'research', label: '标注活动负荷', order: 62 },
            { step_id: 'research.poi_cluster', stage: 'research', label: '景区簇去重', order: 65 },
            { step_id: 'research.poi_guard', stage: 'research', label: '候选合规检查', order: 70 },
            { step_id: 'research.summary', stage: 'research', label: '调研小结', order: 80 },
            { step_id: 'food.search', stage: 'food', label: '检索特色美食', order: 10 },
            { step_id: 'planner.think', stage: 'planner', label: '规划推理', order: 10 },
            { step_id: 'planner.expand', stage: 'planner', label: '扩展候选', order: 20 },
            { step_id: 'planner.trim', stage: 'planner', label: '收缩候选', order: 30 },
            { step_id: 'planner.cluster_layout', stage: 'planner', label: '按负荷排期', order: 35 },
            { step_id: 'planner.finalize', stage: 'planner', label: '生成行程草案', order: 40 },
            { step_id: 'transport.plan', stage: 'transport', label: '住行建议', order: 10 },
            { step_id: 'budget.review', stage: 'budget', label: '预算审阅', order: 10 },
            { step_id: 'supervisor.review', stage: 'supervisor', label: '总审查', order: 10 },
            { step_id: 'supervisor.reroute', stage: 'supervisor', label: '回流优化', order: 20 },
            { step_id: 'supervisor.finalize', stage: 'supervisor', label: '整理输出', order: 30 },
        ];
        return catalogSteps;
    }

    function applyProgressEvent(raw) {
        const ev = normalizeEvent(raw);
        const stepId = ev.step_id;
        if (stepId) {
            stepState[stepId] = {
                status: ev.status || 'running',
                message: ev.message,
                stage: ev.stage || inferStageFromStep(stepId),
                label: ev.label,
            };
        }
        renderTimeline();
        if (typeof applyExecFlowStage === 'function') {
            applyExecFlowStage(ev.stage, ev.message);
        }
    }

    async function resetExecTimeline() {
        stepState = {};
        showPending = false;
        ensureDom();
        if (toggleEl) toggleEl.checked = false;
        await loadCatalog();
        renderTimeline();
    }

    async function initExecTimeline() {
        ensureDom();
        await loadCatalog();
        renderTimeline();
    }

    window.initExecTimeline = initExecTimeline;
    window.resetExecTimeline = resetExecTimeline;
    window.applyProgressEvent = applyProgressEvent;
})();
