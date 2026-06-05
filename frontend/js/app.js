// 前端应用主脚本，负责页面交互、表单状态组织与行程结果渲染。
let activeTripSseConnection = null;
let tripGenerationFinish = null;
let tripStopHandled = false;
let resultSectionNavCleanup = null;

const RESULT_SECTION_DEFS = [
    { id: 'result-itinerary', label: '每日行程', render: (r) => renderItinerarySection(r.plan?.itinerary || []) },
    { id: 'result-weather', label: '天气', render: (r) => renderWeatherSection(r.weather || {}) },
    { id: 'result-map', label: '景点', render: (r) => renderMapSection(r.map_data || {}) },
    { id: 'result-food', label: '美食', render: (r) => renderFoodSection(r.food_recommendations || []) },
    {
        id: 'result-transport',
        label: '住行',
        render: (r) => renderTransportLodgingSection(r.transport_plan || {}, r.lodging_recommendations || []),
    },
    { id: 'result-budget', label: '预算', render: (r) => renderBudgetSection(r.plan || {}) },
    { id: 'result-tips', label: '提醒', render: (r) => renderTipsSection(r.tips?.tips || []) },
];

function setStageTaskPill(text, variant = 'muted') {
    const pill = document.getElementById('stage-task-pill');
    if (!pill) return;
    pill.textContent = text;
    pill.classList.remove('is-muted', 'is-running', 'is-done');
    if (variant === 'running') pill.classList.add('is-running');
    else if (variant === 'done') pill.classList.add('is-done');
    else pill.classList.add('is-muted');
}

function updateConfigBriefSummary(runtimeConfig) {
    const el = document.getElementById('config-brief-summary');
    if (!el) return;
    const state = RuntimeSessionKeys?.getState?.() || {};
    const amapIssue = describeKeyStatus('amap_api_key', state.amap_api_key);
    const bailianIssue = describeKeyStatus('bailian_api_key', state.bailian_api_key);
    const titleParts = [];
    if (amapIssue.status === 'invalid') titleParts.push(amapIssue.message);
    if (bailianIssue.status === 'invalid') titleParts.push(bailianIssue.message);
    el.title = titleParts.join('；');
    if (!state.has_any) {
        el.textContent = '未填写';
        el.classList.add('is-empty');
        el.classList.remove('is-ready', 'is-error');
        return;
    }
    const validCount = [amapIssue, bailianIssue].filter((item) => item.status === 'valid').length;
    const hasInvalid = amapIssue.status === 'invalid' || bailianIssue.status === 'invalid';
    el.textContent = hasInvalid ? '有待修正项' : `已填写 ${validCount} 项`;
    el.classList.toggle('is-empty', false);
    el.classList.toggle('is-error', hasInvalid);
    el.classList.toggle('is-ready', !hasInvalid && validCount > 0);
}

function describeKeyStatus(specId, rawValue) {
    const spec = RuntimeKeyRegistry?.getSpec?.(specId);
    const label = spec?.label || specId;
    const raw = String(rawValue || '');
    const value = raw.trim();
    if (!value) {
        return {
            status: 'missing',
            label,
            message: specId === 'bailian_api_key' ? '百炼 Key 未填写，请补充。' : '高德地图 Key 未填写，请补充。',
        };
    }
    const result = RuntimeKeyValidator.validate(specId, raw);
    if (result.valid) {
        return { status: 'valid', label, message: '' };
    }
    return { status: 'invalid', label, message: result.issue?.message || `${label} 格式不正确` };
}

function formatKeyBadge(status) {
    if (status.status === 'valid') return `${shortKeyLabel(status.label)}✓`;
    if (status.status === 'invalid') return `${shortKeyLabel(status.label)}⚠`;
    return `${shortKeyLabel(status.label)}—`;
}

function shortKeyLabel(label) {
    const text = String(label || '').trim();
    if (text.includes('高德')) return '高德';
    if (text.includes('百炼')) return '百炼';
    return text || 'Key';
}

function describeValidationErrors(errors) {
    const entries = Object.entries(errors || {});
    if (!entries.length) return '';
    return entries
        .map(([, issue]) => issue?.message || '请先检查 Key。')
        .join('；');
}

function wrapResultAccordion(id, title, bodyHtml, openByDefault = false) {
    if (!bodyHtml) return null;
    return {
        id,
        label: title,
        html: `<details class="result-accordion" id="${id}"${openByDefault ? ' open' : ''}><summary>${escapeHtml(title)}</summary><div class="result-accordion__body">${bodyHtml}</div></details>`,
    };
}

function unwrapStageSection(html) {
    const trimmed = String(html || '').trim();
    if (!trimmed) return '';
    const match = trimmed.match(/^<div class="stage-section">\s*<h4>[\s\S]*?<\/h4>/);
    if (!match) return trimmed;
    const end = trimmed.lastIndexOf('</div>');
    return end > match[0].length ? trimmed.slice(match[0].length, end).trim() : trimmed;
}

function setStagePanels({ empty, progress, result }) {
    const emptyStage = document.getElementById('empty-stage');
    const progressSection = document.getElementById('progress-section');
    const resultSection = document.getElementById('result-section');
    if (emptyStage) {
        emptyStage.classList.toggle('panel-hidden', !empty);
        if (empty) emptyStage.style.display = '';
    }
    if (progressSection) progressSection.classList.toggle('panel-hidden', !progress);
    if (resultSection) resultSection.classList.toggle('panel-hidden', !result);
}

function updateSilkNavOffset() {
    const dock = document.getElementById('silk-nav-dock');
    if (!dock || dock.classList.contains('panel-hidden')) return;
    const h = Math.ceil(dock.getBoundingClientRect().height) + 10;
    document.documentElement.style.setProperty('--silk-nav-offset', `${h}px`);
}

function moveSilkNavIndicator(activeBtn) {
    const indicator = document.getElementById('silk-nav-indicator');
    const body = document.querySelector('.silk-nav__body');
    if (!indicator || !body || !activeBtn) return;
    const bodyRect = body.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    indicator.style.left = `${btnRect.left - bodyRect.left}px`;
    indicator.style.width = `${btnRect.width}px`;
    indicator.classList.add('is-ready');
}

function bindSilkNavDock() {
    const dock = document.getElementById('silk-nav-dock');
    if (!dock || dock.dataset.bound === '1') return;
    const stageBody = dock.closest('.stage-body');
    if (!stageBody) return;

    let sentinel = dock.previousElementSibling;
    if (!sentinel || !sentinel.classList.contains('silk-nav-sentinel')) {
        sentinel = document.createElement('div');
        sentinel.className = 'silk-nav-sentinel';
        sentinel.setAttribute('aria-hidden', 'true');
        dock.parentElement?.insertBefore(sentinel, dock);
    }

    const syncFloat = () => {
        const stuck = stageBody.scrollTop > sentinel.offsetTop + 1;
        dock.classList.toggle('is-afloat', stuck);
        updateSilkNavOffset();
    };

    const observer = new IntersectionObserver(
        ([entry]) => {
            dock.classList.toggle('is-afloat', !entry.isIntersecting);
            updateSilkNavOffset();
        },
        { root: stageBody, threshold: 0 },
    );
    observer.observe(sentinel);
    stageBody.addEventListener('scroll', syncFloat, { passive: true });
    dock.dataset.bound = '1';
    syncFloat();
    window.addEventListener('resize', updateSilkNavOffset);
}

