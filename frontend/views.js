// Page views: History, Reports, Logs, Storage and Power BI, plus header notifications.
// Every view is populated from the API; nothing here is hard-coded sample data.

const viewState = {
    history: [],
    reports: [],
    logsSelectedBatch: null,
    logsText: '',
    logsRefreshTimer: null,
    notificationsSeenAt: null,
    historySelected: new Set() // batch ids ticked for a bulk re-run
};

// ---------- small helpers ----------

function fmtDateTime(value) {
    if (!value) return '-';
    const d = parseUTCDate(value);
    return isNaN(d) ? '-' : d.toLocaleString();
}

function fmtBytes(bytes) {
    if (bytes == null) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let value = bytes;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
    return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function statusBadge(status) {
    const cls = status === 'Success' ? 'success'
        : status === 'Passed with Warnings' ? 'warning'
        : status === 'Failed' ? 'failed'
        : status === 'Running' ? 'running' : '';
    return `<span class="badge ${cls}">${escapeHtml(status || '-')}</span>`;
}

function emptyRow(colspan, text) {
    return `<tr><td colspan="${colspan}" class="text-center text-secondary">${text}</td></tr>`;
}

async function fetchJson(url, options) {
    const res = await fetch(url, options);
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON body */ }
    if (!res.ok) throw new Error((data && data.detail) || `Request failed (${res.status})`);
    return data;
}

// ---------- History ----------

window.loadHistoryView = async function() {
    const tbody = document.querySelector('#history-table tbody');
    if (!tbody) return;
    try {
        viewState.history = await fetchJson('/api/v1/history');
        renderHistoryKpis();
        renderHistoryTable();
    } catch (e) {
        tbody.innerHTML = emptyRow(9, `Failed to load history: ${escapeHtml(e.message)}`);
    }
};

function renderHistoryKpis() {
    const el = document.getElementById('history-kpis');
    if (!el) return;
    const runs = viewState.history;
    const count = s => runs.filter(r => r.status === s).length;
    const rows = runs.reduce((sum, r) => sum + (r.rows_loaded || 0), 0);
    const rejected = runs.reduce((sum, r) => sum + (r.rows_rejected || 0), 0);
    const cards = [
        ['Total Uploads', runs.length, 'fa-upload', ''],
        ['Successful Runs', count('Success'), 'fa-circle-check', 'green'],
        ['With Warnings', count('Passed with Warnings'), 'fa-triangle-exclamation', 'orange'],
        ['Failed Runs', count('Failed'), 'fa-circle-xmark', 'red'],
        ['Rows Loaded', rows.toLocaleString(), 'fa-database', ''],
        ['Rows Rejected', rejected.toLocaleString(), 'fa-ban', 'red']
    ];
    el.innerHTML = cards.map(([label, value, icon, color]) => `
        <div class="kpi-card">
            <div class="kpi-card-head"><span>${label}</span><div class="kpi-card-icon ${color}"><i class="fa-solid ${icon}"></i></div></div>
            <div class="kpi-card-value">${value}</div>
        </div>`).join('');
}

