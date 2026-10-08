// Fix data for Human Review: the reviewer sees the uploaded file, jumps to the rows each problem
// refers to and applies the fixes the Review Agent recommends, then processes the fixed file.
// Every fix is recorded and written to the next process log; the original file can be restored.

const editorState = {
    batchId: null,
    item: null,
    data: null,
    filter: null,
    offset: 0,
    limit: 100,
    busy: false
};

window.openDataEditor = async function(batchId) {
    Object.assign(editorState, { batchId, item: null, data: null, filter: null, offset: 0 });
    window.closeSheet && window.closeSheet();
    window.activateView('review-editor-view');
    document.getElementById('nav-review')?.classList.add('active');
    document.getElementById('editor-filename').textContent = 'Loading...';
    document.getElementById('editor-grid').innerHTML = '';
    try {
        editorState.item = await fetchJson(`/api/v1/review/${encodeURIComponent(batchId)}`);
    } catch (e) {
        showToast('error', e.message);
        return;
    }
    renderEditorIssues();
    await loadEditorData();
};

async function loadEditorData() {
    const { batchId, filter, offset, limit } = editorState;
    const params = new URLSearchParams({ offset, limit });
    if (filter) params.set('filter', JSON.stringify(filter));
    try {
        editorState.data = await fetchJson(`/api/v1/review/${encodeURIComponent(batchId)}/data?${params}`);
    } catch (e) {
        document.getElementById('editor-grid').innerHTML = `<tbody><tr><td class="sheet-error">${escapeHtml(e.message)}</td></tr></tbody>`;
        document.getElementById('editor-filename').textContent = editorState.item?.filename || batchId;
        return;
    }
    const d = editorState.data;
    document.getElementById('editor-filename').textContent = d.filename;
    document.getElementById('editor-meta').textContent = `${d.total.toLocaleString()} rows · ${d.columns.length} columns · ${d.format.toUpperCase()}`;
    document.getElementById('btn-editor-revert').hidden = !d.has_original;
    renderEditorFilter();
    renderEditorGrid();
    renderEditorEdits(d.edits);
}

// ---------- problems and suggested fixes ----------

function renderEditorIssues() {
    const box = document.getElementById('editor-issues');
    // Problems with a recommended fix, plus the crucial ones the AI cannot fix in the file
    const issues = (editorState.item?.issues || [])
        .map((issue, n) => ({ issue, n }))
        .filter(({ issue }) => (issue.fixes || []).length || issue.severity === 'critical' || issue.severity === 'high');
    if (!issues.length) {
        box.innerHTML = '<p class="text-secondary sheet-note">The AI has no fixes to recommend for this file. You can process it as it is.</p>';
        return;
    }
    box.innerHTML = issues.map(({ issue, n }) => `
        <div class="editor-issue sev-${escapeHtml(issue.severity)}">
            <div class="editor-issue-head">
                <span class="sev-tag ${escapeHtml(issue.severity)}">${REVIEW_SEVERITY_LABELS[issue.severity] || escapeHtml(issue.severity)}</span>
                <strong>${escapeHtml(issue.title)}</strong>
            </div>
            <p class="editor-issue-text">${escapeHtml(issue.action)}</p>
            <div class="editor-fixes">
                ${issue.rows ? `<button class="btn-refresh editor-show-rows" data-issue="${n}"><i class="fa-solid fa-filter"></i> Show these rows</button>` : ''}
                ${(issue.fixes || []).map((fix, f) => fix.needs ? `
                    <div class="editor-fix-input">
                        <input type="text" class="page-input" data-fix-value="${n}:${f}" placeholder="${fix.needs === 'replace' ? 'Replace with' : 'Value'}">
                        <button class="btn-refresh" data-fix="${n}:${f}" title="${escapeHtml(fix.label)}"><i class="fa-solid fa-wand-magic-sparkles"></i> ${escapeHtml(fix.label.replace('...', ''))}</button>
                    </div>` : `
                    <button class="btn-refresh editor-fix" data-fix="${n}:${f}"><i class="fa-solid fa-wand-magic-sparkles"></i> ${escapeHtml(fix.label)}</button>`).join('')}
            </div>
        </div>`).join('');
}

function issueFixOp(key) {
    const [n, f] = key.split(':').map(Number);
    const fix = editorState.item.issues[n].fixes[f];
    const op = JSON.parse(JSON.stringify(fix.op));
    if (fix.needs) {
        const input = document.querySelector(`[data-fix-value="${key}"]`);
        const value = (input?.value || '').trim();
        if (!value) {
            input?.focus();
            showToast('info', 'Type the value first.');
            return null;
        }
        op[fix.needs] = value;
    }
    return op;
}

// ---------- filter and grid ----------

function renderEditorFilter() {
    const d = editorState.data;
    const el = document.getElementById('editor-filter');
    el.innerHTML = editorState.filter
        ? `<span class="editor-filter-chip"><i class="fa-solid fa-filter"></i> Showing <strong>${d.matched.toLocaleString()}</strong> row(s) ${escapeHtml(d.filter_label)}</span>
           <button class="link-btn" id="btn-editor-clear-filter">Show all rows</button>`
        : `<span class="text-secondary">All ${d.total.toLocaleString()} rows. Empty cells are highlighted.</span>`;
    document.getElementById('btn-editor-clear-filter')?.addEventListener('click', () => setEditorFilter(null));
}

function normalizeName(name) {
    return String(name).trim().toLowerCase().replace(/[ .-]/g, '_');
}