function initResultSectionNav(sections) {
    const dock = document.getElementById('silk-nav-dock');
    const scroll = document.getElementById('silk-nav-scroll');
    if (typeof resultSectionNavCleanup === 'function') {
        resultSectionNavCleanup();
        resultSectionNavCleanup = null;
    }
    if (!dock || !scroll) return;
    if (!sections.length) {
        dock.classList.add('panel-hidden');
        scroll.innerHTML = '';
        return;
    }
    dock.classList.remove('panel-hidden');
    scroll.innerHTML = sections
        .map((s) => `<button type="button" class="silk-nav__btn" data-target="${s.id}">${escapeHtml(s.label)}</button>`)
        .join('');
    const buttons = Array.from(scroll.querySelectorAll('.silk-nav__btn'));
    const stageBody = dock.closest('.stage-body');
    const sectionEls = sections
        .map((section) => document.getElementById(section.id))
        .filter(Boolean);

    const setActive = (activeBtn) => {
        if (!activeBtn) return;
        buttons.forEach((b) => b.classList.toggle('is-active', b === activeBtn));
        activeBtn.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        requestAnimationFrame(() => moveSilkNavIndicator(activeBtn));
    };

    const resolveActiveButtonFromScroll = () => {
        if (!stageBody || !buttons.length || !sectionEls.length) return buttons[0] || null;
        const stageRect = stageBody.getBoundingClientRect();
        const dockHeight = Math.ceil(dock.getBoundingClientRect().height);
        const anchorY = stageRect.top + dockHeight + 18;
        const maxScrollTop = Math.max(0, stageBody.scrollHeight - stageBody.clientHeight);
        if (stageBody.scrollTop >= maxScrollTop - 6) {
            return buttons[buttons.length - 1] || null;
        }

        let candidate = buttons[0] || null;
        let bestPassedTop = -Infinity;
        for (let idx = 0; idx < sectionEls.length; idx += 1) {
            const top = sectionEls[idx].getBoundingClientRect().top - anchorY;
            if (top <= 0 && top > bestPassedTop) {
                bestPassedTop = top;
                candidate = buttons[idx];
            }
        }
        return candidate;
    };

    let navSyncFrame = 0;
    const scheduleScrollSync = () => {
        if (navSyncFrame) return;
        navSyncFrame = window.requestAnimationFrame(() => {
            navSyncFrame = 0;
            setActive(resolveActiveButtonFromScroll());
        });
    };

    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const target = document.getElementById(btn.dataset.target);
            if (target) {
                target.open = true;
                updateSilkNavOffset();
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            setActive(btn);
        });
    });

    if (buttons[0]) setActive(buttons[0]);

    const onStageScroll = () => scheduleScrollSync();
    const onWindowResize = () => scheduleScrollSync();
    stageBody?.addEventListener('scroll', onStageScroll, { passive: true });
    window.addEventListener('resize', onWindowResize);
    sectionEls.forEach((el) => el.addEventListener('toggle', scheduleScrollSync));

    requestAnimationFrame(() => {
        bindSilkNavDock();
        updateSilkNavOffset();
        scheduleScrollSync();
    });

    resultSectionNavCleanup = () => {
        if (navSyncFrame) {
            window.cancelAnimationFrame(navSyncFrame);
            navSyncFrame = 0;
        }
        stageBody?.removeEventListener('scroll', onStageScroll);
        window.removeEventListener('resize', onWindowResize);
        sectionEls.forEach((el) => el.removeEventListener('toggle', scheduleScrollSync));
    };
}

document.addEventListener('DOMContentLoaded', () => {
    initApp().catch((error) => {
        console.error('initApp failed', error);
        showNotification(error.message || '页面初始化失败，请刷新后重试', 'error');
    });
});

async function initApp() {
    initWorkbenchPanels();
    initTripForm();
    initTripGenerationStopButton();
    initPersonaForm();
    initVisionPanel();
    initExportButton();
    await RuntimeConfigController.init();
    setDefaultDate();
    updateDaysValue(document.getElementById('days')?.value || 3);
    updateEnergyValue(document.getElementById('persona-energy')?.value || 2);
    if (typeof initExecTimeline === 'function') await initExecTimeline();
    await Promise.all([loadSystemStatus(), loadPersona()]);
}

function initWorkbenchPanels() {
    const railButtons = document.querySelectorAll('.rail-btn[data-panel]');
    const panelViews = document.querySelectorAll('.sidebar-view[data-panel-view]');
    railButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const target = button.dataset.panel;
            railButtons.forEach((item) => {
                const active = item === button;
                item.classList.toggle('is-active', active);
                if (active) item.setAttribute('aria-current', 'page');
                else item.removeAttribute('aria-current');
            });
            panelViews.forEach((view) => view.classList.toggle('active', view.dataset.panelView === target));
        });
    });
}

function initTripForm() {
    const form = document.getElementById('trip-form');
    if (!form) return;
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
            destination: document.getElementById('destination')?.value?.trim() || '',
            start_date: document.getElementById('start-date')?.value || '',
            days: Number(document.getElementById('days')?.value || 3),
            budget: Number(document.getElementById('budget')?.value || 0),
            persona: getPersonaPayload(),
        };

        const validationMessage = validateTripPayload(payload);
        if (validationMessage) {
            showNotification(validationMessage, 'warning');
            return;
        }
        if (!RuntimeConfigController?.requireKeysForFeature?.('trip')) {
            return;
        }
        const requestPayload = RuntimeSessionKeys.buildRequestPayload(payload);
        const keyValidationErrors = RuntimeKeyValidator.validatePayload(requestPayload);
        if (Object.keys(keyValidationErrors).length) {
            const detail = describeValidationErrors(keyValidationErrors);
            showNotification(detail || '请先修正 Key。', 'error', 7000);
            return;
        }

        try {
            showLoading(true);
            showProgressUI(true);
            const createResponse = await api.post('/api/trip/plan', requestPayload);
            if (!createResponse.success || !createResponse.task_id) {
                throw new Error(createResponse.message || '任务创建失败');
            }
            const taskId = createResponse.task_id;
            setCurrentTaskId(taskId);
            tripStopHandled = false;
            await new Promise((resolve, reject) => {
                tripGenerationFinish = resolve;
                activeTripSseConnection = api.connectSSE(
                    `/api/trip/progress/${taskId}`,
                    updateProgressMessage,
                    (result) => {
                        if (tripStopHandled) return;
                        setTripResult(result);
                        renderTripResult(result);
                        showNotification('旅行方案生成成功', 'success');
                        resolve();
                    },
                    (error) => {
                        if (tripStopHandled) {
                            resolve();
                            return;
                        }
                        reject(error);
                    },
                    (cancelMsg) => {
                        handleTripGenerationCancelled(cancelMsg);
                        resolve();
                    },
                );
            });
        } catch (error) {
            if (!tripStopHandled) {
                notifyServiceFailure(error.message, { context: 'trip' });
                resetStageAfterError();
            }
        } finally {
            activeTripSseConnection = null;
            tripGenerationFinish = null;
            showLoading(false);
        }
    });
}

function initTripGenerationStopButton() {
    const btn = document.getElementById('stop-generation-btn');
    if (!btn) return;
    btn.addEventListener('click', () => requestTripGenerationStop());
}

function resetTripGenerationStopButton() {
    const btn = document.getElementById('stop-generation-btn');
    if (!btn) return;
    btn.disabled = false;
    btn.classList.remove('is-busy');
}

async function requestTripGenerationStop() {
    const taskId = getCurrentTaskId();
    const btn = document.getElementById('stop-generation-btn');
    if (!taskId || !btn || btn.disabled || tripStopHandled) return;

    btn.disabled = true;

    if (activeTripSseConnection) {
        activeTripSseConnection.close();
        activeTripSseConnection = null;
    }
    handleTripGenerationCancelled('已终止生成');
    showLoading(false);
    if (typeof tripGenerationFinish === 'function') {
        tripGenerationFinish();
        tripGenerationFinish = null;
    }

    try {
        await api.post(`/api/trip/cancel/${taskId}`, {}, { timeout: 8000 });
    } catch (error) {
        showNotification(error.message || '终止失败，后台正在收尾', 'warning', 4000);
    }
}

function handleTripGenerationCancelled(message) {
    if (tripStopHandled) return;
    tripStopHandled = true;
    setCurrentTaskId(null);
    resetTripGenerationStopButton();
    if (typeof finishExecFlowVizCancelled === 'function') {
        finishExecFlowVizCancelled();
    }
    const resultStatus = document.getElementById('result-status');
    setStagePanels({ empty: true, progress: false, result: false });
    if (resultStatus) resultStatus.textContent = '等待生成';
    setStageTaskPill('已终止', 'muted');
    showNotification(message || '已终止生成', 'warning', 4500);
}

function validateTripPayload(payload) {
    if (!payload.destination) return '请输入目的地';
    if (!payload.start_date) return '请选择出发日期';
    const selectedDate = new Date(payload.start_date);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (selectedDate < today) return '出发日期不能早于今天';
    if (!Number.isFinite(payload.days) || payload.days < 1 || payload.days > 7) return '游玩天数需在 1 到 7 天之间';
    if (!Number.isFinite(payload.budget) || payload.budget <= 0) return '请输入有效预算';
    return '';
}

function initPersonaForm() {
    const form = document.getElementById('persona-form');
    const resetBtn = document.getElementById('reset-persona-btn');
    const persistPersonaDraft = () => {
        const payload = getPersonaPayload();
        setPersona(payload);
        updatePersonaDisplay(payload);
    };
    if (form) {
        form.addEventListener('input', persistPersonaDraft);
        form.addEventListener('change', persistPersonaDraft);
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const payload = getPersonaPayload();
            setPersona(payload);
            populatePersonaForm(payload);
            updatePersonaDisplay(payload);
            showNotification('画像已保存到当前会话', 'success');
        });
    }
    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            const persona = buildDefaultPersonaPayload();
            setPersona(persona);
            populatePersonaForm(persona);
            updatePersonaDisplay(persona);
            showNotification('已恢复默认画像', 'info');
        });
    }
}

