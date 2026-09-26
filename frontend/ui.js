// Workspace conveniences: the Ctrl+K command palette, dashboard greeting and quick actions,
// and global keyboard shortcuts.

// ---------- Command palette ----------

const palette = {
    items: [],
    filtered: [],
    index: 0
};

function paletteCommands() {
    const go = (view) => () => window.activateView && window.activateView(view);
    const commands = [
        { group: 'Pages', icon: 'fa-gauge-high', label: 'Dashboard', hint: 'Overview & recent activity', run: go('dashboard-view') },
        { group: 'Pages', icon: 'fa-diagram-project', label: 'Pipeline', hint: 'Live data flow monitor', run: go('pipeline-monitor-page') },
        { group: 'Pages', icon: 'fa-clock-rotate-left', label: 'History', hint: 'Every run and its results', run: go('history-view') },
        { group: 'Pages', icon: 'fa-file-lines', label: 'Reports', hint: 'PDF, Word, Markdown & JSON', run: go('reports-view') },
        { group: 'Pages', icon: 'fa-terminal', label: 'Logs', hint: 'Process log of each run', run: go('logs-view') },
        { group: 'Pages', icon: 'fa-database', label: 'Storage', hint: 'All workspace files', run: go('storage-view') },
        { group: 'Pages', icon: 'fa-chart-column', label: 'Power BI', hint: 'Star-schema exports', run: go('powerbi-view') },
        {
            group: 'Actions', icon: 'fa-file-arrow-up', label: 'Upload files to run', hint: 'Pick one or many datasets',
            run: () => {
                go('pipeline-monitor-page')();
                window.switchIngestMode('batch');
                document.getElementById('file-input')?.click();
            }
        },
        {
            group: 'Actions', icon: 'fa-link', label: 'Ingest from URLs', hint: 'One link per line, run in parallel',
            run: () => {
                go('pipeline-monitor-page')();
                window.switchIngestMode('url');
                setTimeout(() => document.getElementById('ingest-url-input')?.focus(), 60);
            }
        },
        {
            group: 'Actions', icon: 'fa-satellite-dish', label: 'Real-time streaming', hint: 'Live feed or simulator',
            run: () => { go('pipeline-monitor-page')(); window.switchIngestMode('realtime'); }
        },
        { group: 'Actions', icon: 'fa-layer-group', label: 'Open Task Center', hint: 'Running, queued & finished tasks', run: () => window.toggleTasksPanel() },
        { group: 'Actions', icon: 'fa-broom', label: 'Clear finished tasks', hint: 'Tidy the Task Center', run: () => window.clearFinishedJobs() },
        {
            group: 'Actions', icon: 'fa-terminal', label: 'Toggle live console', hint: 'Logs of the task on screen',
            run: () => { go('pipeline-monitor-page')(); document.getElementById('btn-toggle-logs')?.click(); }
        },
        { group: 'Actions', icon: 'fa-code-compare', label: 'Compare two runs', hint: 'Metrics & columns side by side', run: () => window.openCompareRuns() },
        { group: 'Actions', icon: 'fa-file-csv', label: 'Export run history', hint: 'Download as CSV', run: () => window.exportHistory() },
        { group: 'Actions', icon: 'fa-heart-pulse', label: 'Check system status', hint: 'Database, AI engine, uptime', run: () => { go('dashboard-view')(); window.loadSystemStatus(true); } },
        { group: 'Actions', icon: 'fa-robot', label: 'Ask the AI assistant', hint: 'Chat about any batch', run: () => openAssistant() },
        { group: 'Actions', icon: 'fa-sliders', label: 'Preferences', hint: 'Parallel runs, alerts, accent', run: () => document.getElementById('btn-dropdown-preferences')?.click() },
        { group: 'Actions', icon: 'fa-key', label: 'API keys', hint: 'Create & manage keys', run: () => document.getElementById('btn-dropdown-security')?.click() }
    ];

    jobManager.jobs.slice(0, 8).forEach(job => {
        commands.push({
            group: 'Tasks', icon: JOB_KIND_ICONS[job.kind] || 'fa-file',
            label: job.label || 'Pending upload', hint: jobStatusText(job),
            run: () => job.batchId ? window.focusJob(job.id, { navigate: true }) : window.toggleTasksPanel()
        });
    });

    (viewState.history || []).filter(r => r.status !== 'Not Run').slice(0, 8).forEach(run => {
        commands.push({
            group: 'Recent runs', icon: 'fa-clock-rotate-left',
            label: run.filename || run.batch_id, hint: `${run.status} · ${run.batch_id}`,
            run: () => window.selectBatchDetail(run.batch_id)
        });
        if (run.clean_file || run.raw_file) {
            commands.push({
                group: 'Recent runs', icon: 'fa-table',
                label: `Preview ${run.filename || run.batch_id}`, hint: 'Rows & column profile',
                run: () => window.previewRun(run.batch_id)
            });
        }
    });
    return commands;
}

