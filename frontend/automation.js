// Automation: scheduled ingestion (Schedules page) and run notifications (Settings > Notifications).

const scheduleState = {
    list: [],
    refreshTimer: null
};

function fmtInterval(minutes) {
    if (minutes % 10080 === 0) return minutes === 10080 ? 'week' : `${minutes / 10080} weeks`;
    if (minutes % 1440 === 0) return minutes === 1440 ? 'day' : `${minutes / 1440} days`;
    if (minutes % 60 === 0) return minutes === 60 ? 'hour' : `${minutes / 60} hours`;
    return `${minutes} min`;
}

// "in 12 min" / "3 h ago" relative to now
function fmtRelative(iso) {
    if (!iso) return '-';
    const diff = (parseUTCDate(iso) - Date.now()) / 1000;
    const abs = Math.abs(diff);
    const text = abs < 60 ? `${Math.max(1, Math.round(abs))} s`
        : abs < 3600 ? `${Math.round(abs / 60)} min`
        : abs < 86400 ? `${Math.round(abs / 3600)} h`
        : `${Math.round(abs / 86400)} d`;
    return diff >= 0 ? `in ${text}` : `${text} ago`;
}

// ---------- Schedules ----------

window.loadSchedulesView = async function() {
    const list = document.getElementById('schedules-list');
    if (!list) return;
    try {
        scheduleState.list = await fetchJson('/api/v1/schedules');
        renderSchedules();
    } catch (e) {
        list.innerHTML = `<p class="sheet-error">${escapeHtml(e.message)}</p>`;
    }
    // Keep statuses and countdowns current while the page is open
    clearInterval(scheduleState.refreshTimer);
    scheduleState.refreshTimer = setInterval(() => {
        if (!document.getElementById('schedules-view')?.classList.contains('active')) {
            clearInterval(scheduleState.refreshTimer);
            return;
        }
        if (!document.hidden) fetchJson('/api/v1/schedules').then(d => { scheduleState.list = d; renderSchedules(); }).catch(() => {});
    }, 10000);
};

function renderSchedules() {
    const list = document.getElementById('schedules-list');
    if (!list) return;
    if (!scheduleState.list.length) {
        list.innerHTML = `
            <div class="sheet-empty">
                <i class="fa-solid fa-calendar-plus"></i>
                <p>No schedules yet. Point one at a CSV, JSON, XML or Excel URL and the server keeps it fresh for you.</p>
            </div>`;
        return;
    }
    list.innerHTML = scheduleState.list.map(s => {
        const running = s.last_status === 'Running';
        const last = s.last_run_at
            ? `<span class="meta-inline">${statusBadge(s.last_status || '-')} <span class="text-secondary">${fmtRelative(s.last_run_at)}</span></span>`
              + (s.last_batch_id && !running ? ` <button class="link-btn" onclick="openRunDetails('${escapeHtml(s.last_batch_id)}')">View run</button>` : '')
            : (running ? statusBadge('Running') : '<span class="text-secondary">Not run yet</span>');
        return `
            <div class="schedule-row ${s.enabled ? '' : 'is-paused'}">
                <div class="schedule-main">
                    <div class="schedule-title">
                        <span class="schedule-dot ${s.enabled ? (running ? 'running' : 'on') : 'off'}"></span>
                        <strong>${escapeHtml(s.name)}</strong>
                        <span class="schedule-chip"><i class="fa-solid fa-rotate"></i> every ${fmtInterval(s.interval_minutes)}</span>
                        ${s.enabled ? '' : '<span class="schedule-chip muted">Paused</span>'}
                    </div>
                    <div class="schedule-url" title="${escapeHtml(s.url)}"><i class="fa-solid fa-link"></i> ${escapeHtml(s.url)}</div>
                    ${s.last_error ? `<div class="schedule-error"><i class="fa-solid fa-circle-exclamation"></i> ${escapeHtml(s.last_error)}</div>` : ''}
                </div>
                <div class="schedule-meta">
                    <div><span class="meta-label">Next run</span>${s.enabled && s.next_run_at ? `<span title="${fmtDateTime(s.next_run_at)}">${fmtRelative(s.next_run_at)}</span>` : '<span class="text-secondary">-</span>'}</div>
                    <div><span class="meta-label">Last run</span>${last}</div>
                    <div><span class="meta-label">Runs</span>${s.run_count}</div>
                </div>
                <div class="schedule-actions">
                    <button class="btn-icon" onclick="scheduleAction(${s.id}, 'run')" title="Run now" ${running ? 'disabled' : ''}><i class="fa-solid ${running ? 'fa-spinner fa-spin' : 'fa-play'}"></i></button>
                    <button class="btn-icon" onclick="scheduleAction(${s.id}, '${s.enabled ? 'pause' : 'resume'}')" title="${s.enabled ? 'Pause' : 'Resume'}"><i class="fa-solid ${s.enabled ? 'fa-pause' : 'fa-rotate-right'}"></i></button>
                    <button class="btn-icon danger" onclick="scheduleAction(${s.id}, 'delete')" title="Delete schedule"><i class="fa-solid fa-trash-can"></i></button>
                </div>
            </div>`;
    }).join('');
}