function initVisionPanel() {
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('image-upload');
    const recognizeBtn = document.getElementById('recognize-btn');
    if (!uploadArea || !fileInput) return;
    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (event) => {
        const file = event.target.files?.[0];
        if (file) handleVisionFile(file);
    });
    uploadArea.addEventListener('dragover', (event) => {
        event.preventDefault();
        uploadArea.style.borderColor = 'var(--color-primary-light)';
    });
    uploadArea.addEventListener('dragleave', (event) => {
        event.preventDefault();
        uploadArea.style.borderColor = '';
    });
    uploadArea.addEventListener('drop', (event) => {
        event.preventDefault();
        uploadArea.style.borderColor = '';
        const file = event.dataTransfer?.files?.[0];
        if (file) handleVisionFile(file);
    });
    if (recognizeBtn) recognizeBtn.addEventListener('click', handleRecognize);
}

function handleVisionFile(file) {
    if (!file.type.startsWith('image/')) {
        showNotification('请上传图片文件', 'warning');
        return;
    }
    if (file.size > 10 * 1024 * 1024) {
        showNotification('图片大小不能超过 10MB', 'warning');
        return;
    }
    window.selectedImageFile = file;
    const previewContainer = document.getElementById('preview-container');
    const imagePreview = document.getElementById('image-preview');
    const recognizeBtn = document.getElementById('recognize-btn');
    if (imagePreview) imagePreview.src = URL.createObjectURL(file);
    if (previewContainer) previewContainer.classList.add('is-visible');
    if (recognizeBtn) recognizeBtn.disabled = false;
}

async function handleRecognize() {
    if (!window.selectedImageFile) {
        showNotification('请先上传图片', 'warning');
        return;
    }
    if (!RuntimeConfigController?.requireKeysForFeature?.('vision')) {
        return;
    }
    const systemStatus = getSystemStatus();
    if (systemStatus && !systemStatus.vision_enabled) {
        notifyServiceFailure('Bailian/Qwen Key 未配置，景点识别暂不可用', { context: 'vision' });
        return;
    }
    const btn = document.getElementById('recognize-btn');
    try {
        if (btn) {
            btn.disabled = true;
            btn.textContent = '识别中...';
        }
        const requestData = RuntimeSessionKeys.buildFormData({ persona: getPersonaPayload() });
        const keyValidationErrors = RuntimeKeyValidator.validatePayload(requestData);
        if (Object.keys(keyValidationErrors).length) {
            const detail = describeValidationErrors(keyValidationErrors);
            showNotification(detail || '请先修正 Key。', 'error', 7000);
            return;
        }
        const response = await api.upload('/api/vision/recognize', window.selectedImageFile, requestData);
        if (!response.success || !response.data) throw new Error(response.message || '识别失败');
        setVisionResult(response.data);
        renderVisionResult(response.data);
        showNotification('景点识别完成', 'success');
    } catch (error) {
        notifyServiceFailure(error.message, { context: 'vision' });
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '开始识别';
        }
    }
}

function renderVisionResult(data) {
    const container = document.getElementById('vision-result');
    if (!container) return;
    refreshServiceAlerts(
        collectServiceAlerts([
            { message: data?.warning, hint: 'bailian vision' },
        ]),
        'vision',
    );
    const relatedPois = Array.isArray(data.related_pois) ? data.related_pois : [];
    const tags = Array.isArray(data.knowledge?.tags) ? data.knowledge.tags : [];
    const confidence = typeof data.vision?.confidence === 'number' ? `${(data.vision.confidence * 100).toFixed(1)}%` : '--';
    container.classList.add('is-visible');
    container.innerHTML = `
        <div class="stage-section">
            <h4>${escapeHtml(data.scenic_name || '未识别地点')}</h4>
            <p class="result-card__meta">置信度：${escapeHtml(confidence)} · 类型：${escapeHtml(data.vision?.category || '待补充')}</p>
            <p class="result-card__meta" style="line-height:1.7;">${escapeHtml(data.vision?.intro || '暂无简介')}</p>
            ${tags.length ? `<p class="result-card__meta">标签：${escapeHtml(tags.join(' / '))}</p>` : ''}
            ${relatedPois.length ? `<div class="result-card-list result-card-list--compact">${relatedPois.map((poi) => `<div class="result-card"><strong>${escapeHtml(poi.name || '未命名地点')}</strong><p class="result-card__meta">${escapeHtml(poi.address || '暂无地址')}</p></div>`).join('')}</div>` : ''}
            ${data.warning ? `<p class="result-muted" style="color:var(--color-warning);">${escapeHtml(data.warning)}</p>` : ''}
        </div>
    `;
}

function initExportButton() {
    const exportBtn = document.getElementById('export-pdf-btn');
    if (!exportBtn) return;
    exportBtn.addEventListener('click', async () => {
        const tripResult = getTripResult();
        if (!tripResult) {
            showNotification('请先生成方案，再导出 PDF', 'warning');
            return;
        }
        try {
            exportBtn.disabled = true;
            exportBtn.textContent = '生成中...';
            await api.download('/api/report/export', {
                method: 'POST',
                data: { trip_result: tripResult },
                filename: 'travel_report.pdf',
                timeout: 60000,
            });
            showNotification('PDF 已生成并开始下载', 'success');
        } catch (error) {
            showNotification(error.message || 'PDF 导出失败', 'error');
        } finally {
            exportBtn.disabled = false;
            exportBtn.textContent = '生成 PDF';
        }
    });
}

function renderTripResult(result) {
    const overviewGrid = document.getElementById('stage-overview-grid');
    const stageSections = document.getElementById('stage-sections');
    const resultStatus = document.getElementById('result-status');
    const resultSubtitle = document.getElementById('result-subtitle');
    if (!overviewGrid || !stageSections) return;
    refreshServiceAlerts(
        collectServiceAlerts([
            { message: result?.map_data?.warning, hint: 'amap poi map' },
            { message: result?.weather?.warning, hint: 'amap weather' },
        ]),
        'trip',
    );
    setStagePanels({ empty: false, progress: false, result: true });
    if (resultStatus) resultStatus.textContent = '已生成';
    if (resultSubtitle) {
        resultSubtitle.textContent = `已为 ${result.trip_request?.destination || '当前目的地'} 生成行程方案`;
    }
    setStageTaskPill('旅行方案已生成', 'done');
    const loadBudget = result.routing_policy?.daily_activity_load_budget;
    const stamina = result.persona?.stamina || '适中';
    overviewGrid.classList.add('stage-overview-grid--hero');
    overviewGrid.innerHTML = renderPlanOverviewHero(result, { loadBudget, stamina });
    const sections = RESULT_SECTION_DEFS.map((def) => {
        const raw = def.render(result);
        if (!raw) return null;
        return wrapResultAccordion(def.id, def.label, unwrapStageSection(raw), def.id === 'result-itinerary');
    }).filter(Boolean);
    stageSections.innerHTML = sections.map((s) => s.html).join('');
    initResultSectionNav(sections);
}

function overviewCard(title, content) {
    return `<div class="stage-overview-card"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(content)}</p></div>`;
}