function renderEditorGrid() {
    const d = editorState.data;
    const stats = Object.fromEntries(d.column_stats.map(s => [s.name, s]));
    const flaggedCol = editorState.filter?.column
        ? d.columns.find(c => normalizeName(c) === normalizeName(editorState.filter.column)) : null;
    const head = `<thead><tr>
        <th class="editor-rownum">#</th>
        ${d.columns.map(c => {
            const s = stats[c] || {};
            const badges = (s.missing ? `<span class="editor-col-badge" title="${s.missing} empty cell(s)">${s.missing} empty</span>` : '')
                + (s.non_numeric ? `<span class="editor-col-badge warn" title="${s.non_numeric} value(s) are not numbers">${s.non_numeric} text</span>` : '');
            return `<th class="${c === flaggedCol ? 'is-flagged' : ''}"><span class="editor-col-name">${escapeHtml(c)}</span>${badges}</th>`;
        }).join('')}
    </tr></thead>`;
    const body = d.rows.length ? d.rows.map(r => `
        <tr>
            <td class="editor-rownum">${r.row + 1}</td>
            ${r.values.map((v, i) => {
                const cls = [v.trim() === '' ? 'is-empty' : '', d.columns[i] === flaggedCol ? 'is-flagged' : ''].join(' ');
                return `<td class="${cls}"><span class="editor-cell">${escapeHtml(v)}</span></td>`;
            }).join('')}
        </tr>`).join('')
        : `<tr><td colspan="${d.columns.length + 1}" class="text-center text-secondary">${editorState.filter ? 'No rows match any more. The problem is fixed.' : 'The file has no rows.'}</td></tr>`;
    document.getElementById('editor-grid').innerHTML = head + `<tbody>${body}</tbody>`;
    // Bring the column the problem is about into view
    const wrap = document.getElementById('editor-grid-wrap');
    const flaggedTh = wrap.querySelector('th.is-flagged');
    wrap.scrollLeft = flaggedTh ? Math.max(0, flaggedTh.offsetLeft - 160) : 0;

    const from = d.matched ? d.offset + 1 : 0;
    const to = Math.min(d.offset + d.limit, d.matched);
    document.getElementById('editor-pager').innerHTML = `
        <span class="text-secondary">Rows ${from.toLocaleString()}-${to.toLocaleString()} of ${d.matched.toLocaleString()}${editorState.filter ? ` matching (file has ${d.total.toLocaleString()})` : ''}</span>
        <div class="editor-pager-btns">
            <button class="btn-refresh" data-page="-1" ${d.offset === 0 ? 'disabled' : ''}><i class="fa-solid fa-chevron-left"></i> Previous</button>
            <button class="btn-refresh" data-page="1" ${to >= d.matched ? 'disabled' : ''}>Next <i class="fa-solid fa-chevron-right"></i></button>
        </div>`;
}

function renderEditorEdits(edits) {
    const box = document.getElementById('editor-edits');
    box.innerHTML = edits && edits.length ? [...edits].reverse().map(e => `
        <div class="editor-edit">
            <span class="text-secondary">${fmtDateTime(e.at)}${e.by ? ` · ${escapeHtml(e.by)}` : ''}</span>
            <ul>${(e.changes || []).map(c => `<li>${escapeHtml(c)}</li>`).join('')}</ul>
        </div>`).join('') : '<p class="text-secondary sheet-note">No fixes yet. The file is as it was uploaded.</p>';
}

// ---------- applying fixes ----------

async function applyFix(op) {
    if (editorState.busy) return;
    editorState.busy = true;
    try {
        const res = await fetchJson(`/api/v1/review/${encodeURIComponent(editorState.batchId)}/data`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version: editorState.data.version, ops: [op] })
        });
        showToast('success', res.changes.join('. ') + '.');
        if (editorState.offset >= res.total) editorState.offset = 0;
        await loadEditorData();
    } catch (e) {
        showToast('error', e.message);
    } finally {
        editorState.busy = false;
    }
}

function setEditorFilter(filter) {
    editorState.filter = filter;
    editorState.offset = 0;
    loadEditorData();
}

// ---------- wiring ----------

document.addEventListener('DOMContentLoaded', () => {
    const view = document.getElementById('review-editor-view');
    if (!view) return;

    document.getElementById('btn-editor-back').addEventListener('click', () => window.activateView('review-view'));
    document.getElementById('btn-editor-process').addEventListener('click', () => window.processReviewItem(editorState.batchId));
    document.getElementById('btn-editor-revert').addEventListener('click', async () => {
        if (!confirmAction('Undo every fix and restore the file as it was uploaded?')) return;
        try {
            await fetchJson(`/api/v1/review/${encodeURIComponent(editorState.batchId)}/data/revert`, { method: 'POST' });
            showToast('success', 'The original file is back.');
            loadEditorData();
        } catch (e) {
            showToast('error', e.message);
        }
    });

    document.getElementById('editor-issues').addEventListener('click', (e) => {
        const show = e.target.closest('.editor-show-rows');
        if (show) {
            setEditorFilter(editorState.item.issues[Number(show.dataset.issue)].rows);
            return;
        }
        const fixBtn = e.target.closest('[data-fix]');
        if (fixBtn) {
            const op = issueFixOp(fixBtn.dataset.fix);
            if (op) applyFix(op);
        }
    });

    document.getElementById('editor-pager').addEventListener('click', (e) => {
        const btn = e.target.closest('[data-page]');
        if (!btn) return;
        editorState.offset = Math.max(0, editorState.offset + Number(btn.dataset.page) * editorState.limit);
        loadEditorData();
    });
});
