// Task Center: runs several pipeline jobs side by side (upload -> start -> poll) with a
// parallel limit and a FIFO queue. One job at a time is "focused" and mirrored on the
// Pipeline page; every other job keeps running and reporting in the background.

const JOB_STAGE_KEYS = ['intake', 'transformation', 'storage', 'report', 'pbi'];
const JOB_STAGE_LABELS = { intake: 'Profiling', transformation: 'Cleaning', storage: 'Staging', report: 'Reporting', pbi: 'Syncing' };
const JOB_ACTIVE_STATES = ['uploading', 'starting', 'running'];
const JOB_FINISHED_STATES = ['success', 'warning', 'failed', 'cancelled'];
const JOB_POLL_MS = 1500;
const JOB_RESUME_KEY = 'controlai_active_jobs';
const BASE_TITLE = document.title;

const jobManager = {
    jobs: [],
    focusedId: null,
    seq: 0
};

function maxParallelJobs() {
    const n = parseInt(localStorage.getItem('pref_max_parallel') || '3', 10);
    return n > 0 ? n : 3;
}

const isJobActive = (job) => JOB_ACTIVE_STATES.includes(job.status);
const isJobFinished = (job) => JOB_FINISHED_STATES.includes(job.status);
const activeJobs = () => jobManager.jobs.filter(isJobActive);
const findJob = (id) => jobManager.jobs.find(j => j.id === id);

function newJob(spec) {
    return {
        id: `job_${Date.now().toString(36)}_${++jobManager.seq}`,
        status: 'queued',
        progress: 0,
        stage: null,
        data: null,
        error: null,
        createdAt: Date.now(),
        startedAt: null,
        endedAt: null,
        pollTimer: null,
        ...spec
    };
}

// ---------- queue ----------

window.enqueueJob = function(spec) {
    const job = newJob(spec);
    jobManager.jobs.unshift(job);
    renderJobs();
    pumpJobQueue();
    return job;
};

function pumpJobQueue() {
    let free = maxParallelJobs() - activeJobs().length;
    // Oldest queued job first
    const queued = jobManager.jobs.filter(j => j.status === 'queued').reverse();
    for (const job of queued) {
        if (free <= 0) break;
        free--;
        runJob(job);
    }
}

async function uploadForJob(job) {
    if (job.kind === 'file') return uploadFile(job.file);
    if (job.kind === 'url') {
        return fetchJson('/api/v1/upload/url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: job.url })
        });
    }
    if (job.kind === 'stream') return uploadRealtimeStream(job.streamType, job.recordCount, job.cycle, job.streamUrl);
    if (job.kind === 'rerun') return { file_path: job.rawFile, batch_id: job.batchId };
    return null;
}

async function runJob(job) {
    job.status = 'uploading';
    job.startedAt = Date.now();
    renderJobs();

    let upload = null;
    try {
        upload = await uploadForJob(job);
    } catch (e) {
        job.error = e.message;
    }
    if (job.status === 'cancelled') return;
    if (!upload) return finishJob(job, 'failed', job.error || 'Upload failed.');

    job.batchId = upload.batch_id;
    job.rawFile = upload.file_path;
    if (!job.label) job.label = osBasename(upload.file_path);
    job.status = 'starting';
    renderJobs();

    const started = await startPipeline(upload.file_path, upload.batch_id);
    if (!started) return finishJob(job, 'failed', 'The pipeline could not be started.');

    job.status = 'running';
    persistActiveJobs();
    const focused = findJob(jobManager.focusedId);
    if (job.focusOnStart || !focused || !isJobActive(focused) || focused === job) focusJob(job.id);
    renderJobs();
    pollJob(job);
}

function pollJob(job) {
    clearTimeout(job.pollTimer);
    job.pollTimer = setTimeout(async () => {
        if (job.status !== 'running') return;
        try {
            const res = await fetch(`/api/v1/pipeline/status?pipeline_id=pipe_${encodeURIComponent(job.batchId)}`);
            if (res.status === 404) return finishJob(job, 'failed', 'This pipeline run no longer exists.');
            if (res.ok) {
                const data = await res.json();
                applyJobData(job, data);
                if (data.status === 'Success') return finishJob(job, 'success');
                if (data.status === 'Passed with Warnings') return finishJob(job, 'warning');
                if (data.status === 'Failed') return finishJob(job, 'failed', data.error || 'See the process log for details.');
            }
        } catch (e) {
            loggerError('pollJob', e);
        }
        pollJob(job);
    }, JOB_POLL_MS);
}