function renderPlanOverviewHero(result, { loadBudget, stamina }) {
    const dest = result.trip_request?.destination || '--';
    const days = result.trip_request?.days || 0;
    const budget = Number(result.trip_request?.budget || 0);
    const spent = Number(result.plan?.estimated_total_cost || 0);
    const startDate = result.trip_request?.start_date || '--';
    const budgetPct = budget > 0 ? Math.min(100, Math.round((spent / budget) * 100)) : 0;
    const budgetTone = budgetPct > 95 ? 'is-warn' : budgetPct > 75 ? 'is-caution' : 'is-ok';
    const loadText = loadBudget ? `每日上限 ${loadBudget}` : '按体力自动装箱';
    const stats = [
        { key: 'date', label: '出发日期', value: startDate, icon: '📅' },
        { key: 'days', label: '行程天数', value: `${days} 天`, icon: '🗓️' },
        { key: 'budget', label: '总预算', value: formatCurrency(budget), icon: '💰' },
        { key: 'spent', label: '预计花费', value: formatCurrency(spent), icon: '🧾', highlight: true },
        {
            key: 'load',
            label: '活动负荷',
            value: loadText,
            sub: stamina,
            icon: '⚡',
        },
    ];
    const cards = stats
        .map(
            (s) => `
        <article class="plan-stat-card${s.highlight ? ' plan-stat-card--highlight' : ''}" data-stat="${s.key}">
            <span class="plan-stat-card__icon" aria-hidden="true">${s.icon}</span>
            <div class="plan-stat-card__body">
                <span class="plan-stat-card__label">${escapeHtml(s.label)}</span>
                <p class="plan-stat-card__value">${escapeHtml(s.value)}</p>
                ${s.sub ? `<span class="plan-stat-card__sub">${escapeHtml(s.sub)}</span>` : ''}
            </div>
        </article>`,
        )
        .join('');
    return `
        <div class="plan-overview-hero">
            <div class="plan-overview-hero__head">
                <div class="plan-overview-hero__dest">
                    <span class="plan-overview-hero__eyebrow">目的地</span>
                    <h4 class="plan-overview-hero__title">${escapeHtml(dest)}</h4>
                </div>
                <div class="plan-budget-ring ${budgetTone}" style="--pct:${budgetPct}" title="预计花费占预算比例">
                    <svg class="plan-budget-ring__svg" viewBox="0 0 36 36" aria-hidden="true">
                        <circle class="plan-budget-ring__track" cx="18" cy="18" r="15.5"/>
                        <circle class="plan-budget-ring__fill" cx="18" cy="18" r="15.5"/>
                    </svg>
                    <div class="plan-budget-ring__label">
                        <strong>${budgetPct}%</strong>
                        <span>预算占用</span>
                    </div>
                </div>
            </div>
            <div class="plan-overview-stats">${cards}</div>
        </div>`;
}

function renderDayTimeline(timeline) {
    if (!Array.isArray(timeline) || !timeline.length) return '';
    const rows = timeline
        .map((item) => {
            const time = escapeHtml(item.time || '--:--');
            const activity = escapeHtml(item.activity || '');
            const place = escapeHtml(item.place || '');
            const kind = (() => {
                const text = String(item.activity || '');
                if (text.includes('午餐')) return 'meal';
                if (text.includes('晚餐')) return 'meal';
                if (text.includes('游览')) return 'visit';
                if (text.includes('前往')) return 'transit';
                return 'other';
            })();
            return `
                <li class="day-timeline__item day-timeline__item--${kind}">
                    <span class="day-timeline__time">${time}</span>
                    <span class="day-timeline__dot" aria-hidden="true"></span>
                    <div class="day-timeline__content">
                        <p class="day-timeline__activity">${activity}</p>
                        ${place ? `<span class="day-timeline__place">${place}</span>` : ''}
                    </div>
                </li>`;
        })
        .join('');
    return `<ol class="day-timeline" aria-label="当日时间轴">${rows}</ol>`;
}

function formatWaypointTypeLine(raw) {
    const text = String(raw || '')
        .trim()
        .replace(/；/g, ';');
    if (!text) return '景点';
    const parts = text
        .split(/[;|｜]/)
        .map((s) => s.trim())
        .filter(Boolean);
    const seen = new Set();
    const unique = [];
    for (const p of parts) {
        if (!seen.has(p)) {
            seen.add(p);
            unique.push(p);
        }
    }
    return unique.slice(0, 2).join(' · ') || '景点';
}

function renderItinerarySection(itinerary) {
    if (!Array.isArray(itinerary) || !itinerary.length) return '';
    return `<div class="stage-section"><h4>每日行程</h4>${itinerary.map((day) => {
        const loadMeta = day.activity_load_used != null && day.activity_load_budget != null
            ? `<p class="day-summary day-load-meta">当日强度：${escapeHtml(day.day_intensity || '适中')}（负荷 ${day.activity_load_used}/${day.activity_load_budget}）</p>`
            : '';
        const poiLines = (day.route_waypoints || []).map((poi) => {
            const typeLabel = poi.type_label || formatWaypointTypeLine(poi.type);
            const tier = poi.activity_tier_label || '常规';
            const hours = poi.visit_hours ? `约 ${poi.visit_hours} 小时` : '';
            return `
                <article class="spot-card">
                    <div class="spot-card__main">
                        <h5 class="spot-card__name">${escapeHtml(poi.name || '未命名景点')}</h5>
                        <span class="spot-card__type">${escapeHtml(typeLabel)}</span>
                    </div>
                    <div class="spot-card__meta">
                        <span class="spot-card__tier">${escapeHtml(tier)}</span>
                        ${hours ? `<span class="spot-card__hours">${escapeHtml(hours)}</span>` : ''}
                    </div>
                </article>`;
        }).join('');
        const timelineHtml = (day.timeline || []).length
            ? `<div class="day-timeline-wrap"><h5 class="day-timeline-title">当日时间安排</h5>${renderDayTimeline(day.timeline)}</div>`
            : '';
        const noteHtml = day.day_note
            ? `<p class="day-summary day-summary--note">${escapeHtml(day.day_note)}</p>`
            : '';
        return `<div class="itinerary-day-block"><div class="itinerary-day-head"><strong>Day ${day.day || '--'}</strong><span class="itinerary-day-theme">${escapeHtml(day.theme || '待补充')}</span></div>${loadMeta}<div class="itinerary-day-pois">${poiLines}</div>${timelineHtml}${noteHtml}${renderRouteMapPreview(day)}</div>`;
    }).join('')}</div>`;
}

function renderRouteMapPreview(day) {
    const previewUrl = RuntimeSessionKeys.appendToUrl(String(day?.route_map_preview || '').trim());
    if (!previewUrl) return '';
    const rg = day?.route_geometry || {};
    const status = String(rg.status || '').trim();
    const drawPath = Boolean(rg.draw_path) || status === 'ok';
    const mode = String(rg.effective_mode || rg.route_profile || 'driving');
    const modeLabel = { driving: '驾车', walking: '步行', transit: '公共交通' }[mode] || '出行';
    const caption = drawPath
        ? `高德${modeLabel}道路路线`
        : status === 'poi_markers_only'
          ? '景点分布预览（仅标注景点位置）'
          : status === 'metrics_only'
            ? '景点顺序标注（未绘制道路连线）'
            : status === 'no_waypoints'
              ? '单点标注'
              : '景点分布预览';
    const routeMessage = String(rg.message || '').trim();
    const distM = Number(rg.distance_m || 0);
    const durS = Number(rg.duration_s || 0);
    const routeSummary = drawPath && (distM > 0 || durS > 0)
        ? `${routeMessage || `全程约 ${distM >= 1000 ? (distM / 1000).toFixed(1) + ' 公里' : distM + ' 米'}，预计${modeLabel} ${durS >= 60 ? Math.round(durS / 60) + ' 分钟' : durS + ' 秒'}`}`
        : routeMessage;
    const wps = Array.isArray(day?.route_waypoints) ? day.route_waypoints : [];
    const legendHtml =
        wps.length > 0
            ? `<p class="route-map-legend"><strong>图中序号与景点</strong>（与地图红点顺序一致）：${wps
                  .slice(0, 8)
                  .map((p, i) => `${i + 1}. ${escapeHtml(p.name || '未命名')}`)
                  .join('；')}</p>`
            : '';
    const encodedUrl = encodeURIComponent(previewUrl);
    const encodedTitle = escapeJs(`Day ${day.day || '--'} 景点地图`);
    const encodedCaption = escapeJs(caption);
    return `
        <div class="route-map-block">
            <div class="route-map-block__head">
                <strong class="route-map-block__title">每日景点地图</strong>
                <span class="route-map-block__caption">${escapeHtml(caption)}</span>
            </div>
            <img class="route-map-block__img" src="${previewUrl}" alt="每日景点地图预览" loading="lazy" decoding="async" onclick="openRouteMapModal('${encodedUrl}', '${encodedTitle}', '${encodedCaption}')">
            ${legendHtml}
            <div class="route-map-block__actions">
                <button type="button" class="btn btn-secondary btn-sm" onclick="openRouteMapModal('${encodedUrl}', '${encodedTitle}', '${encodedCaption}')">查看大图</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="openRouteMapInNewTabFromUrl('${encodedUrl}')">新窗口打开</button>
            </div>
        </div>
    `;
}