function renderHistoryTable() {
    const tbody = document.querySelector('#history-table tbody');
    const query = (document.getElementById('history-search')?.value || '').toLowerCase();
    const statusFilter = document.getElementById('history-status-filter')?.value || 'all';
    const runs = viewState.history.filter(r =>
        (statusFilter === 'all' || r.status === statusFilter) &&
        (!query || (r.filename || '').toLowerCase().includes(query) || r.batch_id.toLowerCase().includes(query))
    );
    if (!runs.length) {
        tbody.innerHTML = emptyRow(9, viewState.history.length ? 'No runs match the filter.' : 'No uploads yet. Run a dataset from the Pipeline page.');
        syncHistorySelection([]);
        return;
    }
    tbody.innerHTML = runs.map(r => {
        const selectable = !!r.raw_file && r.status !== 'Running';
        const checkbox = selectable
            ? `<input type="checkbox" class="row-check" data-history-select="${escapeHtml(r.batch_id)}" ${viewState.historySelected.has(r.batch_id) ? 'checked' : ''} aria-label="Select ${escapeHtml(r.filename || r.batch_id)}">`
            : '';
        const quality = r.quality_after != null
            ? `${r.quality_before != null ? r.quality_before + '% &rarr; ' : ''}<strong>${r.quality_after}%</strong>` : '-';
        const rows = r.rows_loaded != null ? `${(r.rows_loaded).toLocaleString()} / <span class="${r.rows_rejected ? 'text-red' : ''}">${(r.rows_rejected || 0).toLocaleString()}</span>` : '-';
        const reportBtns = ['pdf', 'docx'].map(fmt => r.reports && r.reports[fmt]
            ? `<button class="btn-refresh" onclick="downloadReport('${r.batch_id}', '${fmt}')" title="Download ${fmt.toUpperCase()} report"><i class="fa-solid ${fmt === 'pdf' ? 'fa-file-pdf' : 'fa-file-word'}"></i></button>`
            : '').join('');
        const cleanBtn = r.clean_file ? `<button class="btn-refresh" onclick="downloadNodeData(${jsArg(r.clean_file)})" title="Download cleaned data"><i class="fa-solid fa-broom"></i></button>` : '';
        const rerunBtn = r.raw_file && r.status !== 'Running' ? `<button class="btn-refresh" onclick="rerunBatch('${r.batch_id}')" title="Run the pipeline again on this file"><i class="fa-solid fa-rotate-right"></i></button>` : '';
        return `
            <tr class="${viewState.historySelected.has(r.batch_id) ? 'row-selected' : ''}">
                <td class="check-cell">${checkbox}</td>
                <td><strong>${escapeHtml(r.filename || '-')}</strong><div class="text-secondary cell-sub">${escapeHtml(r.source || '')}</div></td>
                <td><code>${r.batch_id}</code></td>
                <td>${fmtDateTime(r.uploaded_at)}</td>
                <td>${statusBadge(r.status)}${r.error ? `<div class="text-red cell-sub" title="${escapeHtml(r.error)}">${escapeHtml(r.error.slice(0, 60))}</div>` : ''}</td>
                <td>${rows}</td>
                <td>${quality}</td>
                <td>${r.execution_time != null ? r.execution_time.toFixed(1) + 's' : '-'}</td>
                <td class="actions-cell">
                    <button class="btn-refresh" onclick="openRunLog('${r.batch_id}')" title="View process log"><i class="fa-solid fa-terminal"></i> Log</button>
                    <button class="btn-refresh" onclick="selectBatchDetail('${r.batch_id}')" title="Open in the pipeline view"><i class="fa-solid fa-diagram-project"></i></button>
                    ${reportBtns}${cleanBtn}${rerunBtn}
                    ${r.clean_file || r.raw_file ? `<button class="btn-refresh" onclick="previewRun('${r.batch_id}')" title="Preview data & column profile"><i class="fa-solid fa-table"></i></button>` : ''}
                    ${r.status !== 'Running' ? `<button class="btn-refresh btn-danger-soft" onclick="deleteRun('${r.batch_id}')" title="Delete this run"><i class="fa-solid fa-trash-can"></i></button>` : ''}
                </td>
            </tr>`;
    }).join('');
    syncHistorySelection(runs);
}

// Keeps the header checkbox and the bulk re-run button in step with the ticked rows
function syncHistorySelection(visibleRuns) {
    const selectableIds = visibleRuns.filter(r => r.raw_file && r.status !== 'Running').map(r => r.batch_id);
    // Drop selections that are no longer re-runnable (e.g. now running)
    const valid = new Set(viewState.history.filter(r => r.raw_file && r.status !== 'Running').map(r => r.batch_id));
    viewState.historySelected.forEach(id => { if (!valid.has(id)) viewState.historySelected.delete(id); });

    const all = document.getElementById('history-select-all');
    if (all) {
        const ticked = selectableIds.filter(id => viewState.historySelected.has(id)).length;
        all.checked = selectableIds.length > 0 && ticked === selectableIds.length;
        all.indeterminate = ticked > 0 && ticked < selectableIds.length;
        all.disabled = !selectableIds.length;
    }
    const btn = document.getElementById('btn-history-rerun-selected');
    if (btn) {
        const n = viewState.historySelected.size;
        btn.disabled = n === 0;
        btn.innerHTML = `<i class="fa-solid fa-layer-group"></i> Re-run selected${n ? ` (${n})` : ''}`;
    }
}

