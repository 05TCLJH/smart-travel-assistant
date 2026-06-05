/**
 * 总执行流程图可视化，负责主流程节点高亮与状态联动。
 */
(function execFlowVizIIFE() {
    const STAGE_ORDER = ['intent', 'research', 'food', 'planner', 'transport', 'budget', 'supervisor'];

    function inferStageFromMessage(message) {
        const m = String(message || '');
        if (m.includes('Intent Agent')) return 'intent';
        if (m.includes('Research Agent')) return 'research';
        if (m.includes('Food Agent')) return 'food';
        if (m.includes('Planner Agent')) return 'planner';
        if (m.includes('Transport/Lodging')) return 'transport';
        if (m.includes('Budget Reviewer')) return 'budget';
        if (m.includes('Supervisor Agent')) return 'supervisor';
        if (m.includes('Vision Agent')) return 'vision';
        return null;
    }

    function resetExecFlowViz() {
        window.__execFlowTouched = new Set();
        const root = document.getElementById('exec-flow-viz');
        if (root) {
            root.classList.remove('exec-flow-viz--done', 'exec-flow-viz--error', 'exec-flow-viz--cancelled');
        }
        STAGE_ORDER.forEach((id) => {
            const el = document.querySelector(`.exec-flow-node[data-stage="${id}"]`);
            if (el) {
                el.classList.remove('exec-flow-node--active', 'exec-flow-node--touched');
            }
        });
        const vision = document.querySelector('.exec-flow-node[data-stage="vision"]');
        if (vision) vision.classList.remove('exec-flow-node--active', 'exec-flow-node--touched');
        const cap = document.getElementById('exec-flow-caption');
        if (cap) cap.textContent = '任务已创建，等待流水线启动…';
    }

    function applyExecFlowStage(stage, message) {
        if (stage === 'done') {
            finishExecFlowViz(true);
            const cap = document.getElementById('exec-flow-caption');
            if (cap) cap.textContent = message || '旅行方案生成完成';
            return;
        }
        if (stage === 'error') {
            finishExecFlowViz(false);
            const cap = document.getElementById('exec-flow-caption');
            if (cap) cap.textContent = message || '生成失败';
            return;
        }
        if (stage === 'cancelled') {
            finishExecFlowVizCancelled();
            const cap = document.getElementById('exec-flow-caption');
            if (cap) cap.textContent = message || '已终止生成';
            return;
        }

        if (!stage) {
            const cap = document.getElementById('exec-flow-caption');
            if (cap && message) cap.textContent = message;
            return;
        }

        window.__execFlowTouched = window.__execFlowTouched || new Set();
        window.__execFlowTouched.add(stage);
        const parallelRf = stage === 'research' || stage === 'food';
        if (parallelRf) {
            window.__execFlowTouched.add('research');
            window.__execFlowTouched.add('food');
        }

        STAGE_ORDER.forEach((id) => {
            const el = document.querySelector(`.exec-flow-node[data-stage="${id}"]`);
            if (!el) return;
            const isActive = parallelRf ? id === 'research' || id === 'food' : id === stage;
            el.classList.toggle('exec-flow-node--active', isActive);
            el.classList.toggle('exec-flow-node--touched', window.__execFlowTouched.has(id));
        });
        const vision = document.querySelector('.exec-flow-node[data-stage="vision"]');
        if (vision) {
            vision.classList.toggle('exec-flow-node--active', stage === 'vision');
            vision.classList.toggle('exec-flow-node--touched', window.__execFlowTouched.has('vision'));
        }

        const cap = document.getElementById('exec-flow-caption');
        if (cap) cap.textContent = message || '执行中…';
    }

    function finishExecFlowVizCancelled() {
        const root = document.getElementById('exec-flow-viz');
        if (root) {
            root.classList.remove('exec-flow-viz--done', 'exec-flow-viz--error');
            root.classList.add('exec-flow-viz--cancelled');
        }
        STAGE_ORDER.forEach((id) => {
            const el = document.querySelector(`.exec-flow-node[data-stage="${id}"]`);
            if (!el) return;
            el.classList.remove('exec-flow-node--active');
        });
        const vision = document.querySelector('.exec-flow-node[data-stage="vision"]');
        if (vision) vision.classList.remove('exec-flow-node--active');
    }

    function finishExecFlowViz(success) {
        const root = document.getElementById('exec-flow-viz');
        if (root) {
            root.classList.remove('exec-flow-viz--cancelled');
            root.classList.toggle('exec-flow-viz--done', !!success);
            root.classList.toggle('exec-flow-viz--error', !success);
        }
        STAGE_ORDER.forEach((id) => {
            const el = document.querySelector(`.exec-flow-node[data-stage="${id}"]`);
            if (!el) return;
            el.classList.remove('exec-flow-node--active');
            if (success) el.classList.add('exec-flow-node--touched');
        });
        const vision = document.querySelector('.exec-flow-node[data-stage="vision"]');
        if (vision) vision.classList.remove('exec-flow-node--active');
    }

    window.resetExecFlowViz = resetExecFlowViz;
    window.applyExecFlowStage = applyExecFlowStage;
    window.finishExecFlowViz = finishExecFlowViz;
    window.finishExecFlowVizCancelled = finishExecFlowVizCancelled;
    window.inferStageFromMessage = inferStageFromMessage;
})();