function renderWeatherSection(weather) {
    const daily = Array.isArray(weather.daily) ? weather.daily : [];
    if (!daily.length) return '';
    const provider = String(weather.provider || '').trim();
    const fb = Boolean(weather.is_fallback);
    const warn = String(weather.warning || '').trim();
    const providerLine =
        fb && warn
            ? `<p class="weather-fallback-banner"><strong>天气来源：</strong>${escapeHtml(provider || 'fallback')} · ${escapeHtml(warn)}</p>`
            : fb
              ? `<p class="weather-fallback-banner"><strong>天气来源不可用。</strong> 以下为本地估算，出发前请再确认。</p>`
              : provider
                ? `<p class="result-muted result-muted--lead" style="font-size:0.86rem;"><strong>来源：</strong>${escapeHtml(provider)}</p>`
                : '';
    return `<div class="stage-section"><h4>天气</h4><p class="result-muted result-muted--lead"><strong>建议：</strong>${escapeHtml(weather.advice || '出发前请再确认天气')}</p>${providerLine}<div class="result-card-list">${daily.map((item) => `<div class="result-card"><strong>${escapeHtml(formatDate(item.date))}</strong><p class="result-card__meta result-card__meta--lead">${escapeHtml(item.condition || '--')} · ${escapeHtml(formatTemperature(item.temp_min, item.temp_max))}</p>${item.note ? `<p class="result-card__meta">${escapeHtml(item.note)}</p>` : ''}</div>`).join('')}</div></div>`;
}

function renderMapSection(mapData) {
    const pois = Array.isArray(mapData.pois) ? mapData.pois : [];
    const warn = String(mapData.warning || '').trim();
    const isFb = Boolean(mapData.is_fallback);
    if (!pois.length && !warn) return '';
    const warnHtml = warn
        ? `<div class="map-data-warning ${isFb ? 'is-fallback' : ''}">${escapeHtml(warn)}</div>`
        : '';
    const hint = escapeHtml(mapData.transport_hint || '请结合地图 App 查看实时位置与导航');
    const showCount = Math.min(pois.length, 16);
    const listHtml = pois.length
        ? `<p class="result-muted result-muted--lead" style="margin-bottom:10px;"><strong>候选景点：</strong>共 ${pois.length} 个${pois.length > showCount ? `，展示前 ${showCount} 个` : ''}</p><div class="result-card-list">${pois
              .slice(0, showCount)
              .map(
                  (poi) =>
                      `<div class="result-card"><strong>${escapeHtml(poi.visit_site_label || poi.name || '未命名景点')}</strong><p class="result-card__meta">${escapeHtml(poi.type || '景点')} · ${escapeHtml(poi.address || '暂无地址')}</p>${poi.visit_site_note ? `<p class="result-card__meta">${escapeHtml(poi.visit_site_note)}</p>` : ''}</div>`,
              )
              .join('')}</div>`
        : '<p class="result-muted">暂无线上景点。请检查高德 Key 或配额。</p>';
    return `<div class="stage-section"><h4>景点池</h4>${warnHtml}<p class="result-muted result-muted--lead"><strong>导航提示：</strong>${hint}</p>${listHtml}</div>`;
}

function renderBudgetSection(plan) {
    const rows = Object.entries(plan.cost_breakdown || {});
    if (!rows.length) return '';
    const detail = plan.budget_detail || {};
    const ticketLines = Array.isArray(detail.tickets?.lines) ? detail.tickets.lines : [];
    const lodgingLines = Array.isArray(detail.lodging?.lines) ? detail.lodging.lines : [];
    const mealLines = Array.isArray(detail.meals?.lines) ? detail.meals.lines : [];
    const transportLines = Array.isArray(detail.transport?.lines) ? detail.transport.lines : [];
    const bufferLines = Array.isArray(detail.buffer?.lines) ? detail.buffer.lines : [];

    const renderBudgetBadge = (line) => {
        const sourceType = String(line?.source_type || '').trim();
        const label = String(line?.source_label || (sourceType === 'predicted' ? '预测' : '经验估算')).trim();
        const tone = sourceType === 'predicted' ? 'is-predicted' : sourceType === 'estimated' ? 'is-estimated' : 'is-live';
        return `<span class="budget-ticket-row__pill ${tone}">${escapeHtml(label)}</span>`;
    };

    const renderExplain = (lines) =>
        lines.length
            ? `<div class="budget-detail-block">${lines
                  .map(
                      (line) =>
                          `<div class="budget-ticket-row"><div class="budget-ticket-row__head"><strong>${escapeHtml(line.label || '')}</strong>${renderBudgetBadge(line)}</div><span class="budget-ticket-row__meta">${escapeHtml(line.detail || '')}</span><span class="budget-ticket-row__meta budget-ticket-row__meta--amount">${escapeHtml(formatCurrency(line.amount || 0))}</span></div>`,
                  )
                  .join('')}</div>`
            : '';

    const ticketLead =
        ticketLines.length > 0
            ? `<p class="budget-ticket-summary"><strong>门票说明：</strong>本次门票为经验估算。<em>下单前请以景区官方预约页、文旅公告或正规平台为准。</em></p>`
            : '';

    const ticketHtml =
        ticketLines.length > 0
            ? `<div class="budget-detail-block"><h5 class="budget-detail-title">门票 / 预约</h5>${ticketLead}${ticketLines
                  .map(
                      (line) =>
                          `<div class="budget-ticket-row"><div class="budget-ticket-row__head"><strong>Day ${line.day || '-'} · ${escapeHtml(line.place || '')}</strong>${renderBudgetBadge(line)}</div><span class="budget-ticket-row__meta">${escapeHtml(line.note || '')}</span>${line.verification_hint ? `<span class="budget-ticket-row__meta budget-ticket-row__meta--accent">${escapeHtml(line.verification_hint)}</span>` : ''}<span class="budget-ticket-row__meta budget-ticket-row__meta--amount">${escapeHtml(formatCurrency(line.amount || 0))}</span></div>`,
                  )
                  .join('')}</div>`
            : '';

    const budgetLead = `<p class="result-muted result-muted--lead"><strong>说明：</strong>住宿、餐饮、接驳和机动金为 <em>预测</em>；门票/预约为经验估算。</p>`;
    return `<div class="stage-section"><h4>预算</h4>${budgetLead}<div class="result-card-list">${rows.map(([label, amount]) => `<p class="result-row-split"><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatCurrency(amount))}</strong></p>`).join('')}</div>${renderExplain(lodgingLines)}${renderExplain(mealLines)}${renderExplain(transportLines)}${ticketHtml}${renderExplain(bufferLines)}${plan.budget_note ? `<div class="day-summary"><strong>预算提示：</strong>${escapeHtml(plan.budget_note)}</div>` : ''}</div>`;
}

function renderFoodSection(foods) {
    if (!Array.isArray(foods) || !foods.length) return '';
    return `
        <div class="stage-section">
            <h4>当地美食推荐</h4>
            <div class="result-card-list">
                ${foods.map((food) => {
                    const rawType = String(food.type || '').trim();
                    const displayType = rawType && !/^[\d;|]+$/.test(rawType) ? rawType : '';
                    const metaParts = [displayType, String(food.address || '').trim() || '暂无地址'].filter(Boolean);
                    return `
                    <div class="result-card">
                        <strong>${escapeHtml(food.name || '未命名餐厅')}</strong>
                        <p class="result-card__meta">${escapeHtml(metaParts.join(' · '))}</p>
                        ${(food.avg_cost || food.rating) ? `<p class="result-card__meta">${food.avg_cost ? `人均 ${escapeHtml(String(food.avg_cost))} 元` : ''}${food.avg_cost && food.rating ? ' · ' : ''}${food.rating ? `评分 ${escapeHtml(String(food.rating))}` : ''}</p>` : ''}
                    </div>
                `;
                }).join('')}
            </div>
        </div>
    `;
}

