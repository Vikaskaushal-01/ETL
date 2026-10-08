// Human Review: runs the Review Agent handed to a person, either because the file was not processed
// or because the automatic cleaning made choices (filled values, dropped rows) that change the data.
// Every problem shows what happened, why it matters and what to do; reviewers resolve or dismiss it.

const reviewState = {
    status: 'open',
    items: [],
    counts: null,
    highlight: null // batch id to scroll to after loading
};

const REVIEW_CATEGORY_ICONS = {
    'Pipeline failure': 'fa-bug',
    'File': 'fa-file-circle-xmark',
    'Validation': 'fa-ban',
    'Missing values': 'fa-droplet-slash',
    'Bias risk': 'fa-scale-unbalanced',
    'Data types': 'fa-font',
    'Outliers': 'fa-arrow-trend-up',
    'Duplicates': 'fa-clone'
};
const REVIEW_SEVERITY_LABELS = { critical: 'Critical', high: 'High', medium: 'Medium' };

function reviewKindPill(item) {
    if (item.status === 'resolved') return '<span class="review-pill resolved"><i class="fa-solid fa-circle-check"></i> Resolved</span>';
    if (item.status === 'dismissed') return '<span class="review-pill dismissed"><i class="fa-solid fa-eye-slash"></i> Dismissed</span>';
    return item.kind === 'not_processed'
        ? '<span class="review-pill critical"><i class="fa-solid fa-circle-xmark"></i> Not processed</span>'
        : '<span class="review-pill high"><i class="fa-solid fa-user-pen"></i> Needs decision</span>';
}

// The problems that made the file crucial, or every problem when none is critical or high
function crucialIssues(item) {
    const crucial = item.issues.filter(i => i.severity === 'critical' || i.severity === 'high');
    return crucial.length ? crucial : item.issues;
}

function reviewCardHtml(item) {
    const id = escapeHtml(item.batch_id);
    const running = item.run_status === 'Running';
    const issues = crucialIssues(item);
    const fixable = item.issues.filter(i => (i.fixes || []).length).length;
    return `
        <article class="review-card kind-${escapeHtml(item.kind)} ${reviewState.highlight === item.batch_id ? 'is-highlighted' : ''}" data-review-card="${id}">
            <header class="review-card-head">
                <div class="review-card-title">
                    <div class="review-card-name">
                        ${reviewKindPill(item)}
                        <strong class="run-name">${escapeHtml(item.filename || item.batch_id)}</strong>
                    </div>
                    <div class="review-card-meta text-secondary">
                        <span>${issues.length} crucial problem(s)${fixable ? ` &middot; ${fixable} with AI fixes` : ''}</span>
                        <span>Flagged ${fmtDateTime(item.flagged_at)}</span>
                        ${item.edits.length ? `<span><i class="fa-solid fa-pen-to-square"></i> Fixed ${item.edits.length} time(s)</span>` : ''}
                    </div>
                </div>
                <div class="review-card-actions">
                    ${running ? '<span class="review-pill high"><i class="fa-solid fa-spinner fa-spin"></i> Processing</span>' : `
                        ${item.editable ? `<button class="btn-refresh review-fix-btn" onclick="openDataEditor('${id}')" title="Apply the fixes the AI recommends"><i class="fa-solid fa-wand-magic-sparkles"></i> Fix data</button>` : ''}
                        ${item.raw_file ? `<button class="btn-primary-glow review-process-btn" onclick="processReviewItem('${id}')" title="Run the pipeline on this file and close its review"><i class="fa-solid fa-play"></i> Process file</button>` : ''}`}
                </div>
            </header>
            <ul class="review-crucial">${issues.map(i => `<li><span class="sev-tag ${escapeHtml(i.severity)}">${REVIEW_SEVERITY_LABELS[i.severity] || escapeHtml(i.severity)}</span> ${escapeHtml(i.title)}</li>`).join('')}</ul>
        </article>`;
}

