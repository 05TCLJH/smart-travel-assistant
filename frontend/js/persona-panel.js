const TRAVEL_STYLE_OPTIONS = {
    classic_hot: {
        backendValue: '经典热门',
        label: '经典热门风格',
    },
    offbeat: {
        backendValue: '小众探索',
        label: '小众探索风格',
    },
    leisure: {
        backendValue: '休闲度假',
        label: '休闲度假风格',
    },
    adventure: {
        backendValue: '户外探险',
        label: '户外探险风格',
    },
    cultural: {
        backendValue: '文化深度游',
        label: '文化深度游风格',
    },
};

const BUDGET_OPTIONS = {
    economy: '经济',
    balanced: '舒适',
    comfort: '品质',
    luxury: '高品质',
};

const BUDGET_CODE_BY_BACKEND = {
    经济: 'economy',
    经济实惠: 'economy',
    舒适: 'balanced',
    平衡适中: 'balanced',
    品质: 'comfort',
    舒适品质: 'comfort',
    高品质: 'luxury',
};

const STAMINA_LABELS = {
    1: '轻松',
    2: '适中',
    3: '充沛',
};

const DEFAULT_PERSONA = Object.freeze({
    name: '旅行者',
    travel_style: TRAVEL_STYLE_OPTIONS.classic_hot.backendValue,
    stamina: '适中',
    budget_style: BUDGET_OPTIONS.balanced,
});

function getPersonaFieldValue(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const value = String(el.value ?? '').trim();
    return value || fallback;
}

function styleCodeFromBackend(value) {
    const target = String(value || '').trim();
    const matched = Object.entries(TRAVEL_STYLE_OPTIONS).find(([, config]) => config.backendValue === target);
    return matched?.[0] || 'classic_hot';
}

function budgetCodeFromBackend(value) {
    const target = String(value || '').trim();
    return BUDGET_CODE_BY_BACKEND[target] || 'balanced';
}

function staminaFromEnergy(value) {
    const energy = Number(value || 2);
    return STAMINA_LABELS[energy] || '适中';
}

function energyFromStamina(value) {
    const stamina = String(value || '适中').trim();
    if (stamina === '轻松') return 1;
    if (stamina === '充沛') return 3;
    return 2;
}

function setDefaultDate() {
    const dateInput = document.getElementById('start-date');
    if (!dateInput || dateInput.value) return;
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    dateInput.value = tomorrow.toISOString().split('T')[0];
}

function updateDaysValue(value) {
    const display = document.getElementById('days-value');
    if (display) display.textContent = String(value);
}

function updateEnergyValue(value) {
    const display = document.getElementById('energy-value');
    if (display) display.textContent = STAMINA_LABELS[Number(value)] || '适中';
}

function buildDefaultPersonaPayload() {
    return { ...DEFAULT_PERSONA };
}

async function loadPersona() {
    const persona = getPersona() || buildDefaultPersonaPayload();
    setPersona(persona);
    populatePersonaForm(persona);
    updatePersonaDisplay(persona);
}

function getPersonaPayload() {
    const current = getPersona() || {};
    const styleCode = getPersonaFieldValue('persona-style', 'classic_hot');
    const energyLevel = Number(getPersonaFieldValue('persona-energy', 2));
    return {
        name: getPersonaFieldValue('persona-name', current.name || DEFAULT_PERSONA.name),
        travel_style: (TRAVEL_STYLE_OPTIONS[styleCode] || TRAVEL_STYLE_OPTIONS.classic_hot).backendValue,
        stamina: staminaFromEnergy(energyLevel),
        budget_style: BUDGET_OPTIONS[getPersonaFieldValue('persona-budget-preference', 'balanced')] || BUDGET_OPTIONS.balanced,
    };
}

function populatePersonaForm(data) {
    const persona = data || DEFAULT_PERSONA;
    const nameInput = document.getElementById('persona-name');
    const styleInput = document.getElementById('persona-style');
    const energyInput = document.getElementById('persona-energy');
    const budgetInput = document.getElementById('persona-budget-preference');

    if (nameInput) nameInput.value = persona.name || DEFAULT_PERSONA.name;
    if (styleInput) styleInput.value = styleCodeFromBackend(persona.travel_style);
    if (energyInput) energyInput.value = energyFromStamina(persona.stamina);
    if (budgetInput) budgetInput.value = budgetCodeFromBackend(persona.budget_style);
    updateEnergyValue(energyInput?.value || 2);
}

function updatePersonaDisplay(data) {
    const persona = data || DEFAULT_PERSONA;
    const nameEl = document.getElementById('persona-name-display');
    const styleEl = document.getElementById('persona-style-display');
    if (nameEl) nameEl.textContent = persona.name || DEFAULT_PERSONA.name;
    if (styleEl) {
        const styleCode = styleCodeFromBackend(persona.travel_style);
        const label = TRAVEL_STYLE_OPTIONS[styleCode]?.label || '经典热门风格';
        styleEl.textContent = `${label} · ${persona.stamina || DEFAULT_PERSONA.stamina}体力`;
    }
}
