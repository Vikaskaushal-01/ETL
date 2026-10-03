// Data editor for Human Review: the reviewer sees the uploaded file, jumps to the rows each problem
// refers to, applies the Review Agent's suggested fixes or edits cells by hand, then saves and re-runs
// the pipeline on the corrected file. Every change is recorded and written to the next process log.

const editorState = {
    batchId: null,
    item: null,
    data: null,
    filter: null,
    offset: 0,
    limit: 100,
    pending: new Map(), // "row|column" -> new value
    selected: new Set(), // row numbers ticked for deletion
    busy: false
};

function editorDirty() {
    return editorState.pending.size > 0 || editorState.selected.size > 0;
}

window.openDataEditor = async function(batchId) {
    if (editorState.batchId && editorState.batchId !== batchId && editorDirty()
        && !confirmAction('You have unsaved changes in another file. Discard them?')) return;
    Object.assign(editorState, { batchId, item: null, data: null, filter: null, offset: 0 });
    editorState.pending.clear();
    editorState.selected.clear();
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
    renderEditorTools();
    renderEditorGrid();
    renderEditorEdits(d.edits);
    syncEditorButtons();
}

// ---------- problems and suggested fixes ----------

function renderEditorIssues() {
    const box = document.getElementById('editor-issues');
    const issues = editorState.item?.issues || [];
    if (!issues.length) {
        box.innerHTML = '<p class="text-secondary sheet-note">No open problems. You can still edit the file.</p>';
        return;
    }
    box.innerHTML = issues.map((issue, n) => `
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

// ---------- filter, column tools and grid ----------

function renderEditorFilter() {
    const d = editorState.data;
    const el = document.getElementById('editor-filter');
    el.innerHTML = editorState.filter
        ? `<span class="editor-filter-chip"><i class="fa-solid fa-filter"></i> Showing <strong>${d.matched.toLocaleString()}</strong> row(s) ${escapeHtml(d.filter_label)}</span>
           <button class="link-btn" id="btn-editor-clear-filter">Show all rows</button>`
        : `<span class="text-secondary">All ${d.total.toLocaleString()} rows. Empty cells are highlighted; click a cell to edit it.</span>`;
    document.getElementById('btn-editor-clear-filter')?.addEventListener('click', () => setEditorFilter(null));
}

const TOOL_INPUTS = {
    fill_value: ['value'], replace: ['find', 'value'], rename: ['value'],
    fill_group_median: ['group'], fill_group_mode: ['group']
};

function renderEditorTools() {
    const cols = editorState.data.columns;
    const colSelect = document.getElementById('editor-tool-column');
    const groupSelect = document.getElementById('editor-tool-group');
    const keep = colSelect.value;
    const flagged = editorState.filter?.column;
    const options = cols.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    colSelect.innerHTML = options;
    groupSelect.innerHTML = `<option value="">Group by...</option>${options}`;
    const preferred = cols.find(c => c === keep) || cols.find(c => normalizeName(c) === normalizeName(flagged || ''));
    if (preferred) colSelect.value = preferred;
    if (editorState.filter?.group_column) {
        const g = cols.find(c => normalizeName(c) === normalizeName(editorState.filter.group_column));
        if (g) groupSelect.value = g;
    }
    syncToolInputs();
}

function syncToolInputs() {
    const action = document.getElementById('editor-tool-action').value;
    const inputs = TOOL_INPUTS[action] || [];
    const value = document.getElementById('editor-tool-value');
    document.getElementById('editor-tool-find').hidden = !inputs.includes('find');
    value.hidden = !inputs.includes('value');
    value.placeholder = action === 'rename' ? 'New column name' : action === 'replace' ? 'Replace with' : 'Value';
    document.getElementById('editor-tool-group').hidden = !inputs.includes('group');
    document.getElementById('editor-tool-column').disabled = action === 'drop_duplicates';
}

function normalizeName(name) {
    return String(name).trim().toLowerCase().replace(/[ .-]/g, '_');
}

function toolOp() {
    const column = document.getElementById('editor-tool-column').value;
    const action = document.getElementById('editor-tool-action').value;
    const value = document.getElementById('editor-tool-value').value.trim();
    const find = document.getElementById('editor-tool-find').value;
    const group = document.getElementById('editor-tool-group').value;
    const need = (ok, message) => { if (!ok) { showToast('info', message); throw new Error('incomplete'); } };
    switch (action) {
        case 'fill_value': need(value, 'Type the value to fill the empty cells with.'); return { op: 'fill_missing', column, strategy: 'value', value };
        case 'fill_median': return { op: 'fill_missing', column, strategy: 'median' };
        case 'fill_mean': return { op: 'fill_missing', column, strategy: 'mean' };
        case 'fill_mode': return { op: 'fill_missing', column, strategy: 'mode' };
        case 'fill_group_median':
        case 'fill_group_mode':
            need(group && group !== column, 'Pick the column to group by.');
            return { op: 'fill_missing', column, strategy: action === 'fill_group_median' ? 'group_median' : 'group_mode', group_by: group };
        case 'replace': need(find.trim(), 'Type the value to find.'); return { op: 'replace_values', column, find, replace: value };
        case 'clear_non_numeric': return { op: 'clear_matching', column, filter: { kind: 'non_numeric', column } };
        case 'dates_dayfirst': return { op: 'standardize_dates', column, dayfirst: true };
        case 'dates_monthfirst': return { op: 'standardize_dates', column, dayfirst: false };
        case 'delete_empty': return { op: 'delete_matching', filter: { kind: 'missing', column } };
        case 'rename': need(value, 'Type the new column name.'); return { op: 'rename_column', column, new_name: value };
        case 'drop_column': return { op: 'drop_column', column };
        case 'drop_duplicates': return { op: 'drop_duplicates' };
    }
    return null;
}

function renderEditorGrid() {
    const d = editorState.data;
    const stats = Object.fromEntries(d.column_stats.map(s => [s.name, s]));
    const flaggedCol = editorState.filter?.column
        ? d.columns.find(c => normalizeName(c) === normalizeName(editorState.filter.column)) : null;
    const head = `<thead><tr>
        <th class="editor-check"><input type="checkbox" class="row-check" id="editor-select-page" aria-label="Select the rows on this page"></th>
        <th class="editor-rownum">#</th>
        ${d.columns.map(c => {
            const s = stats[c] || {};
            const badges = (s.missing ? `<span class="editor-col-badge" title="${s.missing} empty cell(s)">${s.missing} empty</span>` : '')
                + (s.non_numeric ? `<span class="editor-col-badge warn" title="${s.non_numeric} value(s) are not numbers">${s.non_numeric} text</span>` : '');
            return `<th class="${c === flaggedCol ? 'is-flagged' : ''}"><span class="editor-col-name">${escapeHtml(c)}</span>${badges}</th>`;
        }).join('')}
    </tr></thead>`;
    const body = d.rows.length ? d.rows.map(r => `
        <tr class="${editorState.selected.has(r.row) ? 'row-selected' : ''}">
            <td class="editor-check"><input type="checkbox" class="row-check" data-select-row="${r.row}" ${editorState.selected.has(r.row) ? 'checked' : ''} aria-label="Select row ${r.row + 1}"></td>
            <td class="editor-rownum">${r.row + 1}</td>
            ${r.values.map((v, i) => {
                const key = `${r.row}|${d.columns[i]}`;
                const changed = editorState.pending.has(key);
                const value = changed ? editorState.pending.get(key) : v;
                const cls = [changed ? 'is-changed' : '', value.trim() === '' ? 'is-empty' : '', d.columns[i] === flaggedCol ? 'is-flagged' : ''].join(' ');
                return `<td class="${cls}"><input class="editor-cell" data-key="${escapeHtml(key)}" data-original="${escapeHtml(v)}" value="${escapeHtml(value)}" aria-label="${escapeHtml(d.columns[i])}, row ${r.row + 1}"></td>`;
            }).join('')}
        </tr>`).join('')
        : `<tr><td colspan="${d.columns.length + 2}" class="text-center text-secondary">${editorState.filter ? 'No rows match any more. The problem may already be fixed.' : 'The file has no rows.'}</td></tr>`;
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
        </div>`).join('') : '<p class="text-secondary sheet-note">No changes yet. The file is as it was uploaded.</p>';
}