function queueRerun(run, focusOnStart) {
    enqueueJob({ kind: 'rerun', rawFile: run.raw_file, batchId: run.batch_id, label: run.filename, focusOnStart });
}

window.rerunBatch = function(batchId) {
    const run = viewState.history.find(r => r.batch_id === batchId);
    if (!run || !run.raw_file) return;
    queueRerun(run, true);
    showToast('info', `Re-running ${run.filename}...`);
    if (window.activateView) window.activateView('pipeline-monitor-page');
};

window.rerunSelectedBatches = function() {
    const runs = viewState.history.filter(r => viewState.historySelected.has(r.batch_id) && r.raw_file && r.status !== 'Running');
    if (!runs.length) return;
    runs.forEach(run => queueRerun(run, false));
    viewState.historySelected.clear();
    renderHistoryTable();
    showToast('info', `${runs.length} re-run(s) queued. Up to ${maxParallelJobs()} run at the same time; follow them in the Task Center.`);
};

// ---------- Reports ----------

window.loadReportsView = async function() {
    const grid = document.getElementById('reports-grid');
    if (!grid) return;
    try {
        const [folders, history] = await Promise.all([
            fetchJson('/api/v1/reports/folders'),
            fetchJson('/api/v1/history')
        ]);
        const byBatch = Object.fromEntries(history.map(h => [h.batch_id, h]));
        viewState.reports = folders.map(f => ({ ...f, run: byBatch[f.batch_id] }));
        renderReportsGrid();
    } catch (e) {
        grid.innerHTML = `<p class="text-red">Failed to load reports: ${escapeHtml(e.message)}</p>`;
    }
};

function renderReportsGrid() {
    const grid = document.getElementById('reports-grid');
    const query = (document.getElementById('reports-search')?.value || '').toLowerCase();
    const items = viewState.reports.filter(r => !query || (r.dataset_name || '').toLowerCase().includes(query) || (r.batch_id || '').toLowerCase().includes(query));
    if (!items.length) {
        grid.innerHTML = `<div class="dash-panel empty-panel"><i class="fa-solid fa-file-circle-question"></i><p>${viewState.reports.length ? 'No reports match your search.' : 'No reports yet. Reports are generated automatically at the end of every pipeline run.'}</p></div>`;
        return;
    }
    const formats = [['pdf', 'PDF', 'fa-file-pdf'], ['docx', 'Word', 'fa-file-word'], ['markdown', 'Markdown', 'fa-file-code'], ['json', 'JSON', 'fa-file-lines']];
    grid.innerHTML = items.map(r => {
        const run = r.run || {};
        return `
            <div class="dash-panel report-card">
                <div class="report-card-head">
                    <div>
                        <h3><i class="fa-solid fa-folder-open text-yellow"></i> ${escapeHtml(r.dataset_name || r.folder_name)}</h3>
                        <span class="text-secondary">Batch <code>${escapeHtml(r.batch_id || '-')}</code> &middot; ${fmtDateTime(r.created_at)}</span>
                    </div>
                    ${statusBadge(run.status)}
                </div>
                <div class="report-card-stats">
                    <span><strong>${run.rows_loaded != null ? run.rows_loaded.toLocaleString() : '-'}</strong> loaded</span>
                    <span><strong class="${run.rows_rejected ? 'text-red' : ''}">${run.rows_rejected != null ? run.rows_rejected.toLocaleString() : '-'}</strong> rejected</span>
                    <span><strong>${run.quality_after != null ? run.quality_after + '%' : '-'}</strong> quality</span>
                </div>
                <div class="report-card-actions">
                    ${formats.map(([fmt, label, icon]) => r.formats && r.formats[fmt]
                        ? `<button class="btn-download-file" onclick="downloadReport('${r.batch_id}', '${fmt}')"><i class="fa-solid ${icon}"></i> ${label}</button>`
                        : `<button class="btn-download-file" disabled title="Not generated"><i class="fa-solid ${icon}"></i> ${label}</button>`).join('')}
                    ${r.batch_id ? `<button class="btn-refresh" onclick="openRunLog('${r.batch_id}')"><i class="fa-solid fa-terminal"></i> Log</button>` : ''}
                </div>
            </div>`;
    }).join('');
}

