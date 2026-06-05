document.addEventListener('DOMContentLoaded', () => initApp());

async function initApp() {
    initWorkbenchPanels();
    initTripForm();
    initPersonaForm();
    await loadSystemStatus();
    await loadPersona();
    setDefaultDate();
}

// ====== 面板切换 ======
function initWorkbenchPanels() {
    const railButtons = document.querySelectorAll('.rail-btn[data-panel]');
    const panelViews = document.querySelectorAll('.sidebar-view[data-panel-view]');

    railButtons.forEach(button => {
        button.addEventListener('click', () => {
            const target = button.dataset.panel;
            
            // 切换按钮状态
            railButtons.forEach(item => item.classList.toggle('is-active', item === button));
            
            // 切换面板显示
            panelViews.forEach(view => {
                view.classList.toggle('active', view.dataset.panelView === target);
            });
        });
    });
}

// ====== 行程表单 ======
function initTripForm() {
    const form = document.getElementById('trip-form');
    if (!form) return;

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        
        // 获取当前人物画像
        const persona = getPersonaData();
        
        const payload = {
            destination: document.getElementById('destination').value,
            start_date: document.getElementById('start-date').value,
            days: parseInt(document.getElementById('days').value),
            budget: parseFloat(document.getElementById('budget').value),
            persona: persona,
        };

        try {
            showLoading(true);
            
            // 调用 API 生成方案
            const response = await api.post('/api/trip/plan/sync', payload);
            
            if (response.success && response.data) {
                showResult(response.data);
                showNotification('方案生成成功！', 'success');
            } else {
                throw new Error(response.message || '生成失败');
            }
        } catch (error) {
            showNotification(error.message || '生成失败，请重试', 'error');
        } finally {
            showLoading(false);
        }
    });
}

// ====== 人物画像表单 ======
function initPersonaForm() {
    const form = document.getElementById('persona-form');
    const resetBtn = document.getElementById('reset-persona-btn');

    if (form) {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();

            try {
                const data = getPersonaData();
                await api.put('/api/persona/profile', data);
                
                // 更新显示
                updatePersonaDisplay(data);
                showNotification('人物画像已保存！', 'success');
            } catch (error) {
                showNotification(error.message || '保存失败', 'error');
            }
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            resetPersonaForm();
            showNotification('已恢复默认设置', 'info');
        });
    }
}

// 获取表单数据
function getPersonaData() {
    return {
        name: document.getElementById('persona-name')?.value || '旅行者',
        travel_style: document.getElementById('persona-style')?.value || 'classic_hot',
        energy_level: parseInt(document.getElementById('persona-energy')?.value || 3),
        budget_preference: document.getElementById('persona-budget-preference')?.value || 'balanced',
        notes: document.getElementById('persona-notes')?.value || '',
    };
}

// 加载人物画像
async function loadPersona() {
    try {
        const response = await api.get('/api/persona/profile');
        if (response.success && response.data) {
            populatePersonaForm(response.data);
            updatePersonaDisplay(response.data);
        }
    } catch (error) {
        console.warn('Failed to load persona:', error);
    }
}

// 填充表单
function populatePersonaForm(data) {
    if (!data) return;

    if (data.name && document.getElementById('persona-name')) {
        document.getElementById('persona-name').value = data.name;
    }

    if (data.travel_style && document.getElementById('persona-style')) {
        document.getElementById('persona-style').value = data.travel_style;
    }

    if (data.energy_level && document.getElementById('persona-energy')) {
        document.getElementById('persona-energy').value = data.energy_level;
        updateEnergyValue(data.energy_level);
    }

    if (data.budget_preference && document.getElementById('persona-budget-preference')) {
        document.getElementById('persona-budget-preference').value = data.budget_preference;
    }

    if (data.notes && document.getElementById('persona-notes')) {
        document.getElementById('persona-notes').value = data.notes;
    }
}

// 重置表单
function resetPersonaForm() {
    const defaults = {
        name: '旅行者',
        travel_style: 'classic_hot',
        energy_level: 3,
        budget_preference: 'balanced',
        notes: '',
    };

    populatePersonaForm(defaults);
    updatePersonaDisplay(defaults);
}

// 更新显示
function updatePersonaDisplay(data) {
    const nameEl = document.getElementById('persona-name-display');
    const styleEl = document.getElementById('persona-style-display');

    if (nameEl) nameEl.textContent = data.name || '旅行者';

    if (styleEl) {
        const styleMap = {
            classic_hot: '经典热门风格',
            offbeat: '小众探索风格',
            leisure: '休闲度假风格',
            adventure: '户外探险风格',
            cultural: '文化深度游风格',
        };
        styleEl.textContent = styleMap[data.travel_style] || '经典热门风格';
    }
}