function syncEditorButtons() {
    const edits = editorState.pending.size, rows = editorState.selected.size;
    const pending = document.getElementById('editor-pending');
    pending.hidden = !edits && !rows;
    pending.textContent = [edits ? `${edits} unsaved cell edit(s)` : '', rows ? `${rows} row(s) to delete` : ''].filter(Boolean).join(' · ');
    document.getElementById('btn-editor-save').disabled = editorState.busy || (!edits && !rows);
    const del = document.getElementById('btn-editor-delete-rows');
    del.disabled = !rows;
    del.innerHTML = `<i class="fa-solid fa-trash-can"></i> Delete selected rows${rows ? ` (${rows})` : ''}`;
}

// ---------- saving ----------

function pendingOps() {
    const ops = [];
    if (editorState.pending.size) {
        ops.push({ op: 'set_cells', changes: [...editorState.pending].map(([key, value]) => {
            const cut = key.indexOf('|');
            return { row: Number(key.slice(0, cut)), column: key.slice(cut + 1), value };
        }) });
    }
    if (editorState.selected.size) ops.push({ op: 'delete_rows', rows: [...editorState.selected] });
    return ops;
}

// Sends unsaved cell edits and row deletions first, then the given change, as one edit
async function submitEdits(extraOps = []) {
    const ops = [...pendingOps(), ...extraOps];
    if (!ops.length || editorState.busy) return false;
    editorState.busy = true;
    syncEditorButtons();
    try {
        const res = await fetchJson(`/api/v1/review/${encodeURIComponent(editorState.batchId)}/data`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version: editorState.data.version, ops })
        });
        editorState.pending.clear();
        editorState.selected.clear();
        showToast('success', res.changes.join('. ') + '.');
        if (editorState.offset >= res.total) editorState.offset = 0;
        await loadEditorData();
        return true;
    } catch (e) {
        showToast('error', e.message);
        return false;
    } finally {
        editorState.busy = false;
        syncEditorButtons();
    }
}

