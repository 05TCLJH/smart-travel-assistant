// 前端状态管理模块，负责保存页面运行时共享状态并提供读写接口。
class StateManager {
    constructor() {
        this.state = {};
    }

    init(initialState) {
        this.state = { ...initialState };
    }

    get(key) {
        return key ? this.state[key] : { ...this.state };
    }

    set(key, value) {
        this.state[key] = value;
    }
}

const PERSONA_SESSION_STORAGE_KEY = 'travel-assistant.persona';
const PERSONA_SESSION_FIELDS = ['name', 'travel_style', 'stamina', 'budget_style'];

function normalizePersonaSessionValue(value) {
    if (!value || typeof value !== 'object') return null;
    const compact = {};
    PERSONA_SESSION_FIELDS.forEach((field) => {
        if (value[field] !== undefined && value[field] !== null && String(value[field]).trim()) {
            compact[field] = String(value[field]).trim();
        }
    });
    return Object.keys(compact).length ? compact : null;
}

function readPersonaSession() {
    try {
        const raw = sessionStorage.getItem(PERSONA_SESSION_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return normalizePersonaSessionValue(parsed);
    } catch {
        return null;
    }
}

function writePersonaSession(value) {
    try {
        const normalized = normalizePersonaSessionValue(value);
        if (normalized) {
            sessionStorage.setItem(PERSONA_SESSION_STORAGE_KEY, JSON.stringify(normalized));
        } else {
            sessionStorage.removeItem(PERSONA_SESSION_STORAGE_KEY);
        }
    } catch {
        // sessionStorage 在隐私模式/受限环境下可能不可用，静默降级即可。
    }
}

const stateManager = new StateManager();
stateManager.init({
    persona: readPersonaSession(),
    tripResult: null,
    currentTaskId: null,
    visionResult: null,
    systemStatus: null,
    serviceAlerts: [],
});

function getPersona() { return stateManager.get('persona'); }
function setPersona(value) {
    const normalized = normalizePersonaSessionValue(value);
    stateManager.set('persona', normalized);
    writePersonaSession(normalized);
}
function getTripResult() { return stateManager.get('tripResult'); }
function setTripResult(value) { stateManager.set('tripResult', value); }
function getCurrentTaskId() { return stateManager.get('currentTaskId'); }
function setCurrentTaskId(value) { stateManager.set('currentTaskId', value); }
function setVisionResult(value) { stateManager.set('visionResult', value); }
function getSystemStatus() { return stateManager.get('systemStatus'); }
function setSystemStatus(value) { stateManager.set('systemStatus', value); }
function getServiceAlerts() { return stateManager.get('serviceAlerts') || []; }
function setServiceAlerts(value) { stateManager.set('serviceAlerts', Array.isArray(value) ? value : []); }

window.stateManager = stateManager;
window.getPersona = getPersona;
window.setPersona = setPersona;
window.getTripResult = getTripResult;
window.setTripResult = setTripResult;
window.getCurrentTaskId = getCurrentTaskId;
window.setCurrentTaskId = setCurrentTaskId;
window.setVisionResult = setVisionResult;
window.getSystemStatus = getSystemStatus;
window.setSystemStatus = setSystemStatus;
window.getServiceAlerts = getServiceAlerts;
window.setServiceAlerts = setServiceAlerts;
