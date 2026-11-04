// Data Quality page (dataset health: anomalies and freshness; data contracts), the contract editor,
// the Contracts / Lineage panes of Run details, and REST API ingestion.

const qualityState = {
    datasets: [],
    contracts: [],
    ruleTypes: null,
    editor: null // { id, name, dataset_pattern, enabled, rules: [...] } while the editor is open
};

const HEALTH = {
    failing: { label: 'Failing', icon: 'fa-circle-xmark', cls: 'failed' },
    anomaly: { label: 'Anomaly', icon: 'fa-wave-square', cls: 'warning' },
    late: { label: 'Late', icon: 'fa-hourglass-end', cls: 'warning' },
    contract: { label: 'Contract issues', icon: 'fa-file-circle-exclamation', cls: 'warning' },
    learning: { label: 'Learning', icon: 'fa-graduation-cap', cls: 'running' },
    healthy: { label: 'Healthy', icon: 'fa-circle-check', cls: 'success' }
};

const RULE_PARAM_HINTS = {
    between: 'min..max  (e.g. 0..1000, 0.., ..99)',
    allowed_values: 'value, value, value',
    regex: 'regular expression',
    type: 'numeric | integer | date | text',
    max_null_pct: 'percent, e.g. 5',
    row_count_min: 'rows, e.g. 100',
    row_count_max: 'rows, e.g. 100000'
};
const DATASET_LEVEL = ['column_exists', 'max_null_pct', 'row_count_min', 'row_count_max'];

function fmtDuration(seconds) {
    if (seconds == null) return '-';
    const s = Math.abs(seconds);
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
    if (s < 172800) return `${Math.round(s / 3600)} h`;
    return `${Math.round(s / 86400)} d`;
}

function healthBadge(health) {
    const h = HEALTH[health] || HEALTH.healthy;
    return `<span class="badge ${h.cls}"><i class="fa-solid ${h.icon}"></i> ${h.label}</span>`;
}