function applyJobData(job, data) {
    job.data = data;
    if (data.filename) job.label = data.filename;
    const stages = data.stages || {};
    let progress = 0;
    let stage = null;
    JOB_STAGE_KEYS.forEach((key, i) => {
        const status = (stages[key] || {}).status;
        if (status === 'completed') progress = Math.max(progress, (i + 1) * 20);
        else if (status === 'processing') { progress = Math.max(progress, i * 20 + 10); stage = key; }
        else if (status === 'failed') stage = key;
    });
    job.progress = progress;
    job.stage = stage;
    if (job.id === jobManager.focusedId) {
        state.currentPipelineData = data;
        updatePipelineMonitorUI(data);
        updateLogsConsole(data.logs || []);
    }
    renderJobs();
}

function finishJob(job, status, error) {
    clearTimeout(job.pollTimer);
    job.status = status;
    job.error = error || null;
    job.endedAt = Date.now();
    if (status === 'success' || status === 'warning') job.progress = 100;
    persistActiveJobs();
    renderJobs();

    const name = job.label || job.batchId || 'Pipeline run';
    const focused = job.id === jobManager.focusedId;
    if (status === 'failed') {
        if (focused) writeConsoleLog(`[System Failure] Pipeline execution aborted: ${job.error}`, 'text-red');
        showToast('error', `${name}: ${job.error}`);
        playAlertChime(false);
    } else if (status !== 'cancelled') {
        const secs = jobElapsedSeconds(job);
        if (focused) writeConsoleLog(`[System Success] Pipeline complete! Status: ${job.data.status}. Duration: ${secs.toFixed(2)}s`, 'text-green');
        showToast(status === 'success' ? 'success' : 'info', `${name}: ${job.data.status} in ${secs.toFixed(1)}s`);
        playAlertChime(true);
    }
    notifyDesktop(job);

    if (job.batchId && status !== 'cancelled') {
        // A run finished: refresh everything that depends on run results
        if (window.refreshNotifications) window.refreshNotifications();
        loadDashboardStats();
        loadChatBatchContexts();
        if (focused && status !== 'failed' && localStorage.getItem('pref_auto_ai') !== 'false') {
            fetchSelectedBatchInsights(job.batchId);
        }
    }
    pumpJobQueue();
}

// Browser notification for runs that finish while the tab is in the background
function notifyDesktop(job) {
    if (localStorage.getItem('pref_desktop_notify') !== 'true' || !document.hidden) return;
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const label = { success: 'finished successfully', warning: 'finished with warnings', failed: 'failed' }[job.status];
    if (!label) return;
    try {
        const n = new Notification(`Control AI: ${job.label || job.batchId}`, { body: `Pipeline ${label}.`, tag: job.id });
        n.onclick = () => { window.focus(); focusJob(job.id, { navigate: true }); n.close(); };
    } catch (e) { /* notifications are optional */ }
}

// ---------- tracking runs started elsewhere (history, reloads) ----------

window.trackPipelineRun = function(batchId, label, { focus = false, startTime = null, data = null } = {}) {
    let job = jobManager.jobs.find(j => j.batchId === batchId && isJobActive(j));
    if (!job) {
        const started = startTime ? parseUTCDate(startTime) : null;
        job = newJob({
            kind: 'adopted',
            label: label || batchId,
            batchId,
            status: 'running',
            startedAt: started && !isNaN(started) ? started.getTime() : Date.now()
        });
        jobManager.jobs.unshift(job);
        persistActiveJobs();
        pollJob(job);
    }
    if (data) job.data = data;
    if (focus && jobManager.focusedId !== job.id) focusJob(job.id);
    renderJobs();
    return job;
};

function persistActiveJobs() {
    try {
        const running = jobManager.jobs
            .filter(j => j.status === 'running' && j.batchId)
            .map(j => ({ batchId: j.batchId, label: j.label, startedAt: j.startedAt }));
        sessionStorage.setItem(JOB_RESUME_KEY, JSON.stringify(running));
    } catch (e) { /* storage unavailable */ }
}