// ---------- Logs ----------

window.loadLogsView = async function() {
    const list = document.getElementById('logs-run-list');
    if (!list) return;
    try {
        viewState.history = await fetchJson('/api/v1/history');
        renderLogsRunList();
        const target = viewState.logsSelectedBatch || (viewState.history.find(r => r.status !== 'Not Run') || {}).batch_id;
        if (target) loadRunLog(target);
    } catch (e) {
        list.innerHTML = `<p class="text-red">Failed to load runs: ${escapeHtml(e.message)}</p>`;
    }
};

function renderLogsRunList() {
    const list = document.getElementById('logs-run-list');
    const query = (document.getElementById('logs-search')?.value || '').toLowerCase();
    const runs = viewState.history.filter(r => !query || (r.filename || '').toLowerCase().includes(query) || r.batch_id.toLowerCase().includes(query));
    if (!runs.length) {
        list.innerHTML = `<p class="text-secondary">${viewState.history.length ? 'No runs match.' : 'No runs yet.'}</p>`;
        return;
    }
    list.innerHTML = runs.map(r => `
        <button class="logs-run-item ${r.batch_id === viewState.logsSelectedBatch ? 'active' : ''}" onclick="loadRunLog('${r.batch_id}')">
            <div class="logs-run-item-top"><strong>${escapeHtml(r.filename || r.batch_id)}</strong>${statusBadge(r.status)}</div>
            <span class="text-secondary">${r.batch_id} &middot; ${fmtDateTime(r.started_at || r.uploaded_at)}</span>
        </button>`).join('');
}

window.loadRunLog = async function(batchId) {
    viewState.logsSelectedBatch = batchId;
    renderLogsRunList();
    const viewer = document.getElementById('log-viewer-content');
    const title = document.getElementById('logs-viewer-title');
    const meta = document.getElementById('logs-viewer-meta');
    const run = viewState.history.find(r => r.batch_id === batchId) || {};
    if (title) title.textContent = run.filename ? `${run.filename}.log` : `${batchId}.log`;
    if (meta) meta.innerHTML = `${statusBadge(run.status)} &nbsp;Batch ${batchId}`;
    try {
        const res = await fetch(`/api/v1/history/${encodeURIComponent(batchId)}/log`);
        if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load log');
        viewState.logsText = await res.text();
        if (viewer) {
            viewer.textContent = viewState.logsText;
            viewer.scrollTop = viewer.scrollHeight;
        }
        document.getElementById('btn-logs-copy').disabled = false;
        document.getElementById('btn-logs-download').disabled = false;
    } catch (e) {
        if (viewer) viewer.textContent = `Could not load the log: ${e.message}`;
    }
    // Keep a running pipeline's log live
    clearTimeout(viewState.logsRefreshTimer);
    const logsVisible = document.getElementById('logs-view')?.classList.contains('active');
    if (logsVisible && viewState.logsText.includes('Status       : Running')) {
        viewState.logsRefreshTimer = setTimeout(() => window.loadLogsView(), 2000);
    }
};

// Opens the Logs page focused on one run (used by History, Reports, Dashboard)
window.openRunLog = function(batchId) {
    viewState.logsSelectedBatch = batchId;
    if (window.activateView) window.activateView('logs-view');
};

// ---------- Storage ----------