function renderTransportLodgingSection(transportPlan, lodgings) {
    const hasTransport = transportPlan && Object.keys(transportPlan).length;
    const hasLodgings = Array.isArray(lodgings) && lodgings.length;
    const dailyStays = Array.isArray(transportPlan?.daily_stays) ? transportPlan.daily_stays : [];
    if (!hasTransport && !dailyStays.length && !hasLodgings) return '';
    const hasRouteMetrics = Boolean(transportPlan?.route_metrics_available) &&
        (Number(transportPlan?.estimated_total_distance_km || 0) > 0 || Number(transportPlan?.estimated_total_duration_h || 0) > 0);
    const normalizedHotels = (Array.isArray(lodgings) ? lodgings : [])
        .filter((hotel) => hotel && String(hotel.name || '').trim())
        .map((hotel) => ({ ...hotel, _name: String(hotel.name || '').trim() }));
    const chosenHotelNames = new Set(
        dailyStays
            .map((stay) => String(stay?.hotel_name || '').trim())
            .filter(Boolean),
    );
    const fallbackPool = normalizedHotels.filter((hotel) => !chosenHotelNames.has(hotel._name));
    const parseCoverageDays = (hotel) => {
        const label = String(hotel?.stay_label || '').trim();
        const days = new Set();
        if (!label) return days;
        const rangePattern = /Day\s*(\d+)(?:\s*-\s*(\d+))?/gi;
        let match = null;
        while ((match = rangePattern.exec(label))) {
            const start = Number(match[1] || 0);
            const end = Number(match[2] || start);
            if (!Number.isFinite(start) || start <= 0) continue;
            const upper = Number.isFinite(end) && end >= start ? end : start;
            for (let value = start; value <= upper; value += 1) {
                days.add(value);
            }
        }
        return days;
    };
    const rankFallbackHotels = (day, primaryName) => {
        const hotels = fallbackPool.length ? fallbackPool : normalizedHotels;
        return hotels
            .map((hotel, index) => {
                const coverageDays = parseCoverageDays(hotel);
                const coverageHit = coverageDays.has(day) ? 0 : coverageDays.size ? 1 : 2;
                const rating = Number(hotel.rating || 0);
                const ratingBonus = Number.isFinite(rating) ? Math.min(1.2, Math.max(0, rating) / 10) : 0;
                const primaryPenalty = String(hotel._name || '') === String(primaryName || '') ? 2.5 : 0;
                const coveragePenalty = coverageDays.size ? Math.max(0, Math.min(0.8, Math.abs(day - Math.min(...coverageDays)) * 0.15)) : 0.8;
                const stabilityPenalty = hotel.is_primary ? 1.1 : 0;
                return {
                    hotel,
                    score: coverageHit + coveragePenalty + stabilityPenalty + primaryPenalty - ratingBonus + index * 0.001,
                };
            })
            .sort((a, b) => a.score - b.score)
            .map((item) => item.hotel);
    };
    const renderLodgingCard = (label, tone, hotel, extraHtml = '') => {
        if (!hotel) {
            return `<article class="lodging-day-card lodging-day-card--empty"><div class="lodging-day-card__head"><strong>${escapeHtml(label)}</strong><span class="lodging-pill lodging-pill--muted">${escapeHtml(tone)}</span></div><p class="result-muted">暂无酒店候选。</p></article>`;
        }
        const address = String(hotel.address || '').trim() || '暂无地址';
        const type = String(hotel.type || '').trim() || '住宿';
        const rating = hotel.rating ? `评分 ${escapeHtml(String(hotel.rating))}` : '';
        const stayLabel = String(hotel.stay_label || '').trim();
        const dist = hotel.distance_to_day_center_km != null ? `距当日活动中心约 ${escapeHtml(String(hotel.distance_to_day_center_km))} km` : '';
        return `
            <article class="lodging-day-card lodging-day-card--${escapeHtml(tone)}">
                <div class="lodging-day-card__head">
                    <strong>${escapeHtml(label)}</strong>
                    <span class="lodging-pill lodging-pill--${escapeHtml(tone)}">${escapeHtml(tone === 'primary' ? '主入住' : '兜底')}</span>
                </div>
                <h5 class="lodging-day-card__title">${escapeHtml(hotel.name || '未命名住宿')}</h5>
                <p class="result-card__meta result-card__meta--lead">${escapeHtml(type)} · ${escapeHtml(address)}</p>
                ${rating ? `<p class="result-card__meta">${rating}</p>` : ''}
                ${stayLabel ? `<p class="result-card__meta">覆盖天数：${escapeHtml(stayLabel)}</p>` : ''}
                ${dist ? `<p class="result-card__meta lodging-day-card__distance">${dist}</p>` : ''}
                ${extraHtml}
            </article>
        `;
    };

    const stayCards = dailyStays.length
        ? `<div class="lodging-day-grid">${dailyStays.map((stay) => {
            const day = Number(stay.day || 0) || '-';
            const primaryHotel = {
                name: stay.hotel_name || '待补充',
                address: stay.hotel_address || '',
                type: stay.hotel_type || '住宿',
                rating: stay.rating || '',
                distance_to_day_center_km: stay.distance_to_day_center_km,
                stay_label: `Day ${day}`,
            };
            const fallbackHotel = rankFallbackHotels(day, primaryHotel._name || primaryHotel.name)[0] || null;
            const reasonHtml = stay.reason ? `<p class="lodging-day-card__reason">${escapeHtml(stay.reason)}</p>` : '';
            const primaryCard = renderLodgingCard(`Day ${day} · 主入住`, 'primary', primaryHotel, reasonHtml);
            const fallbackRule = `<p class="lodging-day-card__reason lodging-day-card__reason--fallback"><strong>兜底规则：</strong>优先选覆盖当天或衔接次日动线的酒店；若候选不足，则保留同酒店兜底。</p>`;
            const fallbackCard = renderLodgingCard(`Day ${day} · 兜底方案`, 'fallback', fallbackHotel, fallbackHotel ? fallbackRule : '');
            return `${primaryCard}${fallbackCard}`;
        }).join('')}</div>`
        : '';
    const ruleBasedFallbackPool = rankFallbackHotels(1, '').slice(0, 3);
    const transportMetricsHtml = hasRouteMetrics
        ? `<p class="result-card__meta">预计总里程：${escapeHtml(String(transportPlan.estimated_total_distance_km))} km · 预计总时长：${escapeHtml(String(transportPlan.estimated_total_duration_h))} 小时</p>`
        : '<p class="result-card__meta result-card__meta--lead"><strong>路线提示：</strong>请以实时导航和当天路况为准，酒店优先服务次日首站。</p>';

    return `
        <div class="stage-section">
            <h4>住行</h4>
            ${hasTransport ? `
                <div class="result-block">
                    <p class="result-muted result-muted--lead"><strong>交通建议：</strong>${escapeHtml(transportPlan.summary || '已生成')}</p>
                    <p class="result-card__meta result-card__meta--lead"><strong>交通方式：</strong>${escapeHtml(transportPlan.suggested_mode || '--')}</p>
                    ${transportMetricsHtml}
                    ${transportPlan.cross_city_hint ? `<p class="result-card__meta">${escapeHtml(transportPlan.cross_city_hint)}</p>` : ''}
                    ${dailyStays.length ? `<p class="result-card__meta result-card__meta--lead"><strong>兜底规则：</strong>优先匹配当日动线和次日首站，减少晚归和折返。</p>` : ''}
                    ${stayCards}
                </div>
            ` : ''}
            ${!dailyStays.length && hasLodgings ? `<div class="lodging-fallback-panel"><h5 class="budget-detail-title">兜底酒店</h5><p class="result-muted result-muted--lead"><strong>排序：</strong>先看覆盖天数，再看动线和评分。</p><div class="result-card-list">${ruleBasedFallbackPool.map((hotel) => `<div class="result-card"><strong>${escapeHtml(hotel.name || '未命名住宿')}</strong><p class="result-card__meta result-card__meta--lead">${escapeHtml(hotel.type || '住宿')} · ${escapeHtml(hotel.address || '暂无地址')}</p>${hotel.stay_label ? `<p class="result-card__meta">覆盖天数：${escapeHtml(hotel.stay_label)}</p>` : ''}</div>`).join('')}</div></div>` : ''}
        </div>
    `;
}

function renderTipsSection(tips) {
    if (!Array.isArray(tips) || !tips.length) return '';
    const cards = tips
        .map((tip, index) => {
            if (typeof tip === 'string') {
                return {
                    tag: `提醒 ${index + 1}`,
                    title: '出行提醒',
                    body: tip,
                    tone: index === 0 ? 'alert' : 'soft',
                    layout: index === 0 ? 'featured' : 'default',
                };
            }
            return {
                tag: String(tip?.tag || `提醒 ${index + 1}`).trim(),
                title: String(tip?.title || '出行提醒').trim(),
                body: String(tip?.body || tip?.text || '').trim(),
                tone: String(tip?.tone || 'soft').trim(),
                layout: String(tip?.layout || 'default').trim(),
            };
        })
        .filter((item) => item.body);
    if (!cards.length) return '';
    return `<div class="stage-section tips-stage"><div class="tips-stage__head"><div><h4>提醒</h4><p class="tips-stage__lead">提前留意会影响当天体验的事项。</p></div><span class="tips-stage__count">${cards.length} 条</span></div><div class="tips-card-grid">${cards
        .map(
            (tip, index) =>
                `<article class="tip-card tip-card--${escapeHtml(tip.tone || 'soft')} tip-card--${escapeHtml(tip.layout || 'default')}"><div class="tip-card__head"><span class="tip-card__tag">${escapeHtml(tip.tag || '提醒')}</span></div><h5 class="tip-card__title"><strong>${escapeHtml(tip.title || '出行提醒')}</strong></h5><p class="tip-card__body">${escapeHtml(tip.body || '')}</p></article>`,
        )
        .join('')}</div></div>`;
}