// After a page reload, keep following the runs this tab had in flight
function resumePersistedJobs() {
    if (!getAuthToken()) return;
    let saved = [];
    try { saved = JSON.parse(sessionStorage.getItem(JOB_RESUME_KEY) || '[]'); } catch (e) { saved = []; }
    saved.forEach(s => {
        if (jobManager.jobs.some(j => j.batchId === s.batchId && isJobActive(j))) return;
        const job = newJob({ kind: 'adopted', label: s.label, batchId: s.batchId, status: 'running', startedAt: s.startedAt || Date.now() });
        jobManager.jobs.push(job);
        pollJob(job);
    });
    if (saved.length) renderJobs();
}

// ---------- focus (which job the Pipeline page shows) ----------

window.focusJob = function(id, { navigate = false } = {}) {
    const job = findJob(id);
    if (!job) return;
    jobManager.focusedId = id;
    if (navigate && window.activateView) window.activateView('pipeline-monitor-page');
    if (job.batchId) {
        state.currentBatchId = job.batchId;
        window.openPipelineMonitorOverlay(job.batchId, job.label, isJobActive(job) ? job.startedAt : null);
        const badge = document.getElementById('batch-badge-id');
        if (badge) badge.textContent = `Batch: ${job.batchId}`;
        if (job.data) {
            // Stages already done should not replay their completion burst when switching tasks
            const stages = job.data.stages || {};
            JOB_STAGE_KEYS.forEach(k => { if ((stages[k] || {}).status === 'completed') state.previousStageStatuses[k] = 'completed'; });
            state.currentPipelineData = job.data;
            updatePipelineMonitorUI(job.data);
            updateLogsConsole(job.data.logs || []);
        } else {
            state.currentPipelineData = null;
            clearConsole();
            writeConsoleLog(`[System] ${job.label || job.batchId}: ${jobStatusText(job)}`);
        }
    }
    renderJobs();
};

// The Pipeline page is about to show this batch: focus its task if it is one, otherwise no task
window.markFocusedBatch = function(batchId) {
    const current = findJob(jobManager.focusedId);
    if (current && current.batchId === batchId) return;
    const tracked = jobManager.jobs.find(j => j.batchId === batchId);
    jobManager.focusedId = tracked ? tracked.id : null;
    renderJobs();
};

// ---------- user actions ----------

function retryableSpec(job) {
    if (job.kind === 'file' && job.file) return { kind: 'file', file: job.file, label: job.file.name, size: job.file.size };
    if (job.kind === 'url') return { kind: 'url', url: job.url, label: job.label };
    if (job.rawFile && job.batchId) return { kind: 'rerun', rawFile: job.rawFile, batchId: job.batchId, label: job.label };
    return null;
}

function runJobAction(action, id) {
    const job = findJob(id);
    if (!job) return;
    if (action === 'focus') {
        focusJob(id, { navigate: true });
        closeTasksPanel();
    } else if (action === 'cancel' && job.status === 'queued') {
        job.status = 'cancelled';
        job.endedAt = Date.now();
        renderJobs();
    } else if (action === 'retry') {
        const spec = retryableSpec(job);
        if (spec) {
            jobManager.jobs = jobManager.jobs.filter(j => j !== job);
            enqueueJob({ ...spec, focusOnStart: true });
        }
    } else if (action === 'dismiss' && isJobFinished(job)) {
        jobManager.jobs = jobManager.jobs.filter(j => j !== job);
        if (jobManager.focusedId === id) jobManager.focusedId = null;
        renderJobs();
    }
}

window.clearFinishedJobs = function() {
    jobManager.jobs = jobManager.jobs.filter(j => !isJobFinished(j));
    if (!findJob(jobManager.focusedId)) jobManager.focusedId = null;
    renderJobs();
};

window.hasPendingStreamJob = function() {
    return jobManager.jobs.some(j => j.kind === 'stream' && (j.status === 'queued' || isJobActive(j)));
};

// ---------- rendering ----------

function jobElapsedSeconds(job) {
    if (job.data && !isJobActive(job) && typeof job.data.execution_time === 'number' && job.data.execution_time > 0) {
        return job.data.execution_time;
    }
    if (!job.startedAt) return 0;
    return ((job.endedAt || Date.now()) - job.startedAt) / 1000;
}

function fmtElapsed(seconds) {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    return `${m}m ${Math.round(seconds % 60)}s`;
}