function setEditorFilter(filter) {
    if (editorDirty()) {
        showToast('info', 'Save or discard your unsaved edits first.');
        return;
    }
    editorState.filter = filter;
    editorState.offset = 0;
    loadEditorData();
}

async function saveAndRerun() {
    if (editorDirty() && !(await submitEdits())) return;
    const item = editorState.item;
    if (!item?.raw_file) return;
    enqueueJob({ kind: 'rerun', rawFile: item.raw_file, batchId: item.batch_id, label: item.filename, focusOnStart: true });
    showToast('info', `Running ${item.filename} again with your changes. The Review Agent checks it when the run finishes.`);
    window.activateView('pipeline-monitor-page');
}

// ---------- wiring ----------

document.addEventListener('DOMContentLoaded', () => {
    const view = document.getElementById('review-editor-view');
    if (!view) return;

    document.getElementById('btn-editor-back').addEventListener('click', () => {
        if (editorDirty() && !confirmAction('Discard your unsaved changes?')) return;
        editorState.pending.clear();
        editorState.selected.clear();
        window.activateView('review-view');
    });
    document.getElementById('btn-editor-save').addEventListener('click', () => submitEdits());
    document.getElementById('btn-editor-rerun').addEventListener('click', saveAndRerun);
    document.getElementById('btn-editor-delete-rows').addEventListener('click', () => {
        const n = editorState.selected.size;
        if (n && confirmAction(`Delete ${n} row(s) from the file? You can restore the original file later.`)) submitEdits();
    });
    document.getElementById('btn-editor-revert').addEventListener('click', async () => {
        if (!confirmAction('Undo every edit and restore the file as it was uploaded?')) return;
        try {
            await fetchJson(`/api/v1/review/${encodeURIComponent(editorState.batchId)}/data/revert`, { method: 'POST' });
            editorState.pending.clear();
            editorState.selected.clear();
            showToast('success', 'The original file is back.');
            loadEditorData();
        } catch (e) {
            showToast('error', e.message);
        }
    });

    document.getElementById('editor-tool-action').addEventListener('change', syncToolInputs);
    document.getElementById('editor-tools').addEventListener('submit', async (e) => {
        e.preventDefault();
        let op;
        try { op = toolOp(); } catch (err) { return; }
        if (op && (op.op === 'drop_column' || op.op === 'delete_matching')
            && !confirmAction(op.op === 'drop_column' ? `Remove column '${op.column}' from the file?` : `Delete every row where '${op.filter.column}' is empty?`)) return;
        if (op && await submitEdits([op])) {
            document.getElementById('editor-tool-value').value = '';
            document.getElementById('editor-tool-find').value = '';
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
            if (op) submitEdits([op]);
        }
    });

    const grid = document.getElementById('editor-grid');
    grid.addEventListener('input', (e) => {
        const cell = e.target.closest('.editor-cell');
        if (!cell) return;
        const key = cell.dataset.key;
        if (cell.value === cell.dataset.original) editorState.pending.delete(key);
        else editorState.pending.set(key, cell.value);
        const td = cell.parentElement;
        td.classList.toggle('is-changed', editorState.pending.has(key));
        td.classList.toggle('is-empty', cell.value.trim() === '');
        syncEditorButtons();
    });
    grid.addEventListener('change', (e) => {
        const box = e.target.closest('[data-select-row]');
        if (box) {
            const row = Number(box.dataset.selectRow);
            if (box.checked) editorState.selected.add(row); else editorState.selected.delete(row);
            box.closest('tr').classList.toggle('row-selected', box.checked);
        } else if (e.target.id === 'editor-select-page') {
            grid.querySelectorAll('[data-select-row]').forEach(b => {
                b.checked = e.target.checked;
                const row = Number(b.dataset.selectRow);
                if (b.checked) editorState.selected.add(row); else editorState.selected.delete(row);
                b.closest('tr').classList.toggle('row-selected', b.checked);
            });
        }
        syncEditorButtons();
    });
    // Enter moves to the cell below, like a spreadsheet
    grid.addEventListener('keydown', (e) => {
        const cell = e.target.closest('.editor-cell');
        if (!cell || e.key !== 'Enter') return;
        e.preventDefault();
        const td = cell.parentElement;
        const below = td.parentElement.nextElementSibling?.children[td.cellIndex]?.querySelector('.editor-cell');
        below?.focus();
    });
    document.getElementById('editor-pager').addEventListener('click', (e) => {
        const btn = e.target.closest('[data-page]');
        if (!btn) return;
        if (editorDirty()) {
            showToast('info', 'Save your edits on this page before moving to another one.');
            return;
        }
        editorState.offset = Math.max(0, editorState.offset + Number(btn.dataset.page) * editorState.limit);
        loadEditorData();
    });
    window.addEventListener('beforeunload', (e) => {
        if (editorDirty()) { e.preventDefault(); e.returnValue = ''; }
    });
});