async function loadExplorerFiles() {
    const tbody = document.querySelector('#explorer-files-table tbody');
    if (!getAuthToken()) return;
    try {
        const data = await fetchJson('/api/v1/dashboard/datasets');
        state.explorerFiles = data.files || [];
        const counts = { all: state.explorerFiles.length };
        state.explorerFiles.forEach(f => { counts[f.category] = (counts[f.category] || 0) + 1; });
        ['all', 'raw', 'cleaned', 'report', 'log', 'powerbi'].forEach(key => {
            const el = document.getElementById(`folder-${key}-count`);
            if (el) el.textContent = `${counts[key] || 0} files`;
        });
        renderExplorerFiles();
    } catch (e) {
        if (tbody) tbody.innerHTML = emptyRow(6, `Failed to load storage: ${escapeHtml(e.message)}`);
    }
};

function renderExplorerFiles() {
    const tbody = document.querySelector('#explorer-files-table tbody');
    if (!tbody) return;
    const folder = state.explorerFolderFilter || 'all';
    const query = state.explorerSearchQuery || '';
    const files = (state.explorerFiles || []).filter(f =>
        (folder === 'all' || f.category === folder) &&
        (!query || f.name.toLowerCase().includes(query) || f.directory.toLowerCase().includes(query))
    );
    if (!files.length) {
        tbody.innerHTML = emptyRow(6, (state.explorerFiles || []).length ? 'No files match.' : 'Your workspace is empty. Upload and run a dataset to create files.');
        return;
    }
    const icons = { raw: 'fa-file-import text-purple', cleaned: 'fa-broom text-green', report: 'fa-file-pdf text-red', log: 'fa-file-lines text-yellow', powerbi: 'fa-chart-column text-orange' };
    tbody.innerHTML = files.map(f => `
        <tr>
            <td><i class="fa-solid ${icons[f.category] || 'fa-file'}"></i> <strong>${escapeHtml(f.name)}</strong></td>
            <td><code>${escapeHtml(f.directory)}</code></td>
            <td><span class="badge">${escapeHtml(f.format)}</span></td>
            <td>${fmtBytes(f.size)}</td>
            <td>${new Date(f.modified_time).toLocaleString()}</td>
            <td><button class="btn-download-file" onclick="downloadDataFile(${jsArg(f.path)})"><i class="fa-solid fa-download"></i> Download</button></td>
        </tr>`).join('');
};

// ---------- Power BI ----------

window.loadPowerBIView = async function() {
    const tbody = document.querySelector('#pbi-tables-table tbody');
    try {
        const [status, schema, measures] = await Promise.all([
            fetchJson('/api/v1/powerbi/status'),
            fetchJson('/api/v1/powerbi/schema'),
            fetchJson('/api/v1/powerbi/measures')
        ]);
        const conn = status.connector;
        document.getElementById('pbi-conn-status').textContent =
            `${conn.driver}: ${conn.status} (${conn.server}${conn.latency_ms != null ? `, ${conn.latency_ms} ms` : ''})`;
        document.getElementById('pbi-sync-meta').innerHTML = status.dataset.last_refresh
            ? `Last export ${fmtDateTime(status.dataset.last_refresh)} &middot; ${status.dataset.total_refreshes} export(s) &middot; Folder: <code>${escapeHtml(status.dataset.export_folder)}</code>`
            : `Not exported yet &middot; exports are written to <code>${escapeHtml(status.dataset.export_folder)}</code>`;

        const schemaByName = {};
        [...schema.fact_tables, ...schema.dimension_tables].forEach(t => { schemaByName[t.name] = t; });
        tbody.innerHTML = status.tables.map(t => {
            const def = schemaByName[t.name] || {};
            return `
                <tr>
                    <td><strong>${t.name}</strong><div class="text-secondary cell-sub">${t.name.startsWith('Dim') ? 'Dimension' : 'Fact'}</div></td>
                    <td><code>${escapeHtml(def.source || '-')}</code></td>
                    <td class="cell-sub">${(def.columns || []).map(c => `<code>${c}</code>`).join(' ')}</td>
                    <td>${t.rows.toLocaleString()}</td>
                    <td>${t.file ? `<button class="btn-download-file" onclick="downloadDataFile(${jsArg(t.file)})"><i class="fa-solid fa-download"></i> CSV</button>` : '<span class="text-secondary">Export first</span>'}</td>
                </tr>`;
        }).join('');

        document.getElementById('pbi-measures-list').innerHTML = measures.measures.map(m => `
            <div class="pbi-measure">
                <div class="pbi-measure-head"><strong>${escapeHtml(m.name)}</strong><span class="badge">${escapeHtml(m.category)}</span></div>
                <code class="pbi-measure-formula">${escapeHtml(m.name)} = ${escapeHtml(m.formula)}</code>
                <button class="btn-icon-subtle" title="Copy DAX" onclick="copyText(this.previousElementSibling.textContent)"><i class="fa-solid fa-copy"></i></button>
            </div>`).join('');
    } catch (e) {
        if (tbody) tbody.innerHTML = emptyRow(5, `Failed to load Power BI status: ${escapeHtml(e.message)}`);
    }
};

