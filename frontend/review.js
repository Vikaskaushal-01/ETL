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

function reviewIssueHtml(issue, open) {
    const icon = REVIEW_CATEGORY_ICONS[issue.category] || 'fa-circle-exclamation';
    return `
        <li class="review-issue sev-${escapeHtml(issue.severity)}">
            <details ${open ? 'open' : ''}>
                <summary>
                    <span class="sev-tag ${escapeHtml(issue.severity)}">${REVIEW_SEVERITY_LABELS[issue.severity] || escapeHtml(issue.severity)}</span>
                    <span class="review-issue-cat"><i class="fa-solid ${icon}"></i> ${escapeHtml(issue.category)}${issue.column ? ` &middot; <code>${escapeHtml(issue.column)}</code>` : ''}</span>
                    <span class="review-issue-title">${escapeHtml(issue.title)}</span>
                    <i class="fa-solid fa-chevron-down review-issue-caret"></i>
                </summary>
                <dl>
                    <dt><i class="fa-solid fa-magnifying-glass"></i> What happened</dt><dd>${escapeHtml(issue.problem)}</dd>
                    <dt><i class="fa-solid fa-scale-unbalanced"></i> Why it matters</dt><dd>${escapeHtml(issue.impact)}</dd>
                    <dt><i class="fa-solid fa-hand-point-right"></i> What to do</dt><dd>${escapeHtml(issue.action)}</dd>
                </dl>
            </details>
        </li>`;
}

function reviewCardHtml(item, category) {
    const me = (localStorage.getItem('controlai_email') || '').toLowerCase();
    const issues = category === 'all' ? item.issues : item.issues.filter(i => i.category === category);
    const categories = Object.entries(item.issues.reduce((acc, i) => ({ ...acc, [i.category]: (acc[i.category] || 0) + 1 }), {}));
    const id = escapeHtml(item.batch_id);
    const canRerun = item.raw_file && item.run_status !== 'Running';
    const decided = item.status !== 'open';
    const note = item.note ? `
        <div class="review-note">
            <i class="fa-solid fa-comment-dots"></i>
            <div><strong>${escapeHtml(item.resolved_by || 'Reviewer')}</strong>${item.resolved_at ? ` <span class="text-secondary">&middot; ${fmtDateTime(item.resolved_at)}</span>` : ''}<p>${escapeHtml(item.note)}</p></div>
        </div>` : '';
    return `
        <article class="review-card ${item.status === 'open' ? `kind-${escapeHtml(item.kind)}` : 'is-closed'} ${reviewState.highlight === item.batch_id ? 'is-highlighted' : ''}" data-review-card="${id}">
            <header class="review-card-head">
                <div class="review-card-title">
                    <div class="review-card-name">
                        ${reviewKindPill(item)}
                        <button class="link-btn run-name" onclick="openRunDetails('${id}')" title="Run details">${escapeHtml(item.filename || item.batch_id)}</button>
                    </div>
                    <div class="review-card-meta text-secondary">
                        <code>${id}</code>
                        <span>Run ${statusBadge(item.run_status || '-')}</span>
                        <span>Flagged ${fmtDateTime(item.flagged_at)}</span>
                        ${item.owner && item.owner.toLowerCase() !== me ? `<span><i class="fa-solid fa-user"></i> ${escapeHtml(item.owner)}</span>` : ''}
                    </div>
                </div>
                <div class="review-card-actions">
                    <button class="btn-refresh" onclick="openRunLog('${id}')" title="Process log: every problem is written there too"><i class="fa-solid fa-terminal"></i> Log</button>
                    ${item.raw_file ? `<button class="btn-refresh" onclick="previewRun('${id}')" title="Preview data & column profile"><i class="fa-solid fa-table"></i> Data</button>` : ''}
                    ${canRerun ? `<button class="btn-refresh" onclick="rerunReviewItem('${id}')" title="Run the pipeline again on this file (after fixing the source)"><i class="fa-solid fa-rotate-right"></i> Re-run</button>` : ''}
                    ${decided
                        ? `<button class="btn-refresh" onclick="decideReview('${id}', 'reopen')"><i class="fa-solid fa-rotate-left"></i> Reopen</button>`
                        : `<button class="btn-refresh review-resolve-btn" onclick="openReviewDecision('${id}')"><i class="fa-solid fa-check"></i> Resolve</button>`}
                </div>
            </header>
            ${item.issue_count ? `<div class="review-cats">${categories.map(([cat, n]) => `<span class="review-cat-chip"><i class="fa-solid ${REVIEW_CATEGORY_ICONS[cat] || 'fa-circle-exclamation'}"></i> ${escapeHtml(cat)} <strong>${n}</strong></span>`).join('')}</div>` : ''}
            ${issues.length ? `<ol class="review-issues">${issues.map((issue, n) => reviewIssueHtml(issue, !decided && n === 0)).join('')}</ol>` : ''}
            ${note}
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
    const query = (document.getElementById('review-search')?.value || '').toLowerCase().trim();
    const category = document.getElementById('review-category-filter')?.value || 'all';
    const items = reviewState.items.filter(item =>
        (category === 'all' || item.issues.some(i => i.category === category)) &&
        (!query || [item.filename, item.batch_id, item.owner, item.note, ...item.issues.flatMap(i => [i.title, i.column, i.category])]
            .some(v => (v || '').toLowerCase().includes(query)))
    );
    if (!items.length) {
        const empty = reviewState.items.length ? 'No files match the filter.'
            : reviewState.status === 'open' ? 'Nothing needs a human right now. Every processed file passed the Review Agent\'s checks.'
            : 'No files here yet.';
        list.innerHTML = `<div class="dash-panel sheet-empty"><i class="fa-solid ${reviewState.items.length ? 'fa-filter' : 'fa-circle-check'}"></i><p>${empty}</p></div>`;
        return;
    }
    list.innerHTML = items.map(item => reviewCardHtml(item, category)).join('');
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
        list.innerHTML = '<div class="review-mini-empty"><i class="fa-solid fa-circle-check"></i> All clear: every processed file passed the checks.</div>';
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
