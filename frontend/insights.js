// Dashboard insights and run management: trend chart ranges, system status, dataset preview,
// run comparison, history export and run deletion. All data comes from the API.

const insightState = {
    chartRange: 'recent', // 'recent' | '14' | '30'
    systemLoading: false
};

// ---------- Dialog ----------

window.openSheet = function(title, subtitle, bodyHtml, wide = false) {
    const overlay = document.getElementById('sheet-overlay');
    if (!overlay) return;
    document.getElementById('sheet-title').textContent = title;
    document.getElementById('sheet-subtitle').textContent = subtitle || '';
    document.getElementById('sheet-body').innerHTML = bodyHtml;
    overlay.querySelector('.sheet').classList.toggle('wide', wide);
    overlay.hidden = false;
    document.getElementById('btn-sheet-close')?.focus();
};

window.closeSheet = function() {
    const overlay = document.getElementById('sheet-overlay');
    if (overlay && !overlay.hidden) overlay.hidden = true;
};

function setSheetBody(html) {
    const body = document.getElementById('sheet-body');
    if (body) body.innerHTML = html;
}

function sheetLoading(text) {
    return `<div class="sheet-loading"><div class="spinner"></div><span>${escapeHtml(text)}</span></div>`;
}

function fmtNumber(value, digits = 2) {
    if (value == null) return '-';
    if (typeof value !== 'number') return escapeHtml(value);
    return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

// ---------- Dataset preview & column profile ----------

window.previewRun = async function(batchId) {
    window.openSheet('Dataset preview', batchId, sheetLoading('Reading and profiling the dataset...'), true);
    let data;
    try {
        data = await fetchJson(`/api/v1/history/${encodeURIComponent(batchId)}/preview?rows=50`);
    } catch (e) {
        setSheetBody(`<p class="sheet-error"><i class="fa-solid fa-circle-exclamation"></i> ${escapeHtml(e.message)}</p>`);
        return;
    }
    document.getElementById('sheet-title').textContent = data.filename || 'Dataset preview';
    document.getElementById('sheet-subtitle').textContent =
        `${data.source === 'cleaned' ? 'Cleaned dataset' : 'Raw upload (not cleaned yet)'} · ${batchId}`;

    const nullColumns = data.columns.filter(c => c.null_pct > 0).length;
    const chips = `
        <div class="stat-chips">
            <div class="stat-chip"><span>Rows</span><strong>${fmtNumber(data.total_rows)}</strong></div>
            <div class="stat-chip"><span>Columns</span><strong>${data.columns.length}</strong></div>
            <div class="stat-chip"><span>Columns with nulls</span><strong class="${nullColumns ? 'text-orange' : 'text-green'}">${nullColumns}</strong></div>
            <div class="stat-chip"><span>Profiled</span><strong>${fmtNumber(data.profiled_rows)} rows</strong></div>
        </div>`;

    const profileRows = data.columns.map(c => {
        const detail = c.min != null
            ? `${fmtNumber(c.min)} &ndash; ${fmtNumber(c.max)} <span class="text-secondary">(mean ${fmtNumber(c.mean)})</span>`
            : c.top ? `<span class="text-secondary">most common</span> ${escapeHtml(String(c.top.value).slice(0, 40))} <span class="text-secondary">&times;${c.top.count}</span>` : '-';
        const tone = c.null_pct >= 20 ? 'bad' : c.null_pct > 0 ? 'warn' : 'good';
        return `
            <tr>
                <td><strong>${escapeHtml(c.name)}</strong></td>
                <td><code>${escapeHtml(c.dtype)}</code></td>
                <td>
                    <div class="null-meter ${tone}"><span style="width:${Math.max(c.null_pct, c.null_pct ? 3 : 0)}%"></span></div>
                    <span class="cell-sub">${c.null_pct}%</span>
                </td>
                <td>${fmtNumber(c.unique)}</td>
                <td>${detail}</td>
            </tr>`;
    }).join('');

    const cols = data.rows.length ? Object.keys(data.rows[0]) : [];
    const sampleTable = cols.length ? `
        <div class="table-scroll sheet-table">
            <table class="data-table compact">
                <thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
                <tbody>${data.rows.map(r => `<tr>${cols.map(c => `<td>${r[c] == null ? '<span class="null-cell">null</span>' : escapeHtml(r[c])}</td>`).join('')}</tr>`).join('')}</tbody>
            </table>
        </div>` : '<p class="text-secondary">The dataset has no rows.</p>';

    setSheetBody(`
        ${chips}
        <div class="segmented sheet-tabs" role="tablist">
            <button class="segmented-btn active" data-sheet-tab="profile" role="tab">Column profile</button>
            <button class="segmented-btn" data-sheet-tab="rows" role="tab">First ${data.rows.length} rows</button>
        </div>
        <div data-sheet-pane="profile">
            <div class="table-scroll sheet-table">
                <table class="data-table compact">
                    <thead><tr><th>Column</th><th>Type</th><th>Nulls</th><th>Distinct</th><th>Range / top value</th></tr></thead>
                    <tbody>${profileRows}</tbody>
                </table>
            </div>
        </div>
        <div data-sheet-pane="rows" hidden>${sampleTable}</div>`);
};

// ---------- Compare runs ----------

async function comparableRuns() {
    const history = await fetchJson('/api/v1/history');
    viewState.history = history;
    return history.filter(r => r.status !== 'Not Run' && r.status !== 'Running');
}

window.openCompareRuns = async function(preselected = []) {
    window.openSheet('Compare runs', 'Pick two runs to see their metrics and columns side by side', sheetLoading('Loading your runs...'), true);
    let runs;
    try {
        runs = await comparableRuns();
    } catch (e) {
        setSheetBody(`<p class="sheet-error">${escapeHtml(e.message)}</p>`);
        return;
    }
    if (runs.length < 2) {
        setSheetBody('<div class="sheet-empty"><i class="fa-solid fa-code-compare"></i><p>You need at least two finished runs to compare.</p></div>');
        return;
    }
    const [a, b] = preselected.length === 2 ? preselected : [runs[1].batch_id, runs[0].batch_id];
    const options = (selected) => runs.map(r =>
        `<option value="${escapeHtml(r.batch_id)}" ${r.batch_id === selected ? 'selected' : ''}>${escapeHtml(r.filename || r.batch_id)} · ${fmtDateTime(r.started_at || r.uploaded_at)}</option>`
    ).join('');
    setSheetBody(`
        <div class="compare-pickers">
            <label><span class="compare-tag a">A</span><select class="page-select" id="compare-a">${options(a)}</select></label>
            <button class="btn-icon" id="btn-compare-swap" title="Swap A and B"><i class="fa-solid fa-right-left"></i></button>
            <label><span class="compare-tag b">B</span><select class="page-select" id="compare-b">${options(b)}</select></label>
        </div>
        <div id="compare-result"></div>`);
    const run = () => renderComparison(document.getElementById('compare-a').value, document.getElementById('compare-b').value);
    document.getElementById('compare-a').addEventListener('change', run);
    document.getElementById('compare-b').addEventListener('change', run);
    document.getElementById('btn-compare-swap').addEventListener('click', () => {
        const selA = document.getElementById('compare-a');
        const selB = document.getElementById('compare-b');
        [selA.value, selB.value] = [selB.value, selA.value];
        run();
    });
    run();
};

async function renderComparison(a, b) {
    const target = document.getElementById('compare-result');
    if (!target) return;
    if (a === b) {
        target.innerHTML = '<p class="text-secondary sheet-note">Pick two different runs.</p>';
        return;
    }
    target.innerHTML = sheetLoading('Comparing...');
    let data;
    try {
        data = await fetchJson(`/api/v1/history/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
    } catch (e) {
        target.innerHTML = `<p class="sheet-error">${escapeHtml(e.message)}</p>`;
        return;
    }
    const rows = data.metrics.map(m => {
        const delta = m.delta == null || m.delta === 0 ? '<span class="text-secondary">&ndash;</span>'
            : `<span class="delta ${m.better === 'b' ? 'up' : m.better === 'a' ? 'down' : ''}">${m.delta > 0 ? '+' : ''}${fmtNumber(m.delta)}</span>`;
        return `
            <tr>
                <td>${escapeHtml(m.label)}</td>
                <td class="${m.better === 'a' ? 'is-better' : ''}">${fmtNumber(m.a)}</td>
                <td class="${m.better === 'b' ? 'is-better' : ''}">${fmtNumber(m.b)}</td>
                <td>${delta}</td>
            </tr>`;
    }).join('');
    const chips = (cols, cls) => cols.length
        ? cols.map(c => `<span class="col-chip ${cls}">${escapeHtml(c)}</span>`).join('')
        : '<span class="text-secondary">none</span>';
    target.innerHTML = `
        <table class="data-table compact compare-table">
            <thead><tr><th>Metric</th><th><span class="compare-tag a">A</span> ${statusBadge(data.a.status)}</th><th><span class="compare-tag b">B</span> ${statusBadge(data.b.status)}</th><th>B &minus; A</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>
        <div class="compare-schema">
            <h4>Columns</h4>
            <div><span class="schema-label">Only in A</span>${chips(data.schema.only_in_a, 'a')}</div>
            <div><span class="schema-label">Only in B</span>${chips(data.schema.only_in_b, 'b')}</div>
            <div><span class="schema-label">Shared</span><span class="text-secondary">${data.schema.shared.length} column(s)</span></div>
        </div>`;
}

// ---------- Export & delete ----------

window.exportHistory = function() {
    const link = document.createElement('a');
    link.href = withAuthToken('/api/v1/history/export');
    link.download = 'pipeline_run_history.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    showToast('success', 'Run history exported as CSV.');
};

window.deleteRun = async function(batchId) {
    const run = (viewState.history || []).find(r => r.batch_id === batchId);
    const name = run?.filename || batchId;
    if (!confirmAction(`Delete the run of "${name}" (${batchId})?\n\nIts logs, reports and staging rows are removed. This cannot be undone.`)) return;
    try {
        const res = await fetchJson(`/api/v1/history/${encodeURIComponent(batchId)}`, { method: 'DELETE' });
        showToast('success', `Deleted ${name} (${res.files_removed} file${res.files_removed === 1 ? '' : 's'} removed).`);
    } catch (e) {
        showToast('error', e.message);
        return;
    }
    viewState.historySelected?.delete(batchId);
    loadDashboardStats();
    if (document.getElementById('history-view')?.classList.contains('active')) window.loadHistoryView();
    else viewState.history = (viewState.history || []).filter(r => r.batch_id !== batchId);
};

// ---------- System status ----------

function fmtUptime(seconds) {
    const d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600), m = Math.floor(seconds % 3600 / 60);
    return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

window.loadSystemStatus = async function(manual = false) {
    const target = document.getElementById('dash-system-status');
    const btn = document.getElementById('btn-system-check');
    if (!target || insightState.systemLoading) return;
    insightState.systemLoading = true;
    btn?.classList.add('is-loading');
    try {
        const s = await fetchJson('/api/v1/dashboard/system');
        const engine = s.llm.active_engine;
        const engineLabel = engine === 'gemini' ? `Gemini${s.llm.models[0] ? ` · ${s.llm.models[0]}` : ''}`
            : engine === 'ollama' ? 'Ollama (local)' : 'Offline engine';
        const items = [
            { icon: 'fa-database', label: 'Database', tone: s.database.connected ? 'ok' : 'bad',
              value: s.database.connected ? `${s.database.dialect} · ${s.database.latency_ms} ms` : 'Unreachable' },
            { icon: 'fa-robot', label: 'AI engine', tone: engine === 'offline' ? 'warn' : 'ok', value: engineLabel,
              title: engine === 'offline' ? 'No LLM configured or reachable: reports and chat use the built-in rule engine.' : '' },
            { icon: 'fa-server', label: 'API', tone: 'ok', value: `v${s.version} · up ${fmtUptime(s.uptime_seconds)}` },
            { icon: 'fa-folder-open', label: 'Workspace', tone: 'ok', value: `${s.workspace.files} files · ${fmtBytes(s.workspace.bytes)}` }
        ];
        target.innerHTML = items.map(i => `
            <div class="system-row" title="${escapeHtml(i.title || '')}">
                <span class="system-dot ${i.tone}"></span>
                <i class="fa-solid ${i.icon}"></i>
                <span class="system-label">${i.label}</span>
                <span class="system-value">${escapeHtml(i.value)}</span>
            </div>`).join('') +
            `<div class="system-checked">Checked ${new Date().toLocaleTimeString()}</div>`;
        if (manual) showToast(s.database.connected ? 'success' : 'error', s.database.connected ? 'All systems reachable.' : 'The database is not reachable.');
    } catch (e) {
        target.innerHTML = `<p class="sheet-error">${escapeHtml(e.message)}</p>`;
    } finally {
        insightState.systemLoading = false;
        btn?.classList.remove('is-loading');
    }
};

// ---------- Chart range: last runs or daily trend ----------

window.renderDashboardChart = async function() {
    const title = document.getElementById('dash-chart-title');
    const foot = document.getElementById('dash-chart-foot');
    if (insightState.chartRange === 'recent') {
        if (title) title.textContent = 'Execution Duration Trend';
        renderCharts(state.recentRuns || []);
        const runs = state.recentRuns || [];
        const failed = runs.filter(r => r.status === 'Failed').length;
        if (foot) foot.innerHTML = runs.length ? `Last ${runs.length} runs${failed ? ` · <span class="text-red">${failed} failed</span>` : ' · none failed'}` : '';
        return;
    }
    const days = insightState.chartRange;
    if (title) title.textContent = `Daily Activity · ${days} days`;
    let data;
    try {
        data = await fetchJson(`/api/v1/dashboard/trends?days=${days}`);
    } catch (e) {
        if (foot) foot.innerHTML = `<span class="text-red">${escapeHtml(e.message)}</span>`;
        return;
    }
    if (insightState.chartRange !== days) return; // the range changed while loading
    renderTrendChart(data);
    const t = data.totals;
    if (foot) {
        foot.innerHTML = t.runs
            ? `${t.runs} runs · <span class="text-green">${t.succeeded} succeeded</span> · <span class="${t.failed ? 'text-red' : ''}">${t.failed} failed</span>` +
              (t.busiest_day ? ` · busiest ${new Date(t.busiest_day + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}` : '')
            : 'No runs in this period.';
    }
};

function renderTrendChart(data) {
    const canvas = document.getElementById('executionHistoryChart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (state.historyChart) state.historyChart.destroy();
    const css = getComputedStyle(document.documentElement);
    const green = css.getPropertyValue('--color-green').trim() || '#16a34a';
    const red = css.getPropertyValue('--color-red').trim() || '#dc2626';
    const accent = css.getPropertyValue('--color-blue').trim() || '#4f46e5';
    const tickFont = { family: 'Plus Jakarta Sans', size: 10 };
    const labels = data.series.map(d => new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' }));

    state.historyChart = new Chart(canvas.getContext('2d'), {
        data: {
            labels,
            datasets: [
                { type: 'bar', label: 'Succeeded', data: data.series.map(d => d.succeeded), backgroundColor: `${green}cc`, borderRadius: 4, stack: 'runs', maxBarThickness: 18, yAxisID: 'y' },
                { type: 'bar', label: 'Failed', data: data.series.map(d => d.failed), backgroundColor: `${red}cc`, borderRadius: 4, stack: 'runs', maxBarThickness: 18, yAxisID: 'y' },
                { type: 'line', label: 'Avg quality %', data: data.series.map(d => d.avg_quality), borderColor: accent, backgroundColor: accent,
                  borderWidth: 2, tension: 0.35, pointRadius: 2.5, spanGaps: true, yAxisID: 'q' }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, font: tickFont, color: '#565b66' } },
                tooltip: { backgroundColor: '#12141a', padding: 10, cornerRadius: 8, titleFont: { ...tickFont, size: 11, weight: '700' }, bodyFont: { ...tickFont, size: 11 } }
            },
            scales: {
                x: { stacked: true, grid: { display: false }, ticks: { color: '#8a8f9a', font: tickFont, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
                y: { stacked: true, beginAtZero: true, border: { display: false }, grid: { color: 'rgba(15, 23, 42, 0.06)' },
                     ticks: { color: '#8a8f9a', font: tickFont, precision: 0 }, title: { display: true, text: 'Runs', color: '#8a8f9a', font: tickFont } },
                q: { position: 'right', min: 0, max: 100, border: { display: false }, grid: { display: false },
                     ticks: { color: '#8a8f9a', font: tickFont, callback: (v) => `${v}%` } }
            }
        }
    });
}

window.refreshDashboard = function() {
    loadDashboardStats();
    window.loadSystemStatus();
};

// ---------- wiring ----------

document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('sheet-overlay');
    overlay?.addEventListener('mousedown', (e) => { if (e.target === overlay) window.closeSheet(); });
    document.getElementById('btn-sheet-close')?.addEventListener('click', () => window.closeSheet());

    // Tabs inside the dialog (preview: profile / rows)
    document.getElementById('sheet-body')?.addEventListener('click', (e) => {
        const tab = e.target.closest('[data-sheet-tab]');
        if (!tab) return;
        const name = tab.getAttribute('data-sheet-tab');
        tab.parentElement.querySelectorAll('[data-sheet-tab]').forEach(t => t.classList.toggle('active', t === tab));
        document.querySelectorAll('#sheet-body [data-sheet-pane]').forEach(p => { p.hidden = p.getAttribute('data-sheet-pane') !== name; });
    });

    document.querySelectorAll('[data-chart-range]').forEach(btn => {
        btn.addEventListener('click', () => {
            insightState.chartRange = btn.getAttribute('data-chart-range');
            document.querySelectorAll('[data-chart-range]').forEach(b => {
                b.classList.toggle('active', b === btn);
                b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
            });
            window.renderDashboardChart();
        });
    });

    document.getElementById('btn-system-check')?.addEventListener('click', () => window.loadSystemStatus(true));
});