// Inline sparkline of one metric across a dataset's runs; anomalous runs are marked
function sparkline(series, key, anomalyKey = 'anomalies') {
    const pts = series.map((s, i) => ({ i, v: s[key], bad: s[anomalyKey] > 0 || s.status === 'Failed' })).filter(p => p.v != null);
    if (pts.length < 2) return '<span class="text-secondary">-</span>';
    const w = 120, h = 28, pad = 3;
    const vals = pts.map(p => p.v);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const x = i => pad + (i / Math.max(1, series.length - 1)) * (w - 2 * pad);
    const y = v => h - pad - ((v - lo) / span) * (h - 2 * pad);
    const path = pts.map((p, n) => `${n ? 'L' : 'M'}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
    const last = pts[pts.length - 1];
    const marks = pts.filter(p => p.bad).map(p => `<circle cx="${x(p.i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="2.6" class="spark-bad"/>`).join('');
    return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${escapeHtml(key)} trend">
        <path d="${path}" class="spark-line"/>${marks}
        <circle cx="${x(last.i).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="2.6" class="spark-last"/>
    </svg>`;
}

// ---------- Page ----------

window.loadQualityView = async function() {
    const list = document.getElementById('quality-datasets');
    const contracts = document.getElementById('contracts-list');
    if (!list) return;
    const [health, contractList] = await Promise.allSettled([
        fetchJson('/api/v1/observability/datasets'),
        fetchJson('/api/v1/contracts')
    ]);
    if (contractList.status === 'fulfilled') {
        qualityState.contracts = contractList.value;
        renderContracts();
    } else if (contracts) {
        contracts.innerHTML = `<p class="sheet-error">${escapeHtml(contractList.reason.message)}</p>`;
    }
    if (health.status === 'fulfilled') {
        qualityState.datasets = health.value.datasets;
        renderQualityCounters(health.value.counts || {});
        renderDatasets();
    } else {
        list.innerHTML = `<p class="sheet-error">${escapeHtml(health.reason.message)}</p>`;
    }
};

function renderQualityCounters(counts) {
    const el = document.getElementById('quality-counters');
    if (!el) return;
    const total = qualityState.datasets.length;
    const attention = (counts.failing || 0) + (counts.anomaly || 0) + (counts.late || 0) + (counts.contract || 0);
    const navCount = document.getElementById('nav-quality-count');
    if (navCount) {
        navCount.hidden = !attention;
        navCount.textContent = attention;
        navCount.classList.toggle('critical', !!counts.failing);
    }
    el.innerHTML = `
        <div class="stat-chips">
            <div class="stat-chip"><span>Datasets</span><strong>${total}</strong></div>
            <div class="stat-chip"><span>Healthy</span><strong class="text-green">${counts.healthy || 0}</strong></div>
            <div class="stat-chip"><span>Anomalies</span><strong class="${counts.anomaly ? 'text-orange' : ''}">${counts.anomaly || 0}</strong></div>
            <div class="stat-chip"><span>Late</span><strong class="${counts.late ? 'text-orange' : ''}">${counts.late || 0}</strong></div>
            <div class="stat-chip"><span>Failing</span><strong class="${counts.failing ? 'text-red' : ''}">${counts.failing || 0}</strong></div>
            <div class="stat-chip"><span>Contracts</span><strong>${qualityState.contracts.length}</strong></div>
        </div>`;
}

function renderDatasets() {
    const list = document.getElementById('quality-datasets');
    if (!qualityState.datasets.length) {
        list.innerHTML = `<div class="sheet-empty"><i class="fa-solid fa-heart-pulse"></i>
            <p>No runs yet. Every dataset you run appears here; after 3 deliveries its row count, missing values, rejections, quality and runtime get a learned normal range.</p></div>`;
        return;
    }
    list.innerHTML = `
        <div class="table-scroll">
        <table class="data-table compact quality-table">
            <thead><tr><th>Dataset</th><th>Health</th><th>Rows</th><th>Quality</th><th>Freshness</th><th>Latest finding</th><th></th></tr></thead>
            <tbody>${qualityState.datasets.map(d => {
                const f = d.freshness || {};
                const fresh = f.last_at
                    ? `<span title="Last delivery ${fmtDateTime(f.last_at)}">${fmtDuration(f.silent_for_s)} ago</span>`
                      + (f.expected_every_s ? `<span class="text-secondary detail-small">usually every ${fmtDuration(f.expected_every_s)}</span>` : '')
                    : '-';
                const finding = d.latest_anomalies.length
                    ? `<span class="${d.latest_anomalies[0].severity === 'high' ? 'text-red' : 'text-orange'}">${escapeHtml(d.latest_anomalies[0].message)}</span>`
                      + (d.latest_anomalies.length > 1 ? ` <span class="text-secondary">+${d.latest_anomalies.length - 1} more</span>` : '')
                    : d.health === 'late' ? `<span class="text-orange">No delivery for ${fmtDuration(f.silent_for_s)}; usually every ${fmtDuration(f.expected_every_s)}.</span>`
                    : d.health === 'learning' ? `<span class="text-secondary">Learning the baseline (${d.runs} of 4 runs).</span>`
                    : d.health === 'failing' ? '<span class="text-red">The last run failed.</span>'
                    : d.health === 'contract' ? '<span class="text-orange">The last run broke contract rules.</span>'
                    : '<span class="text-secondary">Everything within the usual range.</span>';
                return `<tr>
                    <td><strong>${escapeHtml(d.dataset)}</strong><span class="text-secondary detail-small">${d.runs} run${d.runs === 1 ? '' : 's'} · last ${escapeHtml(d.latest_filename)}</span></td>
                    <td>${healthBadge(d.health)}</td>
                    <td>${sparkline(d.series, 'rows')}</td>
                    <td>${sparkline(d.series, 'quality_after')}</td>
                    <td class="cell-stack">${fresh}</td>
                    <td class="quality-finding">${finding}</td>
                    <td class="text-right"><button class="btn-icon" title="Open the last run" onclick="openRunDetails('${escapeHtml(d.last_batch_id)}')"><i class="fa-solid fa-arrow-up-right-from-square"></i></button></td>
                </tr>`;
            }).join('')}</tbody>
        </table>
        </div>`;
}

function renderContracts() {
    const list = document.getElementById('contracts-list');
    if (!list) return;
    if (!qualityState.contracts.length) {
        list.innerHTML = `<div class="sheet-empty"><i class="fa-solid fa-file-signature"></i>
            <p>No contracts yet. Create one from a good run: the rules are profiled from its data and you choose what should warn, drop rows or stop the run.</p></div>`;
        return;
    }
    list.innerHTML = qualityState.contracts.map(c => {
        const counts = { warn: 0, drop: 0, fail: 0 };
        c.rules.forEach(r => { counts[r.action] = (counts[r.action] || 0) + 1; });
        return `
        <div class="schedule-row contract-row ${c.enabled ? '' : 'is-paused'}">
            <div class="schedule-main">
                <div class="schedule-title">
                    <span class="schedule-dot ${c.enabled ? 'on' : 'off'}"></span>
                    <strong>${escapeHtml(c.name)}</strong>
                    <span class="schedule-chip"><i class="fa-solid fa-file"></i> ${escapeHtml(c.dataset_pattern)}</span>
                    ${c.enabled ? '' : '<span class="schedule-chip muted">Disabled</span>'}
                </div>
                <div class="contract-rule-preview">${c.rules.slice(0, 4).map(r => `<span class="rule-pill action-${r.action}">${escapeHtml(r.summary)}</span>`).join('')}
                    ${c.rules.length > 4 ? `<span class="text-secondary">+${c.rules.length - 4} more</span>` : ''}</div>
            </div>
            <div class="schedule-meta">
                <div><span class="meta-label">Rules</span>${c.rules.length}</div>
                <div><span class="meta-label">Actions</span><span class="text-secondary">${counts.warn} warn · ${counts.drop} drop · ${counts.fail} fail</span></div>
            </div>
            <div class="schedule-actions">
                <button class="btn-icon" onclick="openContractEditor(${c.id})" title="Edit rules"><i class="fa-solid fa-pen"></i></button>
                <button class="btn-icon" onclick="contractAction(${c.id}, '${c.enabled ? 'disable' : 'enable'}')" title="${c.enabled ? 'Disable' : 'Enable'}"><i class="fa-solid ${c.enabled ? 'fa-pause' : 'fa-play'}"></i></button>
                <button class="btn-icon danger" onclick="contractAction(${c.id}, 'delete')" title="Delete contract"><i class="fa-solid fa-trash-can"></i></button>
            </div>
        </div>`;
    }).join('');
}

window.contractAction = async function(id, action) {
    const contract = qualityState.contracts.find(c => c.id === id);
    if (!contract) return;
    try {
        if (action === 'delete') {
            if (!confirmAction(`Delete the contract "${contract.name}"?\n\nRuns it already checked keep their results.`)) return;
            await fetchJson(`/api/v1/contracts/${id}`, { method: 'DELETE' });
            showToast('success', `Contract "${contract.name}" deleted.`);
        } else {
            await fetchJson(`/api/v1/contracts/${id}`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: action === 'enable' })
            });
            showToast('success', `"${contract.name}" ${action === 'enable' ? 'enabled' : 'disabled'}.`);
        }
    } catch (e) {
        showToast('error', e.message);
    }
    window.loadQualityView();
};

// ---------- Contract editor ----------

function paramText(rule) {
    const p = rule.params || {};
    switch (rule.type) {
        case 'between': return `${p.min ?? ''}..${p.max ?? ''}`;
        case 'allowed_values': return (p.values || []).join(', ');
        case 'regex': return p.pattern || '';
        case 'type': return p.kind || '';
        case 'max_null_pct': return p.max ?? '';
        case 'row_count_min': case 'row_count_max': return p.value ?? '';
        default: return '';
    }
}

function parseParams(type, text) {
    const t = String(text ?? '').trim();
    switch (type) {
        case 'between': {
            const [lo, hi] = t.includes('..') ? t.split('..') : [t, ''];
            return { min: lo.trim() === '' ? null : Number(lo), max: (hi || '').trim() === '' ? null : Number(hi) };
        }
        case 'allowed_values': return { values: t.split(',').map(v => v.trim()).filter(Boolean) };
        case 'regex': return { pattern: t };
        case 'type': return { kind: t.toLowerCase() };
        case 'max_null_pct': return { max: t === '' ? null : Number(t) };
        case 'row_count_min': case 'row_count_max': return { value: t === '' ? null : Number(t) };
        default: return {};
    }
}

async function ensureRuleTypes() {
    if (!qualityState.ruleTypes) qualityState.ruleTypes = await fetchJson('/api/v1/contracts/rule-types');
    return qualityState.ruleTypes;
}

window.openContractEditor = async function(id = null) {
    window.openSheet(id ? 'Edit contract' : 'New data contract', 'Rules are checked on the cleaned data before it is loaded', sheetLoading('Loading...'), true);
    try {
        await ensureRuleTypes();
    } catch (e) {
        setSheetBody(`<p class="sheet-error">${escapeHtml(e.message)}</p>`);
        return;
    }
    const existing = id ? qualityState.contracts.find(c => c.id === id) : null;
    qualityState.editor = existing
        ? { id, name: existing.name, dataset_pattern: existing.dataset_pattern, enabled: existing.enabled, rules: existing.rules.map(r => ({ ...r })) }
        : { id: null, name: '', dataset_pattern: '', enabled: true, rules: [] };
    let runs = [];
    try {
        runs = (await fetchJson('/api/v1/history?limit=50')).filter(r => r.clean_file && r.status !== 'Running');
    } catch (e) { /* the editor still works without suggestions */ }
    const runOptions = runs.map(r => `<option value="${escapeHtml(r.batch_id)}">${escapeHtml(r.filename)} · ${fmtDateTime(r.uploaded_at)}</option>`).join('');
    setSheetBody(`
        <div class="contract-editor">
            <div class="contract-head-grid">
                <label class="api-field"><span>Name</span><input id="ce-name" class="page-input" maxlength="120" placeholder="Orders contract" value="${escapeHtml(qualityState.editor.name)}"></label>
                <label class="api-field"><span>Applies to files named</span><input id="ce-pattern" class="page-input" maxlength="255" placeholder="orders_*.csv" value="${escapeHtml(qualityState.editor.dataset_pattern)}" spellcheck="false"></label>
            </div>
            <div class="contract-suggest">
                <i class="fa-solid fa-wand-magic-sparkles"></i>
                <span>Profile a good run to propose rules:</span>
                <select id="ce-suggest-run" class="page-select" ${runs.length ? '' : 'disabled'}>${runOptions || '<option>No finished runs yet</option>'}</select>
                <button class="btn-refresh-table" id="ce-suggest-btn" ${runs.length ? '' : 'disabled'}><i class="fa-solid fa-wand-magic-sparkles"></i> Suggest rules</button>
                ${id && runs.length ? `<button class="btn-refresh-table" id="ce-test-btn" title="Check the saved contract against the selected run without changing anything"><i class="fa-solid fa-flask"></i> Test on run</button>` : ''}
            </div>
            <div id="ce-test-result"></div>
            <div class="table-scroll sheet-table">
                <table class="data-table compact contract-rules">
                    <thead><tr><th>Rule</th><th>Column</th><th>Setting</th><th>When broken</th><th></th></tr></thead>
                    <tbody id="ce-rules"></tbody>
                </table>
            </div>
            <div class="detail-actions">
                <button class="btn-refresh-table" id="ce-add-rule"><i class="fa-solid fa-plus"></i> Add rule</button>
                <span class="text-secondary detail-small">Patterns use * and ?; column names match the cleaned (snake_case) headers.</span>
                <span class="flex-spacer"></span>
                <button class="btn-primary-glow btn-compact" id="ce-save"><i class="fa-solid fa-floppy-disk"></i> Save contract</button>
            </div>
        </div>`);
    renderRuleRows();
    document.getElementById('ce-add-rule').addEventListener('click', () => {
        syncEditorFromForm();
        qualityState.editor.rules.push({ type: 'not_null', column: '', params: {}, action: 'warn' });
        renderRuleRows();
    });
    document.getElementById('ce-suggest-btn')?.addEventListener('click', suggestRules);
    document.getElementById('ce-test-btn')?.addEventListener('click', testContract);
    document.getElementById('ce-save').addEventListener('click', saveContract);
};

function renderRuleRows() {
    const tbody = document.getElementById('ce-rules');
    if (!tbody) return;
    const types = qualityState.ruleTypes.types;
    const rules = qualityState.editor.rules;
    if (!rules.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-secondary">No rules yet. Suggest them from a run or add one.</td></tr>';
        return;
    }
    tbody.innerHTML = rules.map((r, i) => {
        const noParam = !RULE_PARAM_HINTS[r.type];
        const noColumn = r.type === 'row_count_min' || r.type === 'row_count_max';
        const datasetLevel = DATASET_LEVEL.includes(r.type);
        return `<tr data-rule="${i}">
            <td><select class="page-select ce-type">${types.map(t => `<option value="${t.type}" ${t.type === r.type ? 'selected' : ''}>${escapeHtml(t.label)}</option>`).join('')}</select></td>
            <td><input class="page-input ce-column" value="${escapeHtml(r.column || '')}" ${noColumn ? 'disabled placeholder="whole file"' : 'placeholder="column"'} spellcheck="false"></td>
            <td><input class="page-input ce-param" value="${escapeHtml(paramText(r))}" ${noParam ? 'disabled placeholder="-"' : `placeholder="${escapeHtml(RULE_PARAM_HINTS[r.type])}"`} spellcheck="false"></td>
            <td><select class="page-select ce-action action-${r.action}">
                <option value="warn" ${r.action === 'warn' ? 'selected' : ''}>Warn</option>
                ${datasetLevel ? '' : `<option value="drop" ${r.action === 'drop' ? 'selected' : ''}>Drop rows</option>`}
                <option value="fail" ${r.action === 'fail' ? 'selected' : ''}>Fail run</option>
            </select></td>
            <td><button class="btn-icon danger ce-remove" title="Remove rule"><i class="fa-solid fa-xmark"></i></button></td>
        </tr>`;
    }).join('');
    tbody.querySelectorAll('tr[data-rule]').forEach(tr => {
        const i = Number(tr.dataset.rule);
        tr.querySelector('.ce-type').addEventListener('change', (e) => {
            syncEditorFromForm();
            const rule = qualityState.editor.rules[i];
            rule.type = e.target.value;
            rule.params = {};
            if (DATASET_LEVEL.includes(rule.type) && rule.action === 'drop') rule.action = 'warn';
            renderRuleRows();
        });
        tr.querySelector('.ce-action').addEventListener('change', (e) => { e.target.className = `page-select ce-action action-${e.target.value}`; });
        tr.querySelector('.ce-remove').addEventListener('click', () => {
            syncEditorFromForm();
            qualityState.editor.rules.splice(i, 1);
            renderRuleRows();
        });
    });
}

function syncEditorFromForm() {
    const ed = qualityState.editor;
    if (!ed) return;
    ed.name = document.getElementById('ce-name')?.value.trim() ?? ed.name;
    ed.dataset_pattern = document.getElementById('ce-pattern')?.value.trim() ?? ed.dataset_pattern;
    document.querySelectorAll('#ce-rules tr[data-rule]').forEach(tr => {
        const rule = ed.rules[Number(tr.dataset.rule)];
        rule.type = tr.querySelector('.ce-type').value;
        rule.column = tr.querySelector('.ce-column').value.trim() || null;
        rule.params = parseParams(rule.type, tr.querySelector('.ce-param').value);
        rule.action = tr.querySelector('.ce-action').value;
    });
}

async function suggestRules() {
    const batchId = document.getElementById('ce-suggest-run').value;
    const btn = document.getElementById('ce-suggest-btn');
    btn.disabled = true;
    try {
        const s = await fetchJson(`/api/v1/contracts/suggest?batch_id=${encodeURIComponent(batchId)}`);
        syncEditorFromForm();
        const ed = qualityState.editor;
        if (!ed.name) document.getElementById('ce-name').value = ed.name = s.name;
        if (!ed.dataset_pattern) document.getElementById('ce-pattern').value = ed.dataset_pattern = s.pattern_hint;
        const have = new Set(ed.rules.map(r => `${r.type}|${r.column}`));
        const added = s.rules.filter(r => !have.has(`${r.type}|${r.column}`));
        ed.rules.push(...added);
        renderRuleRows();
        showToast('success', `${plural(added.length, 'rule')} proposed from ${s.rows_profiled.toLocaleString()} rows. Review the actions, then save.`);
    } catch (e) {
        showToast('error', e.message);
    } finally {
        btn.disabled = false;
    }
}

async function testContract() {
    const ed = qualityState.editor;
    const batchId = document.getElementById('ce-suggest-run').value;
    const box = document.getElementById('ce-test-result');
    box.innerHTML = sheetLoading('Checking the saved contract...');
    try {
        const res = await fetchJson(`/api/v1/contracts/${ed.id}/test?batch_id=${encodeURIComponent(batchId)}`, { method: 'POST' });
        box.innerHTML = contractResultsHtml({ summary: res.summary, results: res.results }, true);
    } catch (e) {
        box.innerHTML = `<p class="sheet-error">${escapeHtml(e.message)}</p>`;
    }
}

async function saveContract() {
    syncEditorFromForm();
    const ed = qualityState.editor;
    const body = {
        name: ed.name, dataset_pattern: ed.dataset_pattern,
        rules: ed.rules.map(({ type, column, params, action, description }) => ({ type, column, params, action, description }))
    };
    if (!body.name || !body.dataset_pattern) {
        showToast('error', 'Give the contract a name and the file names it applies to.');
        return;
    }
    const btn = document.getElementById('ce-save');
    btn.disabled = true;
    try {
        await fetchJson(ed.id ? `/api/v1/contracts/${ed.id}` : '/api/v1/contracts', {
            method: ed.id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        showToast('success', `Contract "${body.name}" saved. The next run of ${body.dataset_pattern} is checked against it.`);
        window.closeSheet();
        window.loadQualityView();
    } catch (e) {
        showToast('error', e.message);
        btn.disabled = false;
    }
}

// ---------- Run details panes ----------

function contractResultsHtml(contracts, compact = false) {
    if (!contracts || !contracts.results || !contracts.results.length) {
        return `<div class="sheet-empty"><i class="fa-solid fa-file-signature"></i>
            <p>No data contract applies to this file. Create one on the Data Quality page.</p></div>`;
    }
    const s = contracts.summary || {};
    const names = (contracts.applied || []).map(a => escapeHtml(a.name)).join(', ');
    const order = { failed: 0, dropped: 1, warned: 2, passed: 3 };
    const rows = [...contracts.results].sort((a, b) => order[a.status] - order[b.status]);
    return `
        ${compact ? '' : `<p class="text-secondary detail-small">Checked against ${names || 'the contract'} before loading.</p>`}
        <div class="stat-chips">
            <div class="stat-chip"><span>Passed</span><strong class="text-green">${s.passed ?? 0}</strong></div>
            <div class="stat-chip"><span>Warned</span><strong class="${s.warned ? 'text-orange' : ''}">${s.warned ?? 0}</strong></div>
            <div class="stat-chip"><span>Dropped rows</span><strong class="${s.rows_dropped ? 'text-orange' : ''}">${fmtNumber(s.rows_dropped ?? 0)}</strong></div>
            <div class="stat-chip"><span>Failed</span><strong class="${s.failed ? 'text-red' : ''}">${s.failed ?? 0}</strong></div>
        </div>
        <div class="table-scroll sheet-table">
            <table class="data-table compact wrap">
                <thead><tr><th>Result</th><th>Rule</th><th>Rows</th><th>Examples</th></tr></thead>
                <tbody>${rows.map(r => `
                    <tr>
                        <td><span class="rule-status status-${r.status}">${escapeHtml(r.status)}</span></td>
                        <td>${escapeHtml(r.rule)}<span class="text-secondary detail-small">${escapeHtml(r.action)}${r.contract ? ' · ' + escapeHtml(r.contract) : ''}</span></td>
                        <td>${r.failed_rows ? `${fmtNumber(r.failed_rows)} <span class="text-secondary">(${r.failed_pct}%)</span>` : escapeHtml(r.detail || '-')}</td>
                        <td class="text-secondary">${(r.samples || []).map(v => escapeHtml(v ?? 'empty')).join(', ') || '-'}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
        </div>`;
}

function anomaliesHtml(obs) {
    if (!obs) return '';
    if (obs.learning) {
        return `<section class="detail-watch"><h4><i class="fa-solid fa-wave-square"></i> Observability</h4>
            <p class="text-secondary detail-small">Learning what is normal for ${escapeHtml(obs.dataset_key)}: ${obs.baseline_runs} earlier run${obs.baseline_runs === 1 ? '' : 's'}, anomalies are judged from 3.</p></section>`;
    }
    if (!(obs.anomalies || []).length) {
        return `<section class="detail-watch"><h4><i class="fa-solid fa-wave-square"></i> Observability</h4>
            <p class="text-secondary detail-small"><i class="fa-solid fa-circle-check text-green"></i> Every metric is within its usual range (compared with ${obs.baseline_runs} earlier runs of ${escapeHtml(obs.dataset_key)}).</p></section>`;
    }
    return `<section class="detail-watch">
        <h4><i class="fa-solid fa-wave-square"></i> Anomalies against ${obs.baseline_runs} earlier runs</h4>
        <ul class="watch-list">${obs.anomalies.map(a => `
            <li class="watch-item sev-${escapeHtml(a.severity)}">
                <i class="fa-solid ${a.direction === 'up' ? 'fa-arrow-trend-up' : 'fa-arrow-trend-down'}" title="${escapeHtml(a.label)}"></i>
                <div><strong>${escapeHtml(a.label)} ${escapeHtml(a.change)}</strong><span class="text-secondary">${escapeHtml(a.message)}</span></div>
                <span class="sev-tag ${a.severity === 'high' ? 'high' : ''}">${escapeHtml(a.severity)}</span>
            </li>`).join('')}
        </ul></section>`;
}

window.loadLineagePane = async function(batchId, el) {
    if (!el || el.dataset.loaded) return;
    el.dataset.loaded = '1';
    el.innerHTML = sheetLoading('Tracing columns...');
    try {
        const lin = await fetchJson(`/api/v1/lineage/${encodeURIComponent(batchId)}`);
        const icons = { file: 'fa-file-lines', table: 'fa-table', export: 'fa-chart-column' };
        const flow = lin.datasets.map(d => `<div class="lineage-node kind-${d.kind}"><i class="fa-solid ${icons[d.kind] || 'fa-circle'}"></i><span>${escapeHtml(d.label)}</span></div>`)
            .join('<i class="fa-solid fa-arrow-right lineage-arrow"></i>');
        const steps = lin.dataset_steps.length
            ? `<p class="text-secondary detail-small"><i class="fa-solid fa-filter"></i> Row-level steps: ${lin.dataset_steps.map(s => escapeHtml(s.description)).join('; ')}</p>` : '';
        const rows = lin.columns.map(c => `
            <tr class="${c.dropped ? 'is-dropped' : ''}">
                <td><code>${escapeHtml(c.source)}</code></td>
                <td>${c.dropped ? '<span class="text-red">dropped</span>' : `<code>${escapeHtml(c.target)}</code>`}</td>
                <td>${c.transformations.length ? c.transformations.map(t => `<span class="rule-pill" title="${escapeHtml(t.description)}">${escapeHtml(t.label)}</span>`).join('') : '<span class="text-secondary">unchanged</span>'}</td>
                <td>${c.loaded_to ? `<code>${escapeHtml(c.loaded_to)}</code>` : '<span class="text-secondary">not loaded</span>'}</td>
            </tr>`).join('');
        el.innerHTML = `
            <div class="lineage-flow">${flow}</div>
            <div class="stat-chips">
                <div class="stat-chip"><span>Source columns</span><strong>${lin.stats.source_columns}</strong></div>
                <div class="stat-chip"><span>Renamed</span><strong>${lin.stats.renamed}</strong></div>
                <div class="stat-chip"><span>Values changed</span><strong>${lin.stats.changed}</strong></div>
                <div class="stat-chip"><span>Dropped</span><strong>${lin.stats.dropped}</strong></div>
                <div class="stat-chip"><span>Loaded to warehouse</span><strong>${lin.stats.loaded}</strong></div>
            </div>
            ${steps}
            ${lin.columns.length ? `<div class="table-scroll sheet-table">
                <table class="data-table compact wrap">
                    <thead><tr><th>Source column</th><th>Cleaned column</th><th>Transformations</th><th>Warehouse</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>` : '<p class="text-secondary sheet-note">The run did not record its columns.</p>'}
            <div class="detail-actions">
                <button class="btn-refresh-table" onclick="downloadOpenLineage('${escapeHtml(batchId)}')"><i class="fa-solid fa-download"></i> OpenLineage events (JSON)</button>
                <span class="text-secondary detail-small">Import into Marquez, DataHub or any OpenLineage consumer, or set OPENLINEAGE_URL to send them automatically.</span>
            </div>`;
    } catch (e) {
        el.innerHTML = `<p class="sheet-error">${escapeHtml(e.message)}</p>`;
    }
};

window.downloadOpenLineage = async function(batchId) {
    try {
        const events = await fetchJson(`/api/v1/lineage/${encodeURIComponent(batchId)}/openlineage`);
        const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `${batchId}_openlineage.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (e) {
        showToast('error', e.message);
    }
};

// ---------- REST API ingestion ----------

window.apiSourceRequest = function() {
    const url = (document.getElementById('api-url-input')?.value || '').trim();
    const type = document.getElementById('api-pagination')?.value || 'auto';
    const pageSize = parseInt(document.getElementById('api-page-size')?.value, 10);
    const auth = (document.getElementById('api-auth')?.value || '').trim();
    const pagination = { type };
    if (pageSize > 0) {
        pagination.page_size = pageSize;
        pagination.size_param = type === 'offset' ? 'limit' : 'per_page';
    }
    return {
        url,
        records_path: (document.getElementById('api-records-path')?.value || '').trim() || null,
        pagination,
        max_pages: parseInt(document.getElementById('api-max-pages')?.value, 10) || 20,
        headers: auth ? { Authorization: auth } : null
    };
};

async function previewApiSource() {
    const req = window.apiSourceRequest();
    const box = document.getElementById('api-preview-result');
    if (!req.url) {
        showToast('error', 'Enter the API endpoint URL.');
        return;
    }
    box.hidden = false;
    box.innerHTML = '<span class="text-secondary"><i class="fa-solid fa-spinner fa-spin"></i> Calling the API...</span>';
    try {
        const p = await fetchJson('/api/v1/upload/api/preview', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req)
        });
        box.innerHTML = `<i class="fa-solid fa-circle-check text-green"></i>
            <strong>${fmtNumber(p.records)} records</strong> on ${p.pages} page${p.pages === 1 ? '' : 's'} (preview)
            · records at <code>${escapeHtml(p.records_path || '(root)')}</code> · pagination: ${escapeHtml(p.pagination)}
            <div class="api-columns">${p.columns.slice(0, 16).map(c => `<code>${escapeHtml(c)}</code>`).join(' ')}${p.columns.length > 16 ? ` +${p.columns.length - 16}` : ''}</div>`;
        if (!document.getElementById('api-records-path').value && p.records_path) {
            document.getElementById('api-records-path').placeholder = `auto: ${p.records_path}`;
        }
    } catch (e) {
        box.innerHTML = `<span class="text-red"><i class="fa-solid fa-circle-exclamation"></i> ${escapeHtml(e.message)}</span>`;
    }
}

// ---------- wiring ----------

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-refresh-quality')?.addEventListener('click', () => window.loadQualityView());
    document.getElementById('btn-new-contract')?.addEventListener('click', () => window.openContractEditor());
    document.getElementById('btn-api-preview')?.addEventListener('click', previewApiSource);
    // Keep the sidebar count current without opening the page
    setTimeout(() => {
        if (document.getElementById('nav-quality-count') && typeof getAuthToken === 'function' && getAuthToken()) {
            fetchJson('/api/v1/observability/datasets').then(h => {
                qualityState.datasets = h.datasets;
                renderQualityCounters(h.counts || {});
            }).catch(() => {});
        }
    }, 1500);
});