function jobStatusText(job) {
    switch (job.status) {
        case 'queued': return 'Queued';
        case 'uploading': return 'Uploading';
        case 'starting': return 'Starting agents';
        case 'running': return `Running · ${JOB_STAGE_LABELS[job.stage] || 'Initializing'}`;
        case 'success': return 'Success';
        case 'warning': return 'Passed with warnings';
        case 'failed': return 'Failed';
        case 'cancelled': return 'Cancelled';
        default: return job.status;
    }
}

const JOB_KIND_ICONS = {
    file: 'fa-file-arrow-up',
    url: 'fa-link',
    stream: 'fa-satellite-dish',
    rerun: 'fa-rotate-right',
    adopted: 'fa-diagram-project'
};

function jobActionsHtml(job) {
    const btn = (action, icon, title) =>
        `<button class="job-action-btn" data-job-action="${action}" data-job-id="${job.id}" title="${title}" aria-label="${title}"><i class="fa-solid ${icon}"></i></button>`;
    const out = [];
    if (job.batchId) out.push(btn('focus', 'fa-eye', 'Show on the Pipeline page'));
    if (job.status === 'queued') out.push(btn('cancel', 'fa-xmark', 'Cancel'));
    if ((job.status === 'failed' || job.status === 'cancelled') && retryableSpec(job)) out.push(btn('retry', 'fa-rotate-right', 'Retry'));
    if (isJobFinished(job)) out.push(btn('dismiss', 'fa-trash-can', 'Remove from list'));
    return out.join('');
}

function jobItemHtml(job) {
    const focused = job.id === jobManager.focusedId ? ' focused' : '';
    const meta = [
        job.batchId ? `<code>${escapeHtml(job.batchId)}</code>` : '',
        job.status === 'queued' ? 'waiting for a free slot' : `<span data-job-elapsed="${job.id}"></span>`
    ].filter(Boolean).join(' · ');
    return `
        <div class="job-item is-${job.status}${focused}">
            <div class="job-icon"><i class="fa-solid ${JOB_KIND_ICONS[job.kind] || 'fa-file'}"></i></div>
            <div class="job-body">
                <div class="job-top">
                    <strong title="${escapeHtml(job.label || '')}">${escapeHtml(job.label || 'Pending upload')}</strong>
                    <span class="job-status">${escapeHtml(jobStatusText(job))}</span>
                </div>
                <div class="job-progress"><span style="width:${job.progress}%"></span></div>
                <div class="job-meta">${meta}${job.error ? ` · <span class="text-red" title="${escapeHtml(job.error)}">${escapeHtml(job.error.slice(0, 70))}</span>` : ''}</div>
            </div>
            <div class="job-actions">${jobActionsHtml(job)}</div>
        </div>`;
}

function jobListHtml(emptyText) {
    if (!jobManager.jobs.length) {
        return `<div class="job-empty"><i class="fa-solid fa-layer-group"></i><p>${emptyText}</p></div>`;
    }
    return jobManager.jobs.map(jobItemHtml).join('');
}

function jobSummary() {
    const running = activeJobs().length;
    const queued = jobManager.jobs.filter(j => j.status === 'queued').length;
    const done = jobManager.jobs.filter(isJobFinished).length;
    return { running, queued, done };
}

function renderJobStrip() {
    const tabs = document.getElementById('job-strip-tabs');
    if (!tabs) return;
    if (!jobManager.jobs.length) {
        setHtml(tabs, '<span class="job-strip-hint">Drop several files, or paste several URLs, and they run here side by side.</span>');
        return;
    }
    setHtml(tabs, jobManager.jobs.map(job => `
        <button class="job-tab is-${job.status}${job.id === jobManager.focusedId ? ' focused' : ''}" data-job-action="focus" data-job-id="${job.id}" title="${escapeHtml((job.label || '') + ' - ' + jobStatusText(job))}">
            <span class="job-dot"></span>
            <span class="job-tab-name">${escapeHtml(job.label || 'Pending upload')}</span>
            <span class="job-tab-meta">${job.status === 'running' ? `${job.progress}%` : escapeHtml(jobStatusText(job))}</span>
            <span class="job-tab-bar"><span style="width:${job.progress}%"></span></span>
        </button>`).join(''));
}

// Rewrites a container only when its markup changed, so polling never swaps buttons mid-click
function setHtml(el, html) {
    if (el._renderedHtml === html) return;
    el._renderedHtml = html;
    el.innerHTML = html;
}