function renderPalette() {
    const list = document.getElementById('palette-list');
    if (!list) return;
    if (!palette.filtered.length) {
        list.innerHTML = '<div class="palette-empty">No matches. Try a page name, an action or a file name.</div>';
        return;
    }
    let lastGroup = null;
    list.innerHTML = palette.filtered.map((item, i) => {
        const header = item.group !== lastGroup ? `<div class="palette-group">${escapeHtml(item.group)}</div>` : '';
        lastGroup = item.group;
        return `${header}
            <button class="palette-item${i === palette.index ? ' active' : ''}" data-palette-index="${i}" role="option" aria-selected="${i === palette.index}">
                <i class="fa-solid ${item.icon}"></i>
                <span class="palette-item-label">${escapeHtml(item.label)}</span>
                <span class="palette-item-hint">${escapeHtml(item.hint || '')}</span>
            </button>`;
    }).join('');
    list.querySelector('.palette-item.active')?.scrollIntoView({ block: 'nearest' });
}

function filterPalette(query) {
    const q = query.trim().toLowerCase();
    palette.filtered = !q ? palette.items : palette.items.filter(item =>
        `${item.label} ${item.hint || ''} ${item.group}`.toLowerCase().includes(q));
    palette.index = 0;
    renderPalette();
}

window.openPalette = function() {
    const overlay = document.getElementById('palette-overlay');
    const input = document.getElementById('palette-input');
    if (!overlay || !input || document.getElementById('main-app-container')?.classList.contains('app-hidden')) return;
    palette.items = paletteCommands();
    overlay.hidden = false;
    input.value = '';
    filterPalette('');
    input.focus();
};

window.closePalette = function() {
    const overlay = document.getElementById('palette-overlay');
    if (overlay) overlay.hidden = true;
};

function runPaletteItem(i) {
    const item = palette.filtered[i];
    if (!item) return;
    window.closePalette();
    item.run();
}

function openAssistant() {
    const popup = document.getElementById('chatbot-popup');
    if (popup && !popup.classList.contains('active')) document.getElementById('chatbot-trigger-btn')?.click();
    setTimeout(() => document.getElementById('chat-input')?.focus(), 250);
}

// ---------- Dashboard greeting ----------

function renderDashboardHero() {
    const greeting = document.getElementById('dash-hero-greeting');
    const dateEl = document.getElementById('dash-hero-date');
    if (!greeting) return;
    const hour = new Date().getHours();
    const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    const name = (localStorage.getItem('controlai_username') || '').trim()
        || (localStorage.getItem('controlai_email') || '').split('@')[0];
    greeting.textContent = name ? `${part}, ${name}` : part;
    if (dateEl) dateEl.textContent = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
}

// ---------- wiring ----------

document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('palette-overlay');
    const input = document.getElementById('palette-input');
    const list = document.getElementById('palette-list');

    document.getElementById('btn-open-palette')?.addEventListener('click', () => window.openPalette());
    if (input) {
        input.addEventListener('input', () => filterPalette(input.value));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                const n = palette.filtered.length;
                if (!n) return;
                palette.index = (palette.index + (e.key === 'ArrowDown' ? 1 : -1) + n) % n;
                renderPalette();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                runPaletteItem(palette.index);
            }
        });
    }
    if (list) {
        list.addEventListener('click', (e) => {
            const item = e.target.closest('[data-palette-index]');
            if (!item) return;
            // Commands may open popovers that close on outside clicks; keep this click from reaching them
            e.stopPropagation();
            runPaletteItem(parseInt(item.getAttribute('data-palette-index'), 10));
        });
        list.addEventListener('mousemove', (e) => {
            const item = e.target.closest('[data-palette-index]');
            if (!item) return;
            const i = parseInt(item.getAttribute('data-palette-index'), 10);
            if (i !== palette.index) {
                palette.index = i;
                list.querySelectorAll('.palette-item').forEach((el, j) => el.classList.toggle('active', j === i));
            }
        });
    }
    if (overlay) overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) window.closePalette(); });

    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            if (overlay && !overlay.hidden) window.closePalette();
            else window.openPalette();
        } else if (e.key === 'Escape') {
            if (overlay && !overlay.hidden) window.closePalette();
            window.closeSheet && window.closeSheet();
            document.getElementById('tasks-panel') && window.toggleTasksPanel();
            document.getElementById('notifications-panel')?.remove();
        }
    });

    // Dashboard quick actions
    document.querySelectorAll('[data-quick]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const action = btn.getAttribute('data-quick');
            if (action === 'new-run') {
                window.activateView('pipeline-monitor-page');
                window.switchIngestMode('batch');
                document.getElementById('file-input')?.click();
            } else if (action === 'tasks') {
                e.stopPropagation();
                window.toggleTasksPanel();
            } else if (action === 'assistant') {
                openAssistant();
            } else if (action === 'history') {
                window.activateView('history-view');
            } else if (action === 'compare') {
                window.openCompareRuns();
            } else if (action === 'export') {
                window.exportHistory();
            } else if (action === 'refresh') {
                window.refreshDashboard();
            }
        });
    });

    renderDashboardHero();
    window.addEventListener('controlai_login_success', renderDashboardHero);
    setInterval(renderDashboardHero, 5 * 60 * 1000);
});