window.copyText = function(textValue) {
    navigator.clipboard.writeText(textValue).then(() => showToast('success', 'Copied to clipboard.'));
};

// ---------- Notifications (recent run outcomes) ----------

window.refreshNotifications = async function() {
    const btn = document.getElementById('btn-topbar-notifications');
    if (!btn || !getAuthToken()) return;
    try {
        viewState.history = await fetchJson('/api/v1/history?limit=50');
        const seenAt = localStorage.getItem('notifications_seen_at');
        const unseen = viewState.history.filter(r => r.ended_at && (!seenAt || parseUTCDate(r.ended_at) > new Date(seenAt)));
        let dot = btn.querySelector('.notif-dot');
        if (unseen.length) {
            if (!dot) {
                dot = document.createElement('span');
                dot.className = 'notif-dot';
                btn.appendChild(dot);
            }
            dot.textContent = unseen.length > 9 ? '9+' : unseen.length;
        } else if (dot) {
            dot.remove();
        }
    } catch (e) { /* not signed in yet */ }
};

window.toggleNotifications = function() {
    let panel = document.getElementById('notifications-panel');
    if (panel) { panel.remove(); return; }
    const btn = document.getElementById('btn-topbar-notifications');
    panel = document.createElement('div');
    panel.id = 'notifications-panel';
    panel.className = 'notifications-panel';
    const finished = viewState.history.filter(r => r.ended_at).slice(0, 10);
    panel.innerHTML = `
        <div class="notifications-head"><strong>Recent pipeline runs</strong><button class="btn-icon-subtle" onclick="openHistoryFromNotifications()">View all</button></div>
        ${finished.length ? finished.map(r => `
            <button class="notification-item" onclick="openRunLog('${r.batch_id}'); document.getElementById('notifications-panel')?.remove();">
                <div>${statusBadge(r.status)} <strong>${escapeHtml(r.filename || r.batch_id)}</strong></div>
                <span class="text-secondary">${fmtDateTime(r.ended_at)} &middot; ${r.rows_loaded ?? 0} loaded, ${r.rows_rejected ?? 0} rejected</span>
            </button>`).join('') : '<p class="text-secondary" style="padding:12px;">No finished runs yet.</p>'}`;
    btn.parentElement.appendChild(panel);
    localStorage.setItem('notifications_seen_at', new Date().toISOString());
    const dot = btn.querySelector('.notif-dot');
    if (dot) dot.remove();
};

window.openHistoryFromNotifications = function() {
    document.getElementById('notifications-panel')?.remove();
    if (window.activateView) window.activateView('history-view');
};

// ---------- wiring ----------