// ====== 显示结果 ======
function showResult(data) {
    const emptyStage = document.getElementById('empty-stage');
    const resultSection = document.getElementById('result-section');
    
    if (emptyStage) emptyStage.style.display = 'none';
    if (resultSection) resultSection.style.display = 'block';

    renderTripResult(data);
}

// ====== 渲染旅行结果 ======
function renderTripResult(data) {
    const overviewGrid = document.getElementById('stage-overview-grid');
    const stageSections = document.getElementById('stage-sections');

    if (!overviewGrid || !stageSections) return;

    overviewGrid.innerHTML = '';
    stageSections.innerHTML = '';

    // 基础信息卡片
    const infoCards = [
        { title: '目的地', content: data.destination || '未知' },
        { title: '天数', content: `${data.days || 0} 天` },
        { title: '预算', content: `¥${(data.budget || 0).toLocaleString()}` },
        { title: '日期', content: data.start_date || '待定' },
    ];

    infoCards.forEach(card => {
        overviewGrid.innerHTML += `
            <div class="stage-overview-card">
                <strong>${escapeHtml(card.title)}</strong>
                <p>${escapeHtml(card.content)}</p>
            </div>
        `;
    });

    // 每日行程
    if (data.itinerary && Array.isArray(data.itinerary)) {
        data.itinerary.forEach((day, index) => {
            let spotsHtml = '';
            if (day.spots && Array.isArray(day.spots)) {
                spotsHtml = day.spots.map(spot => 
                    `<p class="spot-item">${escapeHtml(spot.name || spot)}</p>`
                ).join('');
            }

            stageSections.innerHTML += `
                <div class="stage-section">
                    <h4>第 ${index + 1} 天</h4>
                    ${spotsHtml}
                    ${day.summary ? `<p class="day-summary">${escapeHtml(day.summary)}</p>` : ''}
                </div>
            `;
        });
    }

    // 更新状态
    const resultStatus = document.getElementById('result-status');
    if (resultStatus) resultStatus.textContent = '已生成';
}

// ====== 加载系统状态 ======
async function loadSystemStatus() {
    try {
        const response = await api.get('/api/system/status');
        if (response.success && response.data) {
            updateSystemUI(response.data);
        }
    } catch (error) {
        console.warn('System status load failed:', error);
    }
}

function updateSystemUI(status) {
    const badge = document.getElementById('runtime-mode-badge');
    const title = document.getElementById('runtime-mode-title');
    const desc = document.getElementById('system-status-desc');
    const pills = document.getElementById('stage-capability-pills');

    const modeMap = { demo: '体验模式', hybrid: '混合模式' };
    const modeText = modeMap[status.app_mode] || '运行模式';

    if (badge) badge.dataset.mode = status.app_mode || 'demo';
    if (title) title.textContent = modeText;
    if (desc) desc.textContent = status.notes?.[0] || '系统能力检测完成';

    if (pills) {
        pills.innerHTML = [
            { label: status.trip_live_enabled ? '实时数据' : '演示数据', live: !!status.trip_live_enabled },
            { label: status.vision_enabled ? '识别可用' : '识别未启用', live: !!status.vision_enabled },
            { label: status.report_enabled ? 'PDF可用' : 'PDF未启用', live: !!status.report_enabled },
        ].map(item => 
            `<span class="capability-pill ${item.live ? 'is-live' : 'is-demo'}">${escapeHtml(item.label)}</span>`
        ).join('');
    }
}

// ====== 工具函数 ======
function setDefaultDate() {
    const dateInput = document.getElementById('start-date');
    if (dateInput && !dateInput.value) {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        dateInput.value = tomorrow.toISOString().split('T')[0];
    }
}

function updateDaysValue(value) {
    const display = document.getElementById('days-value');
    if (display) display.textContent = value;
}

function updateEnergyValue(value) {
    const display = document.getElementById('energy-value');
    if (!display) return;

    const labels = ['', '轻松', '较轻松', '中等', '较充沛', '充沛'];
    display.textContent = labels[parseInt(value)] || '中等';
}

function showLoading(isLoading) {
    const btn = document.querySelector('#trip-form .btn-primary');
    if (btn) {
        btn.disabled = isLoading;
        btn.textContent = isLoading ? '生成中...' : '生成方案';
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 简易通知（可后续优化为 toast 组件）
function showNotification(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);
    // 使用 helpers.js 中的完整实现
    if (typeof window.showNotification === 'function' && window.showNotification !== showNotification) {
        window.showNotification(message, type);
    }
}