window.scheduleAction = async function(id, action) {
    const schedule = scheduleState.list.find(s => s.id === id);
    if (!schedule) return;
    try {
        if (action === 'run') {
            await fetchJson(`/api/v1/schedules/${id}/run`, { method: 'POST' });
            showToast('info', `Running "${schedule.name}" now. It appears in History when it starts.`);
        } else if (action === 'pause' || action === 'resume') {
            await fetchJson(`/api/v1/schedules/${id}`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: action === 'resume' })
            });
            showToast('success', `"${schedule.name}" ${action === 'pause' ? 'paused' : 'resumed'}.`);
        } else if (action === 'delete') {
            if (!confirmAction(`Delete the schedule "${schedule.name}"?\n\nRuns it already made stay in History.`)) return;
            await fetchJson(`/api/v1/schedules/${id}`, { method: 'DELETE' });
            showToast('success', `Schedule "${schedule.name}" deleted.`);
        }
    } catch (e) {
        showToast('error', e.message);
    }
    window.loadSchedulesView();
};

async function createSchedule(event) {
    event.preventDefault();
    const btn = document.getElementById('btn-schedule-create');
    const body = {
        name: document.getElementById('schedule-name').value.trim(),
        url: document.getElementById('schedule-url').value.trim(),
        interval_minutes: parseInt(document.getElementById('schedule-interval').value, 10),
        run_now: document.getElementById('schedule-run-now').checked
    };
    btn.disabled = true;
    try {
        await fetchJson('/api/v1/schedules', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        showToast('success', body.run_now ? `"${body.name}" created and running now.` : `"${body.name}" created. First run ${fmtRelative(new Date(Date.now() + body.interval_minutes * 60000).toISOString())}.`);
        event.target.reset();
        document.getElementById('schedule-interval').value = '60';
        window.loadSchedulesView();
    } catch (e) {
        showToast('error', e.message);
    } finally {
        btn.disabled = false;
    }
}

// ---------- Notifications ----------

function notifyForm() {
    return {
        webhook_url: document.getElementById('notify-webhook-url').value.trim(),
        notify_on: document.querySelector('input[name="notify-on"]:checked')?.value || 'all'
    };
}

async function loadNotificationSettings() {
    try {
        const data = await fetchJson('/api/v1/auth/notifications');
        document.getElementById('notify-webhook-url').value = data.webhook_url || '';
        const radio = document.querySelector(`input[name="notify-on"][value="${data.notify_on}"]`);
        if (radio) radio.checked = true;
    } catch (e) {
        showToast('error', `Could not load notification settings: ${e.message}`);
    }
}

async function withBusyButton(btn, work) {
    const html = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Working...';
    try { await work(); } finally { btn.disabled = false; btn.innerHTML = html; }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('schedule-form')?.addEventListener('submit', createSchedule);
    document.getElementById('btn-refresh-schedules')?.addEventListener('click', () => window.loadSchedulesView());

    document.getElementById('tab-btn-notifications')?.addEventListener('click', loadNotificationSettings);
    const testBtn = document.getElementById('btn-notify-test');
    testBtn?.addEventListener('click', () => withBusyButton(testBtn, async () => {
        try {
            const res = await fetchJson('/api/v1/auth/notifications/test', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notifyForm())
            });
            showToast('success', `Test message sent. ${res.detail}`);
        } catch (e) {
            showToast('error', e.message);
        }
    }));
    const saveBtn = document.getElementById('btn-notify-save');
    saveBtn?.addEventListener('click', () => withBusyButton(saveBtn, async () => {
        try {
            const saved = await fetchJson('/api/v1/auth/notifications', {
                method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notifyForm())
            });
            showToast('success', saved.webhook_url ? 'Notifications on. You will hear about ' + (saved.notify_on === 'failures' ? 'failed runs.' : 'every run.') : 'Notifications turned off.');
        } catch (e) {
            showToast('error', e.message);
        }
    }));
});