document.addEventListener('DOMContentLoaded', () => {
    const on = (id, event, handler) => { const el = document.getElementById(id); if (el) el.addEventListener(event, handler); };

    on('history-search', 'input', renderHistoryTable);
    on('history-status-filter', 'change', renderHistoryTable);
    on('btn-refresh-history', 'click', () => window.loadHistoryView());
    on('btn-history-compare', 'click', () => {
        const ticked = [...viewState.historySelected];
        window.openCompareRuns(ticked.length === 2 ? ticked : []);
    });
    on('btn-history-export', 'click', () => window.exportHistory());
    on('btn-history-rerun-selected', 'click', () => window.rerunSelectedBatches());
    on('history-select-all', 'change', (e) => {
        document.querySelectorAll('#history-table [data-history-select]').forEach(box => {
            const id = box.getAttribute('data-history-select');
            if (e.target.checked) viewState.historySelected.add(id);
            else viewState.historySelected.delete(id);
        });
        renderHistoryTable();
    });
    on('history-table', 'change', (e) => {
        const box = e.target.closest('[data-history-select]');
        if (!box) return;
        const id = box.getAttribute('data-history-select');
        if (box.checked) viewState.historySelected.add(id);
        else viewState.historySelected.delete(id);
        box.closest('tr')?.classList.toggle('row-selected', box.checked);
        syncHistorySelection(Array.from(document.querySelectorAll('#history-table [data-history-select]'))
            .map(b => viewState.history.find(r => r.batch_id === b.getAttribute('data-history-select')))
            .filter(Boolean));
    });
    on('btn-refresh-explorer', 'click', () => loadExplorerFiles());
    on('explorer-search', 'input', (e) => {
        state.explorerSearchQuery = e.target.value.toLowerCase();
        renderExplorerFiles();
    });
    document.querySelectorAll('#storage-folders .folder-card').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('#storage-folders .folder-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            state.explorerFolderFilter = card.getAttribute('data-folder');
            renderExplorerFiles();
        });
    });
    on('reports-search', 'input', renderReportsGrid);
    on('btn-refresh-reports', 'click', () => window.loadReportsView());
    on('logs-search', 'input', renderLogsRunList);
    on('btn-refresh-logs', 'click', () => window.loadLogsView());
    on('btn-logs-copy', 'click', () => window.copyText(viewState.logsText));
    on('btn-logs-download', 'click', () => {
        if (viewState.logsSelectedBatch) window.open(`/api/v1/history/${encodeURIComponent(viewState.logsSelectedBatch)}/log?download=true`, '_blank');
    });
    on('btn-trigger-pbi-refresh', 'click', async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Exporting...';
        try {
            const data = await fetchJson('/api/v1/powerbi/refresh', { method: 'POST' });
            const total = Object.values(data.tables).reduce((s, t) => s + t.rows, 0);
            showToast('success', `Power BI dataset exported: ${Object.keys(data.tables).length} tables, ${total.toLocaleString()} rows.`);
            window.loadPowerBIView();
        } catch (err) {
            showToast('error', `Export failed: ${err.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Export / Refresh Dataset';
        }
    });

    // Real-time source switcher: show the URL field for live feeds, the size chips for the simulator
    const streamSelect = document.getElementById('stream-type-select');
    const syncStreamSource = () => {
        const live = streamSelect && streamSelect.value === 'live_url';
        const urlRow = document.getElementById('stream-url-row');
        const sizeRow = document.getElementById('stream-size-row');
        if (urlRow) urlRow.style.display = live ? 'flex' : 'none';
        if (sizeRow) sizeRow.style.display = live ? 'none' : 'flex';
    };
    if (streamSelect) streamSelect.addEventListener('change', syncStreamSource);
    syncStreamSource();

    // Close the notifications panel on outside click
    document.addEventListener('click', (e) => {
        const panel = document.getElementById('notifications-panel');
        if (panel && !panel.contains(e.target) && e.target.id !== 'btn-topbar-notifications') panel.remove();
    });

    // Profile display name comes from the server
    const syncProfileName = async () => {
        if (!getAuthToken()) return;
        try {
            const profile = await fetchJson('/api/v1/auth/profile');
            localStorage.setItem('controlai_username', profile.display_name);
            localStorage.setItem('controlai_email', profile.email);
            if (window.updateProfileUI) window.updateProfileUI();
        } catch (e) { /* ignore */ }
    };
    window.addEventListener('controlai_login_success', () => { syncProfileName(); window.refreshNotifications(); });
    syncProfileName();
    window.refreshNotifications();
    setInterval(window.refreshNotifications, 60000);
});