function tickJobTimers() {
    jobManager.jobs.forEach(job => {
        document.querySelectorAll(`[data-job-elapsed="${job.id}"]`).forEach(el => {
            const text = fmtElapsed(jobElapsedSeconds(job));
            if (el.textContent !== text) el.textContent = text;
        });
    });
}

function renderJobs() {
    const { running, queued, done } = jobSummary();

    // Topbar + sidebar badges
    const badgeText = running + queued;
    [document.getElementById('btn-topbar-tasks'), document.getElementById('nav-tasks')].forEach(el => {
        if (!el) return;
        let dot = el.querySelector('.task-dot');
        if (badgeText) {
            if (!dot) { dot = document.createElement('span'); dot.className = 'task-dot'; el.appendChild(dot); }
            dot.textContent = badgeText > 99 ? '99+' : badgeText;
        } else if (dot) {
            dot.remove();
        }
    });
    const topBtn = document.getElementById('btn-topbar-tasks');
    if (topBtn) topBtn.classList.toggle('is-busy', running > 0);

    document.title = running ? `(${running}) ${BASE_TITLE}` : BASE_TITLE;

    const kpi = document.getElementById('stat-running-now');
    if (kpi) kpi.textContent = running;
    const kpiSub = document.getElementById('stat-running-sub');
    if (kpiSub) kpiSub.textContent = queued ? `${queued} queued · ${maxParallelJobs()} run in parallel` : `Up to ${maxParallelJobs()} run in parallel`;

    const dashList = document.getElementById('dash-jobs-list');
    if (dashList) setHtml(dashList, jobListHtml('No tasks in this session yet. Start a run from the Pipeline page.'));

    const panel = document.getElementById('tasks-panel');
    if (panel) {
        panel.querySelector('.tasks-panel-summary').textContent = `${running} running · ${queued} queued · ${done} finished`;
        setHtml(panel.querySelector('.tasks-panel-list'), jobListHtml('No tasks yet. Every upload, URL and stream cycle shows up here.'));
    }
    renderJobStrip();
    tickJobTimers();
}

// Elapsed timers tick without re-rendering (so buttons never move under the cursor)
setInterval(tickJobTimers, 1000);

// ---------- Task Center dropdown ----------

function closeTasksPanel() {
    const panel = document.getElementById('tasks-panel');
    if (panel) panel.remove();
    const btn = document.getElementById('btn-topbar-tasks');
    if (btn) btn.classList.remove('active');
}

window.toggleTasksPanel = function() {
    if (document.getElementById('tasks-panel')) { closeTasksPanel(); return; }
    document.getElementById('notifications-panel')?.remove();
    const btn = document.getElementById('btn-topbar-tasks');
    if (!btn) return;
    const panel = document.createElement('div');
    panel.id = 'tasks-panel';
    panel.className = 'tasks-panel';
    panel.innerHTML = `
        <div class="tasks-panel-head">
            <div>
                <strong>Task Center</strong>
                <span class="tasks-panel-summary text-secondary"></span>
            </div>
            <button class="btn-icon-subtle" data-tasks-clear title="Remove finished tasks"><i class="fa-solid fa-broom"></i> Clear finished</button>
        </div>
        <div class="tasks-panel-list"></div>`;
    btn.parentElement.appendChild(panel);
    btn.classList.add('active');
    renderJobs();
};

// ---------- wiring ----------

document.addEventListener('click', (e) => {
    const actionEl = e.target.closest('[data-job-action]');
    if (actionEl) {
        e.stopPropagation();
        runJobAction(actionEl.getAttribute('data-job-action'), actionEl.getAttribute('data-job-id'));
        return;
    }
    if (e.target.closest('[data-tasks-clear]')) {
        window.clearFinishedJobs();
        return;
    }
    const panel = document.getElementById('tasks-panel');
    if (panel && !panel.contains(e.target) && !e.target.closest('#btn-topbar-tasks') && !e.target.closest('#nav-tasks')) {
        closeTasksPanel();
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const toggle = (e) => { e.stopPropagation(); window.toggleTasksPanel(); };
    document.getElementById('btn-topbar-tasks')?.addEventListener('click', toggle);
    document.getElementById('nav-tasks')?.addEventListener('click', toggle);
    document.getElementById('btn-job-strip-add')?.addEventListener('click', () => {
        window.switchIngestMode('batch');
        document.getElementById('file-input')?.click();
    });
    renderJobs();
    resumePersistedJobs();
    window.addEventListener('controlai_login_success', resumePersistedJobs);
});