async function loadSystemStatus() {
    try {
        const response = await api.get('/api/system/status');
        if (!response.success || !response.data) return;
        setSystemStatus(response.data);
        updateSystemUI(response.data);
    } catch (error) {
        console.warn('loadSystemStatus failed', error);
    }
}

function updateSystemUI(status) {
    const badge = document.getElementById('runtime-mode-badge');
    const title = document.getElementById('runtime-mode-title');
    const desc = document.getElementById('system-status-desc');
    const pills = document.getElementById('stage-capability-pills');
    const sessionState = RuntimeSessionKeys?.getState?.() || {};
    const modeText = sessionState.has_any ? '本次会话已配置' : (status.app_mode === 'hybrid' ? '混合模式' : '体验模式');
    if (badge) badge.dataset.mode = sessionState.has_any ? 'byok' : (status.app_mode || 'demo');
    if (title) title.textContent = modeText;
    if (desc) {
        desc.textContent = sessionState.has_any
            ? '当前会话已配置 Key，具体可用能力见下方状态。'
            : status.notes?.[0] || '系统状态已加载';
    }
    updateConfigBriefSummary(status.runtime_config || {});
    RuntimeConfigController.renderHints(status.runtime_config || {});
    renderSystemServiceAlerts();
    if (pills) pills.innerHTML = [
        { label: (status.trip_live_enabled || sessionState.has_amap) ? '实时地图' : '演示地图', live: !!(status.trip_live_enabled || sessionState.has_amap) },
        { label: (status.vision_enabled || sessionState.has_bailian) ? '景点识别可用' : '景点识别不可用', live: !!(status.vision_enabled || sessionState.has_bailian) },
        { label: status.report_enabled ? 'PDF 可导出' : 'PDF 未启用', live: !!status.report_enabled },
    ].map((item) => `<span class="capability-pill ${item.live ? 'is-live' : 'is-demo'}">${escapeHtml(item.label)}</span>`).join('');
}

function notifyServiceFailure(message, { context = 'trip', hint = '' } = {}) {
    const info = RuntimeServiceErrors.classify(message, hint);
    const level = info.code === 'unknown' ? 'error' : 'warning';
    refreshServiceAlerts(info.code === 'unknown' ? [] : [toServiceAlert(info)], context);
    showNotification(RuntimeServiceErrors.notificationText(info), level, 6000);
}

function toServiceAlert(info) {
    return {
        service: String(info?.service || '').trim(),
        code: String(info?.code || '').trim(),
        title: String(info?.title || '').trim(),
        message: String(info?.message || '').trim(),
        doc_url: String(info?.doc_url || '').trim(),
    };
}

function collectServiceAlerts(items) {
    const alerts = [];
    for (const item of Array.isArray(items) ? items : []) {
        const message = typeof item === 'string' ? item : item?.message;
        const hint = typeof item === 'string' ? '' : item?.hint || '';
        const text = String(message || '').trim();
        if (!text) continue;
        const info = RuntimeServiceErrors.classify(text, hint);
        if (info.code === 'unknown') continue;
        alerts.push(toServiceAlert(info));
    }
    return dedupeServiceAlerts(alerts);
}

function dedupeServiceAlerts(alerts) {
    const seen = new Set();
    const output = [];
    for (const alert of Array.isArray(alerts) ? alerts : []) {
        const key = `${alert.service || ''}:${alert.code || ''}`;
        if (!key || seen.has(key)) continue;
        seen.add(key);
        output.push(alert);
    }
    return output;
}

function refreshServiceAlerts(nextAlerts, context) {
    const current = Array.isArray(getServiceAlerts?.()) ? getServiceAlerts() : [];
    const keep = current.filter((item) => String(item?.context || '') !== String(context || ''));
    const incoming = dedupeServiceAlerts(nextAlerts).map((item) => ({ ...item, context }));
    setServiceAlerts([...keep, ...incoming].slice(0, 6));
    renderSystemServiceAlerts();
}

function renderSystemServiceAlerts() {
    const host = document.getElementById('system-service-alerts');
    if (!host) return;
    const alerts = Array.isArray(getServiceAlerts?.()) ? getServiceAlerts() : [];
    if (!alerts.length) {
        host.hidden = true;
        host.innerHTML = '';
        return;
    }
    host.hidden = false;
    host.innerHTML = alerts.map((alert) => {
        const link = alert.doc_url
            ? `<a href="${escapeHtml(alert.doc_url)}" target="_blank" rel="noopener">查看说明</a>`
            : '';
        return `
            <article class="system-service-alert" data-service="${escapeHtml(alert.service || 'unknown')}">
                <div class="system-service-alert__head">
                    <strong>${escapeHtml(alert.title || '服务告警')}</strong>
                    <span>${escapeHtml((alert.service || '').toUpperCase())}</span>
                </div>
                <p>${escapeHtml(alert.message || '')}</p>
                ${link ? `<div class="system-service-alert__actions">${link}</div>` : ''}
            </article>
        `;
    }).join('');
}

function showLoading(show) {
    const submitBtn = document.getElementById('trip-submit-btn');
    if (!submitBtn) return;
    if (!submitBtn.dataset.defaultText) {
        submitBtn.dataset.defaultText = submitBtn.textContent || '生成方案';
    }
    submitBtn.disabled = !!show;
    submitBtn.classList.toggle('is-loading', !!show);
    submitBtn.textContent = show ? '生成中...' : submitBtn.dataset.defaultText;
}

function showProgressUI(show) {
    const resultStatus = document.getElementById('result-status');
    const messagesContainer = document.getElementById('progress-messages');
    if (show) {
        setStagePanels({ empty: false, progress: true, result: false });
        setStageTaskPill('生成中', 'running');
        resetTripGenerationStopButton();
        if (resultStatus) resultStatus.textContent = '生成中';
        if (messagesContainer) messagesContainer.innerHTML = '<div class="progress-message progress-message--latest">正在初始化任务...</div>';
        if (typeof resetExecFlowViz === 'function') resetExecFlowViz();
        if (typeof resetExecTimeline === 'function') resetExecTimeline();
        const timelinePanel = document.getElementById('exec-timeline');
        if (timelinePanel) timelinePanel.open = true;
    } else {
        setStagePanels({ empty: true, progress: false, result: false });
        setStageTaskPill('等待生成', 'muted');
        if (resultStatus) resultStatus.textContent = '等待生成';
    }
}