function renderReviewKpis() {
    const el = document.getElementById('review-kpis');
    const c = reviewState.counts;
    if (!el || !c) return;
    const cards = [
        ['Waiting for review', c.open, 'fa-user-shield', c.open ? 'orange' : 'green', 'Files with open problems'],
        ['Not processed', c.not_processed, 'fa-circle-xmark', c.not_processed ? 'red' : '', 'Failed, empty or nothing loaded'],
        ['Needs a decision', c.needs_decision, 'fa-user-pen', c.needs_decision ? 'orange' : '', 'Processed, but changes need sign-off'],
        ['Open problems', c.issues, 'fa-list-check', '', `${c.by_severity.critical} critical files, ${c.by_severity.high} high`],
        ['Resolved', c.resolved + c.dismissed, 'fa-circle-check', 'green', `${c.dismissed} accepted as they are`]
    ];
    el.innerHTML = cards.map(([label, value, icon, color, sub]) => `
        <div class="kpi-card">
            <div class="kpi-card-head"><span>${label}</span><div class="kpi-card-icon ${color}"><i class="fa-solid ${icon}"></i></div></div>
            <div class="kpi-card-value">${value}</div>
            <div class="kpi-card-sub">${sub}</div>
        </div>`).join('');
}

function renderReviewList() {
    const list = document.getElementById('review-list');
    if (!list) return;
    if (!reviewState.items.length) {
        list.innerHTML = '<div class="dash-panel sheet-empty"><i class="fa-solid fa-circle-check"></i><p>No crucial files right now. Every processed file is fine as it is.</p></div>';
        return;
    }
    list.innerHTML = reviewState.items.map(reviewCardHtml).join('');
    if (reviewState.highlight) {
        list.querySelector(`[data-review-card="${CSS.escape(reviewState.highlight)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        reviewState.highlight = null;
    }
}

function updateReviewBadges(counts) {
    for (const id of ['nav-review-count', 'dash-review-count']) {
        const el = document.getElementById(id);
        if (!el) continue;
        el.hidden = !counts.open;
        el.textContent = counts.open > 99 ? '99+' : counts.open;
        el.classList.toggle('critical', counts.not_processed > 0);
        el.title = `${counts.open} file(s) waiting for review`;
    }
}

window.loadReviewView = async function() {
    const list = document.getElementById('review-list');
    try {
        const data = await fetchJson(`/api/v1/review?status=${reviewState.status}`);
        reviewState.items = data.items;
        reviewState.counts = data.counts;
        updateReviewBadges(data.counts);
        renderReviewKpis();
        renderReviewList();
    } catch (e) {
        if (list) list.innerHTML = `<p class="text-red">Failed to load the review queue: ${escapeHtml(e.message)}</p>`;
    }
};

// Dashboard panel: the most urgent open items, plus the sidebar badge
window.loadDashboardReview = async function() {
    if (!getAuthToken()) return;
    let data;
    try {
        data = await fetchJson('/api/v1/review?status=open');
    } catch (e) {
        return;
    }
    updateReviewBadges(data.counts);
    const list = document.getElementById('dash-review-list');
    if (!list) return;
    if (!data.items.length) {
        list.innerHTML = '<div class="review-mini-empty"><i class="fa-solid fa-circle-check"></i> All clear: no file needs a human decision.</div>';
        return;
    }
    const rank = { critical: 0, high: 1, medium: 2 };
    const top = [...data.items].sort((a, b) => (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9)).slice(0, 5);
    list.innerHTML = top.map(item => `
        <button class="review-mini-row" onclick="openReviewFor('${escapeHtml(item.batch_id)}')">
            ${reviewKindPill(item)}
            <span class="review-mini-name">${escapeHtml(item.filename || item.batch_id)}</span>
            <span class="review-mini-issue text-secondary">${escapeHtml(item.issues[0]?.title || '')}${item.issue_count > 1 ? ` <strong>+${item.issue_count - 1} more</strong>` : ''}</span>
            <i class="fa-solid fa-chevron-right"></i>
        </button>`).join('') +
        (data.items.length > top.length ? `<button class="link-btn review-mini-more" data-quick-review>View all ${data.items.length} files</button>` : '');
    list.querySelector('[data-quick-review]')?.addEventListener('click', () => window.activateView('review-view'));
};

window.openReviewFor = function(batchId) {
    window.closeSheet && window.closeSheet();
    reviewState.highlight = batchId;
    setReviewStatus('open', false);
    window.activateView('review-view');
};

function setReviewStatus(status, reload = true) {
    reviewState.status = status;
    document.querySelectorAll('[data-review-status]').forEach(b => {
        const active = b.getAttribute('data-review-status') === status;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    if (reload) window.loadReviewView();
}

window.rerunReviewItem = function(batchId) {
    const item = reviewState.items.find(i => i.batch_id === batchId);
    if (!item || !item.raw_file) return;
    enqueueJob({ kind: 'rerun', rawFile: item.raw_file, batchId: item.batch_id, label: item.filename, focusOnStart: true });
    showToast('info', `Re-running ${item.filename}. The Review Agent checks it again when the run finishes.`);
    window.activateView('pipeline-monitor-page');
};

window.openReviewDecision = function(batchId) {
    const item = reviewState.items.find(i => i.batch_id === batchId);
    if (!item) return;
    window.openSheet('Close this review', item.filename || batchId, `
        <p class="text-secondary sheet-note">${item.issue_count} problem(s) were found in this file. Record what you decided so the next person knows.</p>
        <label class="review-note-field">
            <span>Note (optional)</span>
            <textarea id="review-note-input" class="page-input" rows="4" maxlength="4000" placeholder="e.g. Filled income per region in the source export and re-ran it.">${escapeHtml(item.note || '')}</textarea>
        </label>
        <div class="review-decision-options">
            <button class="review-decision" onclick="submitReviewDecision('${escapeHtml(batchId)}', 'resolve')">
                <i class="fa-solid fa-circle-check text-green"></i>
                <span><strong>Mark resolved</strong><small>The problem was fixed (source corrected, file re-run, or handled elsewhere).</small></span>
            </button>
            <button class="review-decision" onclick="submitReviewDecision('${escapeHtml(batchId)}', 'dismiss')">
                <i class="fa-solid fa-eye-slash"></i>
                <span><strong>Accept as it is</strong><small>The automatic handling is acceptable for this data; keep the processed result.</small></span>
            </button>
        </div>`);
    setTimeout(() => document.getElementById('review-note-input')?.focus(), 50);
};

window.submitReviewDecision = async function(batchId, action) {
    const note = document.getElementById('review-note-input')?.value;
    await window.decideReview(batchId, action, note);
    window.closeSheet();
};

window.decideReview = async function(batchId, action, note) {
    try {
        const body = { action };
        if (note !== undefined) body.note = note;
        await fetchJson(`/api/v1/review/${encodeURIComponent(batchId)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const done = { resolve: 'marked resolved', dismiss: 'accepted as it is', reopen: 'reopened' }[action];
        showToast('success', `Review ${done}.`);
    } catch (e) {
        showToast('error', e.message);
        return;
    }
    if (document.getElementById('review-view')?.classList.contains('active')) window.loadReviewView();
    window.loadDashboardReview();
};

// Runs the pipeline on the file as the reviewer approved it; the run closes its review unless it fails
window.processReviewItem = function(batchId) {
    const item = reviewState.items.find(i => i.batch_id === batchId) || (editorState.item?.batch_id === batchId ? editorState.item : null);
    if (!item || !item.raw_file) return;
    enqueueJob({ kind: 'rerun', rawFile: item.raw_file, batchId: item.batch_id, label: item.filename, reviewed: true, focusOnStart: true });
    showToast('info', `Processing ${item.filename}. It leaves Human Review when the run finishes.`);
    window.activateView('pipeline-monitor-page');
};

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-review-status]').forEach(btn => {
        btn.addEventListener('click', () => setReviewStatus(btn.getAttribute('data-review-status')));
    });
    document.getElementById('review-search')?.addEventListener('input', renderReviewList);
    document.getElementById('review-category-filter')?.addEventListener('change', renderReviewList);
    document.getElementById('btn-refresh-review')?.addEventListener('click', () => window.loadReviewView());
    window.addEventListener('controlai_login_success', () => window.loadDashboardReview());
    window.loadDashboardReview();
    setInterval(() => window.loadDashboardReview(), 60000);
});
