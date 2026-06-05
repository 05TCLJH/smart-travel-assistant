// 前端通用工具函数，负责日期、金额和展示文本等基础格式化逻辑。
function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value || '-');
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const weekDays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    return `${year}年${month}月${day}日 ${weekDays[date.getDay()]}`;
}

function formatCurrency(amount) {
    if (amount === null || amount === undefined || amount === '') return '¥0';
    return new Intl.NumberFormat('zh-CN', {
        style: 'currency',
        currency: 'CNY',
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
    }).format(amount);
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = String(value ?? '');
    return div.innerHTML;
}

function showNotification(message, type = 'info', duration = 3000) {
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();

    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <span class="notification-icon">${({ success: 'OK', error: 'ERR', warning: 'WARN', info: 'INFO' }[type] || 'INFO')}</span>
        <span class="notification-message">${escapeHtml(message)}</span>
        <button type="button" class="notification-close" aria-label="关闭">&times;</button>
    `;

    if (!document.getElementById('notification-styles-classic-v3')) {
        [
            'notification-styles-classic-v2',
            'notification-styles-classic',
            'notification-styles',
            'notification-styles-v4',
            'notification-styles-v5',
            'notification-styles-restored',
        ].forEach((id) => {
            document.getElementById(id)?.remove();
        });
        const style = document.createElement('style');
        style.id = 'notification-styles-classic-v3';
        style.textContent = `
            .notification{position:fixed;top:100px;right:20px;padding:1rem 1.25rem;border-radius:14px;background:rgba(255,255,255,.96);box-shadow:0 8px 24px rgba(91,163,160,.15);display:flex;align-items:center;gap:.8rem;z-index:3000;max-width:420px;border-left:4px solid #5BA3A0}
            .notification-success{border-left-color:#5BA3A0}
            .notification-info{border-left-color:#5BA3A0}
            .notification-warning{border-left-color:#f39c12}
            .notification-error{border-left-color:#e74c3c}
            .notification-message{flex:1;color:#2D5A54;font-size:.94rem;line-height:1.6}
            .notification-close{background:none;border:none;font-size:1.35rem;cursor:pointer;color:#7a9996}
            .notification-icon{font-size:.78rem;font-weight:700;letter-spacing:.03em;color:#5BA3A0}
            .notification-warning .notification-icon{color:#f39c12}
            .notification-error .notification-icon{color:#e74c3c}
        `;
        document.head.appendChild(style);
    }

    document.body.appendChild(notification);
    notification.querySelector('.notification-close').addEventListener('click', () => notification.remove());
    setTimeout(() => notification.remove(), duration);
}

window.formatDate = formatDate;
window.formatCurrency = formatCurrency;
window.escapeHtml = escapeHtml;
window.showNotification = showNotification;