function updateProgressMessage(raw) {
    const messagesContainer = document.getElementById('progress-messages');
    if (!messagesContainer) return;
    const isStr = typeof raw === 'string';
    const message = isStr ? raw : String(raw?.message || '');
    const stage = isStr ? window.inferStageFromMessage?.(message) ?? null : raw?.stage ?? window.inferStageFromMessage?.(message) ?? null;
    const stepId = !isStr && raw && Object.prototype.hasOwnProperty.call(raw, 'step_id') ? raw.step_id : null;
    if (typeof applyProgressEvent === 'function') {
        applyProgressEvent(isStr ? { message, stage } : raw);
    } else if (typeof applyExecFlowStage === 'function') {
        applyExecFlowStage(stage, message);
    }
    // 带步骤标识的结构化进度已由「执行明细」时间线承接，底部消息流不再重复追加。
    if (stepId) {
        return;
    }
    messagesContainer.querySelectorAll('.progress-message--latest').forEach((el) => el.classList.remove('progress-message--latest'));
    const messageEl = document.createElement('div');
    messageEl.className = 'progress-message progress-message--latest';
    messageEl.textContent = `• ${message}`;
    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function resetStageAfterError() {
    resetTripGenerationStopButton();
    if (typeof resetExecFlowViz === 'function') resetExecFlowViz();
    if (typeof resetExecTimeline === 'function') resetExecTimeline();
    if (typeof finishExecFlowViz === 'function') finishExecFlowViz(false);
    setStagePanels({ empty: true, progress: false, result: false });
    setStageTaskPill('等待生成', 'muted');
}

function formatTemperature(min, max) {
    if (min === null || min === undefined || max === null || max === undefined) return '待更新';
    return `${min}°C - ${max}°C`;
}

function escapeJs(value) {
    return String(value || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, ' ');
}

function buildHighResStaticMapUrl(rawUrl) {
    const source = String(rawUrl || '').trim();
    if (!source) return '';
    try {
        const url = new URL(source, window.location.origin);
        const params = url.searchParams;
        if (params.has('markers') || params.has('paths')) {
            params.set('size', '1100*480');
        }
        return `${url.pathname}${url.search}`;
    } catch {
        return source;
    }
}

function getRouteMapViewerElements() {
    return {
        wrap: document.getElementById('route-map-modal-zoom-wrap'),
        stage: document.getElementById('route-map-pan-stage'),
        image: document.getElementById('route-map-modal-image'),
    };
}

function measureRouteMapViewer(state) {
    const { wrap, image } = getRouteMapViewerElements();
    if (!wrap || !image || !state) return false;
    state.viewportW = Math.max(1, wrap.clientWidth);
    state.viewportH = Math.max(1, wrap.clientHeight);
    state.baseW = Math.max(1, image.offsetWidth || state.viewportW);
    state.baseH = Math.max(1, image.offsetHeight || state.viewportH);
    state.fitScale = Math.min(state.viewportW / state.baseW, state.viewportH / state.baseH, 1);
    state.minScale = state.fitScale;
    state.maxScale = Math.max(state.fitScale * 4, state.fitScale + 0.5);
    return true;
}

function clampRouteMapViewerTransform(state) {
    if (!state?.baseW || !state?.baseH) return;
    let scale = Number(state.scale ?? 1);
    scale = Math.min(state.maxScale ?? 4, Math.max(state.minScale ?? 1, scale));
    state.scale = scale;
    const sw = state.baseW * scale;
    const sh = state.baseH * scale;
    let tx = Number(state.tx ?? 0);
    let ty = Number(state.ty ?? 0);
    if (sw <= state.viewportW) {
        tx = (state.viewportW - sw) / 2;
    } else {
        const minTx = state.viewportW - sw;
        tx = Math.min(0, Math.max(minTx, tx));
    }
    if (sh <= state.viewportH) {
        ty = (state.viewportH - sh) / 2;
    } else {
        const minTy = state.viewportH - sh;
        ty = Math.min(0, Math.max(minTy, ty));
    }
    state.tx = tx;
    state.ty = ty;
}

function fitRouteMapViewer(state) {
    if (!measureRouteMapViewer(state)) return;
    state.scale = state.fitScale;
    state.tx = (state.viewportW - state.baseW * state.scale) / 2;
    state.ty = (state.viewportH - state.baseH * state.scale) / 2;
    clampRouteMapViewerTransform(state);
}

function applyRouteMapViewerTransform() {
    const { stage } = getRouteMapViewerElements();
    const state = window.routeMapViewerState;
    if (!stage || !state) return;
    clampRouteMapViewerTransform(state);
    const s = Number(state.scale ?? 1);
    const tx = Number(state.tx ?? 0);
    const ty = Number(state.ty ?? 0);
    stage.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
    const { wrap } = getRouteMapViewerElements();
    if (wrap) {
        const canPan = s > (state.fitScale ?? 1) * 1.02;
        wrap.classList.toggle('is-pannable', canPan);
    }
}

function zoomRouteMapViewerAt(clientX, clientY, factor) {
    const state = window.routeMapViewerState;
    const { wrap } = getRouteMapViewerElements();
    if (!state?.rawUrl || !wrap) return;
    if (!state.baseW) measureRouteMapViewer(state);
    const rect = wrap.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
    const scale = Number(state.scale ?? 1);
    const tx = Number(state.tx ?? 0);
    const ty = Number(state.ty ?? 0);
    const newScale = Math.min(state.maxScale ?? 4, Math.max(state.minScale ?? 1, scale * factor));
    if (Math.abs(newScale - scale) < 1e-9) return;
    const cx = (mx - tx) / scale;
    const cy = (my - ty) / scale;
    state.scale = newScale;
    state.tx = mx - cx * newScale;
    state.ty = my - cy * newScale;
    applyRouteMapViewerTransform();
}

function openRouteMapModal(rawUrl, title = '景点地图', caption = '') {
    const previewUrl = decodeURIComponent(String(rawUrl || '').trim());
    if (!previewUrl) return;
    const modal = document.getElementById('route-map-modal');
    const { image, stage } = getRouteMapViewerElements();
    const titleEl = document.getElementById('route-map-modal-title');
    const captionEl = document.getElementById('route-map-modal-caption');
    if (!modal || !image) return;
    window.routeMapViewerState = {
        rawUrl: previewUrl,
        scale: 1,
        tx: 0,
        ty: 0,
        fitScale: 1,
        minScale: 1,
        maxScale: 4,
        baseW: 0,
        baseH: 0,
        viewportW: 0,
        viewportH: 0,
        dragging: false,
    };
    if (stage) stage.style.transform = '';
    image.alt = title || '景点地图';
    const onReady = () => {
        fitRouteMapViewer(window.routeMapViewerState);
        applyRouteMapViewerTransform();
    };
    if (image.complete && image.naturalWidth > 0) {
        onReady();
    } else {
        image.onload = () => {
            image.onload = null;
            onReady();
        };
    }
    image.src = previewUrl;
    if (titleEl) titleEl.textContent = title;
    if (captionEl) {
        const hint = '滚轮缩放（以指针为中心）· 左键拖动 · 双击适应窗口';
        captionEl.textContent = caption ? `${caption} ${hint}` : hint;
    }
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
}

function closeRouteMapModal() {
    const modal = document.getElementById('route-map-modal');
    const image = document.getElementById('route-map-modal-image');
    const panStage = document.getElementById('route-map-pan-stage');
    if (!modal) return;
    if (image) {
        image.src = '';
    }
    if (panStage) {
        panStage.style.transform = '';
    }
    window.routeMapViewerState = { rawUrl: '', scale: 1, tx: 0, ty: 0, dragging: false };
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
}

function initRouteMapModalViewer() {
    const wrap = document.getElementById('route-map-modal-zoom-wrap');
    const img = document.getElementById('route-map-modal-image');
    if (!wrap || !img || wrap.dataset.viewerBound === '1') return;
    wrap.dataset.viewerBound = '1';

    const isModalOpen = () => {
        const modal = document.getElementById('route-map-modal');
        return modal && !modal.classList.contains('hidden');
    };

    wrap.addEventListener(
        'wheel',
        (e) => {
            if (!isModalOpen()) return;
            e.preventDefault();
            const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
            zoomRouteMapViewerAt(e.clientX, e.clientY, factor);
        },
        { passive: false },
    );

    wrap.addEventListener('dblclick', (e) => {
        e.preventDefault();
        if (!isModalOpen()) return;
        const state = window.routeMapViewerState;
        if (!state) return;
        fitRouteMapViewer(state);
        applyRouteMapViewerTransform();
    });

    wrap.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || !isModalOpen()) return;
        const state = window.routeMapViewerState;
        if (!state?.rawUrl) return;
        if (!state.baseW) measureRouteMapViewer(state);
        const canPan = Number(state.scale ?? 1) > Number(state.fitScale ?? 1) * 1.02;
        if (!canPan) return;
        e.preventDefault();
        state.dragging = true;
        state.dragStartX = e.clientX;
        state.dragStartY = e.clientY;
        state.dragOrigTx = Number(state.tx ?? 0);
        state.dragOrigTy = Number(state.ty ?? 0);
        wrap.classList.add('is-dragging');
    });

    function onMouseMove(e) {
        const state = window.routeMapViewerState;
        if (!state?.dragging) return;
        state.tx = state.dragOrigTx + (e.clientX - state.dragStartX);
        state.ty = state.dragOrigTy + (e.clientY - state.dragStartY);
        applyRouteMapViewerTransform();
    }

    window.addEventListener('resize', () => {
        const state = window.routeMapViewerState;
        if (!isModalOpen() || !state?.rawUrl) return;
        fitRouteMapViewer(state);
        applyRouteMapViewerTransform();
    });

    function onMouseUp() {
        const state = window.routeMapViewerState;
        if (state?.dragging) {
            state.dragging = false;
            wrap.classList.remove('is-dragging');
        }
    }

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
}

function openRouteMapInNewTab() {
    const state = window.routeMapViewerState || {};
    if (!state.rawUrl) return;
    const url = buildHighResStaticMapUrl(state.rawUrl);
    window.open(url || state.rawUrl, '_blank', 'noopener');
}

function openRouteMapInNewTabFromUrl(rawUrl) {
    const previewUrl = decodeURIComponent(String(rawUrl || '').trim());
    if (!previewUrl) return;
    const url = buildHighResStaticMapUrl(previewUrl);
    window.open(url || previewUrl, '_blank', 'noopener');
}

window.openRouteMapModal = openRouteMapModal;
window.closeRouteMapModal = closeRouteMapModal;
window.openRouteMapInNewTab = openRouteMapInNewTab;
window.openRouteMapInNewTabFromUrl = openRouteMapInNewTabFromUrl;

initRouteMapModalViewer();
