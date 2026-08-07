// Global Application State
const state = {
    selectedFile: null,
    pipelinePollingInterval: null,
    currentBatchId: null,
    explorerFolderFilter: 'all',
    explorerSearchQuery: '',
    chatContextBatchId: '',
    historyChart: null,
    explorerFiles: [],
    equalizerInterval: null,
    chatHistory: []
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
    initAuth();
    initUserProfileManager();
    initSettingsPage();
    initClock();
    initDrawers();
    initDragAndDrop();
    initPipelineControls();
    initExplorer();
    initChat();
    initChatbotToggle();
    initSVGDrawing();
    initNodeHoverEffects();
    initStageInspector();
    
    // Initial data load
    loadDashboardStats();
    loadReportsList();
    
    document.getElementById('refresh-dashboard-btn').addEventListener('click', () => {
        loadDashboardStats();
        loadExplorerFiles();
    });
});

// Authentication and Session Flow Control
function initAuth() {
    const loginForm = document.getElementById('login-form');
    const loginScreen = document.getElementById('login-screen');
    const mainApp = document.getElementById('main-app-container');
    const loginBtnText = document.getElementById('login-btn-text');

    const profileTrigger = document.getElementById('profile-avatar-trigger');
    const profileDropdown = document.getElementById('profile-dropdown');
    const logoutBtn = document.getElementById('btn-dropdown-logout');

    // 1. Session state checker
    const checkSession = () => {
        const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';
        if (isLoggedIn) {
            loginScreen.classList.add('fade-out');
            mainApp.classList.remove('app-hidden');
            setTimeout(drawNetworkConnections, 600); // Redraw SVG curves when dimensions mount
        } else {
            loginScreen.classList.remove('fade-out');
            mainApp.classList.add('app-hidden');
        }
    };
    checkSession();

    // 2. Authentication submission
    loginForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const user = document.getElementById('login-username').value.trim();
        const pass = document.getElementById('login-password').value.trim();

        if (user !== '' && pass !== '') {
            loginBtnText.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Authenticating...';
            
            fetch('/api/v1/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: user, password: pass })
            })
            .then(async (response) => {
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Authentication failed');
                }
                return response.json();
            })
            .then(data => {
                localStorage.setItem('isLoggedIn', 'true');
                if (data && data.user && data.user.username) {
                    if (data.user.username.includes('@')) {
                        localStorage.setItem('controlai_email', data.user.username);
                    }
                }
                showToast('success', 'Access granted! Welcome to ETL.');
                
                // Transition views
                loginScreen.classList.add('fade-out');
                mainApp.classList.remove('app-hidden');
                
                // Clear inputs
                loginForm.reset();
                loginBtnText.textContent = 'Sign in';
                
                // Trigger login success event for profile manager
                window.dispatchEvent(new Event('controlai_login_success'));

                // Draw graph components
                setTimeout(drawNetworkConnections, 600);
            })
            .catch(err => {
                loginBtnText.textContent = 'Sign in';
                showToast('error', err.message || 'Authentication failed. Please check inputs.');
            });
        } else {
            showToast('error', 'Authentication failed. Please check inputs.');
        }
    });

    // 3. Header Profile Trigger Dropdown
    profileTrigger.addEventListener('click', (e) => {
        e.stopPropagation();
        profileDropdown.classList.toggle('active');
    });

    // Close profile dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!profileDropdown.contains(e.target) && !profileTrigger.contains(e.target)) {
            profileDropdown.classList.remove('active');
        }
    });

    // Dropdown Actions Toasts
    const actions = [
        { id: 'btn-dropdown-security', text: 'Retrieving API Keys...' },
        { id: 'btn-dropdown-preferences', text: 'Loading Client Preferences...' }
    ];
    actions.forEach(act => {
        const el = document.getElementById(act.id);
        if (el) {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                profileDropdown.classList.remove('active');
                showToast('info', act.text);
            });
        }
    });

    // Logout account
    logoutBtn.addEventListener('click', (e) => {
        e.preventDefault();
        profileDropdown.classList.remove('active');
        
        localStorage.setItem('isLoggedIn', 'false');
        showToast('info', 'Logged out successfully.');

        // Revert views
        mainApp.classList.add('app-hidden');
        loginScreen.classList.remove('fade-out');
    });
}

// Live Clock in Topbar
function initClock() {
    const clockEl = document.getElementById('live-clock');
    const updateClock = () => {
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        clockEl.innerHTML = `<i class="fa-solid fa-clock"></i> ${timeStr}`;
    };
    updateClock();
    setInterval(updateClock, 1000);
}

// Drawers & Manual Paste Panel Toggles
function initDrawers() {
    const btnToggleExplorer = document.getElementById('btn-toggle-explorer');
    const btnCloseExplorer = document.getElementById('btn-close-explorer');
    const explorerDrawer = document.getElementById('explorer-drawer');

    const btnToggleLogs = document.getElementById('btn-toggle-logs');
    const btnCloseLogs = document.getElementById('btn-close-logs');
    const consoleDrawer = document.getElementById('console-drawer');

    const btnToggleGraph = document.getElementById('btn-toggle-graph');
    const workspace = document.querySelector('.network-workspace');

    const btnTogglePowerBI = document.getElementById('btn-toggle-powerbi');
    const btnClosePowerBI = document.getElementById('btn-close-powerbi');
    const powerbiDrawer = document.getElementById('powerbi-drawer');
    const btnTriggerPbiRefresh = document.getElementById('btn-trigger-pbi-refresh');

    const updateWorkspaceBlur = () => {
        if (explorerDrawer.classList.contains('active') || consoleDrawer.classList.contains('active') || (powerbiDrawer && powerbiDrawer.classList.contains('active'))) {
            workspace.classList.add('blur-bg');
        } else {
            workspace.classList.remove('blur-bg');
        }
    };

    if (btnTogglePowerBI && powerbiDrawer) {
        btnTogglePowerBI.addEventListener('click', () => {
            powerbiDrawer.classList.toggle('active');
            btnTogglePowerBI.classList.toggle('active');
            if (powerbiDrawer.classList.contains('active')) {
                fetchPowerBIStatus();
            }
            updateWorkspaceBlur();
        });
    }

    if (btnClosePowerBI && powerbiDrawer) {
        btnClosePowerBI.addEventListener('click', () => {
            powerbiDrawer.classList.remove('active');
            if (btnTogglePowerBI) btnTogglePowerBI.classList.remove('active');
            updateWorkspaceBlur();
        });
    }

    if (btnTriggerPbiRefresh) {
        btnTriggerPbiRefresh.addEventListener('click', async () => {
            btnTriggerPbiRefresh.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Refreshing...';
            try {
                const res = await fetch('/api/v1/powerbi/refresh', { method: 'POST' });
                if (res.ok) {
                    const data = await res.json();
                    showToast('success', 'Power BI Dataset Refreshed Successfully!');
                    writeConsoleLog(`[Power BI Gateway] Manual dataset refresh triggered successfully. Timestamp: ${data.last_refresh}`, 'text-yellow');
                    fetchPowerBIStatus();
                } else {
                    showToast('error', 'Power BI dataset refresh request failed.');
                }
            } catch (err) {
                showToast('error', 'Error calling Power BI refresh API.');
            } finally {
                btnTriggerPbiRefresh.innerHTML = '<i class="fa-solid fa-rotate"></i> Trigger Dataset Refresh';
            }
        });
    }

    btnToggleExplorer.addEventListener('click', () => {
        explorerDrawer.classList.toggle('active');
        btnToggleExplorer.classList.toggle('active');
        if (explorerDrawer.classList.contains('active')) {
            loadExplorerFiles();
            loadDashboardStats();
        }
        updateWorkspaceBlur();
    });

    btnCloseExplorer.addEventListener('click', () => {
        explorerDrawer.classList.remove('active');
        btnToggleExplorer.classList.remove('active');
        updateWorkspaceBlur();
    });

    btnToggleLogs.addEventListener('click', () => {
        consoleDrawer.classList.toggle('active');
        btnToggleLogs.classList.toggle('active');
        updateWorkspaceBlur();
    });

    btnCloseLogs.addEventListener('click', () => {
        consoleDrawer.classList.remove('active');
        btnToggleLogs.classList.remove('active');
        updateWorkspaceBlur();
    });

    btnToggleGraph.addEventListener('click', () => {
        btnToggleGraph.classList.add('active');
        explorerDrawer.classList.remove('active');
        consoleDrawer.classList.remove('active');
        if (powerbiDrawer) powerbiDrawer.classList.remove('active');
        if (btnTogglePowerBI) btnTogglePowerBI.classList.remove('active');
        btnToggleExplorer.classList.remove('active');
        btnToggleLogs.classList.remove('active');
        updateWorkspaceBlur();
    });

    const toggleManualInput = document.getElementById('toggle-manual-input');
    const boxBody = toggleManualInput.nextElementSibling;
    const arrowIcon = toggleManualInput.querySelector('.arrow-icon');

    toggleManualInput.addEventListener('click', () => {
        const isHidden = boxBody.style.display === 'none';
        boxBody.style.display = isHidden ? 'block' : 'none';
        arrowIcon.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
    });
}

// Power BI status fetcher
async function fetchPowerBIStatus() {
    try {
        const res = await fetch('/api/v1/powerbi/status');
        if (!res.ok) return;
        const data = await res.json();
        const statusEl = document.getElementById('pbi-conn-status');
        const syncMetaEl = document.getElementById('pbi-sync-meta');
        if (statusEl && data.connector) {
            statusEl.textContent = `MySQL Engine: ${data.connector.status} (${data.connector.server})`;
        }
        if (syncMetaEl && data.dataset) {
            const timeStr = data.dataset.last_refresh ? new Date(data.dataset.last_refresh).toLocaleTimeString() : 'Just now';
            syncMetaEl.textContent = `Database: ${data.connector.database} | Last Refresh: ${timeStr} (${data.dataset.status})`;
        }
    } catch (e) {
        loggerError('fetchPowerBIStatus', e);
    }
}

// SVG Connection Lines Graph Drawing (Sequential connected network pipeline flow)
function initSVGDrawing() {
    setTimeout(drawNetworkConnections, 500);
    window.addEventListener('resize', drawNetworkConnections);
}

function drawNetworkConnections() {
    const svg = document.getElementById('connection-svg');
    if (!svg) return;
    svg.innerHTML = ''; 

    const canvasRect = svg.getBoundingClientRect();
    const getCenterOffset = (el) => {
        const r = el.getBoundingClientRect();
        return {
            x: r.left - canvasRect.left + r.width / 2,
            y: r.top - canvasRect.top + r.height / 2
        };
    };

    const sourceEl = document.getElementById('file-drop-zone');
    const steps = [
        document.getElementById('flow-intake'),
        document.getElementById('flow-transformation'),
        document.getElementById('flow-storage'),
        document.getElementById('flow-report'),
        document.getElementById('flow-pbi')
    ];
    const outputs = [
        document.getElementById('entity-csv-dest'),
        document.getElementById('entity-sql-dest'),
        document.getElementById('entity-word-dest'),
        document.getElementById('entity-pdf-dest'),
        document.getElementById('entity-pbi-dest')
    ];

    if (!sourceEl || steps.some(s => !s)) return;
    const sourcePt = getCenterOffset(sourceEl);

    const appendConnectionPath = (startPt, destPt, stepState, idPrefix) => {
        const cp1x = startPt.x + (destPt.x - startPt.x) * 0.45;
        const cp1y = startPt.y;
        const cp2x = startPt.x + (destPt.x - startPt.x) * 0.55;
        const cp2y = destPt.y;

        const dAttr = `M ${startPt.x} ${startPt.y} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${destPt.x} ${destPt.y}`;
        
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', dAttr);
        path.id = `path-${idPrefix}`;
        
        let colorClass = 'conn-path';
        if (stepState === 'processing') colorClass = 'conn-path-active';
        else if (stepState === 'completed') colorClass = 'conn-path-completed';
        else if (stepState === 'failed') colorClass = 'conn-path-failed';
        
        path.setAttribute('class', colorClass);
        svg.appendChild(path);

        if (stepState === 'processing' || stepState === 'completed') {
            const flowPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            flowPath.setAttribute('d', dAttr);
            
            let flowClass = 'conn-path-flow blue';
            if (stepState === 'processing') flowClass = 'conn-path-flow orange';
            else if (stepState === 'completed') flowClass = 'conn-path-flow green';
            
            flowPath.setAttribute('class', flowClass);
            svg.appendChild(flowPath);
        }
    };

    const getStepState = (el) => {
        if (el.classList.contains('processing')) return 'processing';
        if (el.classList.contains('completed')) return 'completed';
        if (el.classList.contains('failed')) return 'failed';
        return 'waiting';
    };

    // 1. Raw Intake -> Agent 1 Intake
    appendConnectionPath(sourcePt, getCenterOffset(steps[0]), getStepState(steps[0]), 'source-intake');

    // 2. Agent 1 Intake -> Agent 2 Transformation
    let state1to2 = getStepState(steps[1]);
    if (state1to2 === 'waiting' && steps[0].classList.contains('completed')) state1to2 = 'completed';
    appendConnectionPath(getCenterOffset(steps[0]), getCenterOffset(steps[1]), state1to2, 'intake-transform');

    // 3. Agent 2 Transformation -> Agent 3 Storage
    let state2to3 = getStepState(steps[2]);
    if (state2to3 === 'waiting' && steps[1].classList.contains('completed')) state2to3 = 'completed';
    appendConnectionPath(getCenterOffset(steps[1]), getCenterOffset(steps[2]), state2to3, 'transform-storage');

    // 4. Agent 3 Storage -> Agent 4 Report
    let state3to4 = getStepState(steps[3]);
    if (state3to4 === 'waiting' && steps[2].classList.contains('completed')) state3to4 = 'completed';
    appendConnectionPath(getCenterOffset(steps[2]), getCenterOffset(steps[3]), state3to4, 'storage-report');

    // 5. Agent 4 Report -> Step 5 Power BI Gateway
    let state4to5 = getStepState(steps[4]);
    if (state4to5 === 'waiting' && steps[3].classList.contains('completed')) state4to5 = 'completed';
    appendConnectionPath(getCenterOffset(steps[3]), getCenterOffset(steps[4]), state4to5, 'report-pbi');

    // 6. Outputs connections
    const storagePt = getCenterOffset(steps[2]); 
    const reportPt = getCenterOffset(steps[3]);  
    const pbiPt = getCenterOffset(steps[4]);

    outputs.forEach((out, idx) => {
        if (!out) return;
        const outPt = getCenterOffset(out);
        
        let startPt = storagePt;
        let stepState = steps[2].classList.contains('completed') ? 'completed' : 'waiting';
        if (steps[2].classList.contains('failed')) stepState = 'failed';
        
        if (idx === 3) {
            startPt = reportPt;
            stepState = steps[3].classList.contains('completed') ? 'completed' : 'waiting';
            if (steps[3].classList.contains('failed')) stepState = 'failed';
        } else if (idx === 4) {
            startPt = pbiPt;
            stepState = steps[4].classList.contains('completed') ? 'completed' : 'waiting';
            if (steps[4].classList.contains('failed')) stepState = 'failed';
        }

        appendConnectionPath(startPt, outPt, stepState, `step-out-${idx}`);
    });
}

// Hover effects to highlight relations
function initNodeHoverEffects() {
    const hoverMappings = [
        { node: 'file-drop-zone', paths: ['path-source-intake'], color: 'highlight-blue' },
        { node: 'flow-intake', paths: ['path-source-intake', 'path-intake-transform'], color: 'highlight-orange' },
        { node: 'flow-transformation', paths: ['path-intake-transform', 'path-transform-storage'], color: 'highlight-orange' },
        { node: 'flow-storage', paths: ['path-transform-storage', 'path-storage-report', 'path-step-out-0', 'path-step-out-1', 'path-step-out-2'], color: 'highlight-teal' },
        { node: 'flow-report', paths: ['path-storage-report', 'path-report-pbi', 'path-step-out-3'], color: 'highlight-red' },
        { node: 'flow-pbi', paths: ['path-report-pbi', 'path-step-out-4'], color: 'highlight-orange' },
        { node: 'entity-csv-dest', paths: ['path-step-out-0'], color: 'highlight-green' },
        { node: 'entity-sql-dest', paths: ['path-step-out-1'], color: 'highlight-teal' },
        { node: 'entity-word-dest', paths: ['path-step-out-2'], color: 'highlight-blue' },
        { node: 'entity-pdf-dest', paths: ['path-step-out-3'], color: 'highlight-red' },
        { node: 'entity-pbi-dest', paths: ['path-step-out-4'], color: 'highlight-teal' }
    ];

    hoverMappings.forEach(mapping => {
        const el = document.getElementById(mapping.node);
        if (!el) return;

        el.addEventListener('mouseenter', () => {
            mapping.paths.forEach(pId => {
                const pathEl = document.getElementById(pId);
                if (pathEl) {
                    pathEl.classList.add(mapping.color || 'highlight-teal');
                }
            });
        });

        el.addEventListener('mouseleave', () => {
            mapping.paths.forEach(pId => {
                const pathEl = document.getElementById(pId);
                if (pathEl) {
                    pathEl.classList.remove('highlight-blue', 'highlight-teal', 'highlight-green', 'highlight-red', 'highlight-orange');
                }
            });
        });
    });
}

// Drag & Drop Ingestion
function initDragAndDrop() {
    const dropZone = document.getElementById('file-drop-zone');
    const fileInput = document.getElementById('file-input');
    const fileBanner = document.getElementById('file-banner');
    const fileNameEl = document.getElementById('selected-file-name');
    const fileSizeEl = document.getElementById('selected-file-size');
    const clearFileBtn = document.getElementById('btn-clear-file');
    
    dropZone.addEventListener('click', (e) => {
        if (e.target.closest('#btn-clear-file')) return;
        fileInput.click();
    });
    
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });
    
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });
    
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFileSelection(fileInput.files[0]);
        }
    });
    
    clearFileBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        state.selectedFile = null;
        fileInput.value = '';
        fileBanner.style.display = 'none';
        dropZone.querySelector('.node-card-header').style.display = 'block';
        showToast('info', 'File cleared.');
    });
    
    function handleFileSelection(file) {
        state.selectedFile = file;
        fileNameEl.textContent = file.name;
        
        let sizeStr = `${(file.size / 1024).toFixed(1)} KB`;
        if (file.size > 1024 * 1024) {
            sizeStr = `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
        }
        fileSizeEl.textContent = sizeStr;
        
        dropZone.querySelector('.node-card-header').style.display = 'none';
        fileBanner.style.display = 'flex';
        showToast('info', `Loaded file: ${file.name}`);
    }
}

// Pipeline controls trigger
function initPipelineControls() {
    const runBtn = document.getElementById('btn-run-pipeline');
    
    runBtn.addEventListener('click', async () => {
        const hasVirtualInput = document.getElementById('manual-textarea').value.trim() !== '';
        let uploadResult = null;
        
        resetFlowVisual();
        clearConsole();
        
        document.getElementById('console-drawer').classList.add('active');
        document.getElementById('btn-toggle-logs').classList.add('active');
        document.querySelector('.network-workspace').classList.add('blur-bg');

        if (!hasVirtualInput) {
            if (!state.selectedFile) {
                showToast('error', 'Select a file or enter text data to ingest.');
                return;
            }
            writeConsoleLog('[System] Initiating file ingestion...');
            uploadResult = await uploadFile(state.selectedFile);
        } else {
            const rawData = document.getElementById('manual-textarea').value.trim();
            const filename = document.getElementById('manual-filename').value.trim() || 'adhoc_sales.csv';
            
            writeConsoleLog('[System] Generating simulated file from text editor...');
            const blob = new Blob([rawData], { type: 'text/plain' });
            const virtualFile = new File([blob], filename, { type: 'text/plain' });
            uploadResult = await uploadFile(virtualFile);
        }
        
        if (!uploadResult) {
            writeConsoleLog('[System Error] Upload registration failed. Aborting pipeline.', 'text-red');
            showToast('error', 'Ingestion upload failed.');
            return;
        }
        
        const { file_path, batch_id } = uploadResult;
        state.currentBatchId = batch_id;
        document.getElementById('batch-badge-id').textContent = `Batch: ${batch_id}`;
        
        document.getElementById('details-active-batch').textContent = batch_id;
        document.getElementById('details-batch-meta').textContent = `Initiating file parsing...`;

        writeConsoleLog(`[Intake] Preserved original raw file at: ${file_path}`);
        writeConsoleLog(`[System] Initializing autonomous agents graph for pipeline: pipe_${batch_id}`);
        
        startEqualizerPulsing();

        const startSuccess = await startPipeline(file_path, batch_id);
        if (startSuccess) {
            setStepStatus('intake', 'processing', 'Profiling schema...');
            startPipelinePolling(`pipe_${batch_id}`);
        } else {
            showToast('error', 'Failed to start pipeline.');
            setStepStatus('intake', 'failed', 'Crashed');
            stopEqualizerPulsing();
        }
    });
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/api/v1/upload', {
            method: 'POST',
            body: formData
        });
        if (!response.ok) throw new Error('File upload failed.');
        return await response.json();
    } catch (e) {
        loggerError('uploadFile', e);
        return null;
    }
}

async function startPipeline(filePath, batchId) {
    try {
        const response = await fetch('/api/v1/pipeline/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_path: filePath, batch_id: batchId })
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            const msg = errData.detail || 'Failed to start pipeline.';
            writeConsoleLog(`[System Error] ${msg}`, 'text-red');
            showToast('error', msg);
            return false;
        }
        return true;
    } catch (e) {
        loggerError('startPipeline', e);
        writeConsoleLog(`[System Error] ${e.message || 'Failed to start pipeline.'}`, 'text-red');
        showToast('error', e.message || 'Failed to start pipeline.');
        return false;
    }
}

// Pipeline Polling Status
function startPipelinePolling(pipelineId) {
    if (state.pipelinePollingInterval) clearInterval(state.pipelinePollingInterval);
    
    state.pipelinePollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/v1/pipeline/status?pipeline_id=${pipelineId}`);
            if (!response.ok) return;
            const data = await response.json();
            state.currentPipelineData = data;
            
            updateLogsConsole(data.logs);
            if (data.stages) {
                updateFlowVisualFromStages(data.stages);
            } else {
                updateFlowVisualFromLogs(data.logs);
            }
            
            if (data.status === 'Success' || data.status === 'Passed with Warnings') {
                clearInterval(state.pipelinePollingInterval);
                state.pipelinePollingInterval = null;
                
                setStepStatus('intake', 'completed', 'Completed');
                setStepStatus('transformation', 'completed', 'Completed');
                setStepStatus('storage', 'completed', 'Stored');
                setStepStatus('report', 'completed', 'Report Ready');
                setStepStatus('pbi', 'completed', 'Refreshed');
                
                writeConsoleLog(`[System Success] Pipeline complete! Status: ${data.status}. Duration: ${data.execution_time.toFixed(2)}s`, 'text-green');
                showToast('success', `Automation Complete: Batch ${state.currentBatchId}`);
                
                stopEqualizerPulsing();
                
                loadDashboardStats();
                loadExplorerFiles();
                loadReportsList();
                loadChatBatchContexts();
                
                fetchSelectedBatchInsights(state.currentBatchId);
            } else if (data.status === 'Failed') {
                clearInterval(state.pipelinePollingInterval);
                state.pipelinePollingInterval = null;
                
                const activeStep = getActiveStep(data.logs);
                if (activeStep) setStepStatus(activeStep, 'failed', 'Crashed');
                
                writeConsoleLog('[System Failure] Pipeline execution aborted due to errors.', 'text-red');
                showToast('error', `Execution failed.`);
                
                stopEqualizerPulsing();
                loadDashboardStats();
            }
        } catch (e) {
            loggerError('polling', e);
        }
    }, 1500);
}

// Equalizer dynamic pulsation helper
function startEqualizerPulsing() {
    if (state.equalizerInterval) clearInterval(state.equalizerInterval);
    
    const equalizer = document.getElementById('quality-equalizer');
    const bars = equalizer.querySelectorAll('.eq-bar');
    
    state.equalizerInterval = setInterval(() => {
        bars.forEach(bar => {
            const randHeight = Math.floor(Math.random() * 85) + 15;
            bar.style.height = `${randHeight}%`;
        });
    }, 120);
}

function stopEqualizerPulsing() {
    if (state.equalizerInterval) {
        clearInterval(state.equalizerInterval);
        state.equalizerInterval = null;
    }
}

function updateLogsConsole(logs) {
    const consoleBody = document.getElementById('console-logs');
    consoleBody.innerHTML = '';
    if (logs.length === 0) {
        consoleBody.innerHTML = '<p class="text-gray">[System] Initializing logs stream...</p>';
        return;
    }
    
    logs.forEach(log => {
        let logClass = '';
        if (log.includes('[System Error]') || log.includes('Crashed') || log.includes('Failed')) {
            logClass = 'text-red';
        } else if (log.includes('[System Success]') || log.includes('Success')) {
            logClass = 'text-green';
        } else if (log.includes('Power BI')) {
            logClass = 'text-yellow';
        } else if (log.includes('Transformation Agent') || log.includes('Intelligent Storage Agent') || log.includes('Report Generation Agent')) {
            logClass = 'text-blue';
        }
        
        const p = document.createElement('p');
        if (logClass) p.className = logClass;
        p.textContent = log;
        consoleBody.appendChild(p);
    });
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

function updateFlowVisualFromStages(stages) {
    if (!stages) return;
    
    Object.keys(stages).forEach(stageId => {
        const stage = stages[stageId];
        const status = stage.status || 'waiting';
        
        let statusText = 'Waiting';
        if (status === 'processing') {
            if (stageId === 'intake') statusText = 'Profiling...';
            else if (stageId === 'transformation') statusText = 'Cleaning...';
            else if (stageId === 'storage') statusText = 'Formatting...';
            else if (stageId === 'report') statusText = 'Generating PDF...';
            else if (stageId === 'pbi') statusText = 'Refreshing Sync...';
            else statusText = 'Running...';
        } else if (status === 'completed') {
            if (stageId === 'storage') statusText = 'Stored';
            else if (stageId === 'report') statusText = 'Report Ready';
            else if (stageId === 'pbi') statusText = 'Refreshed';
            else statusText = 'Completed';
        } else if (status === 'failed') {
            statusText = 'Crashed';
        }
        
        setStepStatus(stageId, status, statusText);
    });
}

function updateFlowVisualFromLogs(logs) {
    let hasIntake = false;
    let hasTransform = false;
    let hasStorage = false;
    let hasReport = false;
    let hasPbi = false;
    
    logs.forEach(log => {
        if (log.includes('Data Intake Agent') || log.includes('IntakeAgent')) hasIntake = true;
        if (log.includes('Transformation Agent') || log.includes('TransformationAgent')) hasTransform = true;
        if (log.includes('Intelligent Storage Agent') || log.includes('StorageAgent')) hasStorage = true;
        if (log.includes('Report Generation Agent') || log.includes('ReportAgent')) hasReport = true;
        if (log.includes('Power BI') || log.includes('pbi_refresh')) hasPbi = true;
    });
    
    if (hasPbi) {
        setStepStatus('intake', 'completed', 'Completed');
        setStepStatus('transformation', 'completed', 'Completed');
        setStepStatus('storage', 'completed', 'Stored');
        setStepStatus('report', 'completed', 'Report Ready');
        setStepStatus('pbi', 'processing', 'Refreshing Sync...');
    } else if (hasReport) {
        setStepStatus('intake', 'completed', 'Completed');
        setStepStatus('transformation', 'completed', 'Completed');
        setStepStatus('storage', 'completed', 'Stored');
        setStepStatus('report', 'processing', 'Generating PDF...');
        setStepStatus('pbi', 'waiting', 'Waiting');
    } else if (hasStorage) {
        setStepStatus('intake', 'completed', 'Completed');
        setStepStatus('transformation', 'completed', 'Completed');
        setStepStatus('storage', 'processing', 'Formatting...');
        setStepStatus('report', 'waiting', 'Waiting');
        setStepStatus('pbi', 'waiting', 'Waiting');
    } else if (hasTransform) {
        setStepStatus('intake', 'completed', 'Completed');
        setStepStatus('transformation', 'processing', 'Cleaning...');
        setStepStatus('storage', 'waiting', 'Waiting');
        setStepStatus('pbi', 'waiting', 'Waiting');
    } else if (hasIntake) {
        setStepStatus('intake', 'processing', 'Profiling...');
        setStepStatus('transformation', 'waiting', 'Waiting');
        setStepStatus('pbi', 'waiting', 'Waiting');
    }
}

function getActiveStep(logs) {
    if (logs.length === 0) return 'intake';
    const lastLog = logs[logs.length - 1];
    if (lastLog.includes('Power BI') || lastLog.includes('pbi')) return 'pbi';
    if (lastLog.includes('Report')) return 'report';
    if (lastLog.includes('Storage') || lastLog.includes('DB Sync')) return 'storage';
    if (lastLog.includes('Cleansed') || lastLog.includes('Transformation')) return 'transformation';
    return 'intake';
}

function setStepStatus(step, status, text) {
    const stepEl = document.getElementById(`flow-${step}`);
    if (!stepEl) return;
    
    stepEl.className = `flow-step ${status}`;
    stepEl.querySelector('.flow-status-text').textContent = text;
    
    drawNetworkConnections();
}

function resetFlowVisual() {
    setStepStatus('intake', 'waiting', 'Pending Ingest');
    setStepStatus('transformation', 'waiting', 'Waiting');
    setStepStatus('storage', 'waiting', 'Waiting');
    setStepStatus('report', 'waiting', 'Waiting');
    setStepStatus('pbi', 'waiting', 'Waiting');
}

function clearConsole() {
    document.getElementById('console-logs').innerHTML = '';
}

function writeConsoleLog(text, colorClass = '') {
    const consoleBody = document.getElementById('console-logs');
    const p = document.createElement('p');
    if (colorClass) p.className = colorClass;
    p.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
    consoleBody.appendChild(p);
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

// Fetch insights details with a smooth fade animation
async function fetchSelectedBatchInsights(batchId) {
    if (!batchId) return;
    
    const wrapper = document.querySelector('.sidebar-scroll-wrapper');
    wrapper.classList.add('fade-out'); 

    setTimeout(async () => {
        state.currentBatchId = batchId;
        document.getElementById('details-active-batch').textContent = batchId;
        document.getElementById('details-batch-meta').textContent = `Showing analytics for selected run.`;

        try {
            const qRes = await fetch(`/api/v1/data-quality?batch_id=${batchId}`);
            if (qRes.ok) {
                const reports = await qRes.json();
                if (reports && reports.length > 0) {
                    const report = reports[0];
                    const score = report.quality_score;
                    
                    document.getElementById('stat-quality-score').textContent = `${score}%`;
                    document.getElementById('widget-quality-val').textContent = `${score}%`;
                    
                    const equalizer = document.getElementById('quality-equalizer');
                    const bars = equalizer.querySelectorAll('.eq-bar');
                    bars.forEach((bar, idx) => {
                        const offset = (Math.sin(idx) * 6) + (score - 5);
                        const clampedHeight = Math.min(100, Math.max(15, offset));
                        bar.style.height = `${clampedHeight}%`;
                    });
                    
                    const missingCount = report.missing_values ? Object.values(report.missing_values).reduce((a, b) => a + b, 0) : 0;
                    document.getElementById('stat-failed-records').textContent = report.duplicate_count + missingCount;
                }
            }
            
            const rcaRes = await fetch(`/api/v1/root-cause?batch_id=${batchId}`);
            const rcaBody = document.getElementById('rca-details-body');
            rcaBody.innerHTML = '';
            
            if (rcaRes.ok) {
                const rcas = await rcaRes.json();
                if (rcas && rcas.length > 0) {
                    rcas.forEach(rca => {
                        const div = document.createElement('div');
                        div.className = 'rca-item';
                        div.innerHTML = `
                            <div class="rca-title">${rca.issue}</div>
                            <p class="text-secondary"><strong>Root Cause:</strong> ${rca.root_cause}</p>
                            <p class="text-green"><strong>Recommendation:</strong> ${rca.recommendation}</p>
                        `;
                        rcaBody.appendChild(div);
                    });
                } else {
                    rcaBody.innerHTML = `<p class="text-secondary text-center">Batch processed cleanly with no data quality alerts.</p>`;
                }
            }

            const repRes = await fetch('/api/v1/reports/history');
            const container = document.getElementById('pdf-reports-container');
            container.innerHTML = '';
            
            if (repRes.ok) {
                const reports = await repRes.json();
                const batchReport = reports.find(r => r.batch_id === batchId);
                if (batchReport) {
                    const pdfName = batchReport.pdf_path.split('/').pop();
                    const dateStr = batchReport.created_at ? new Date(batchReport.created_at).toLocaleDateString() : 'N/A';
                    
                    const reportId = batchReport.batch_id;
                    container.innerHTML = `
                        <div class="report-item-download" style="flex-direction: column; align-items: stretch; gap: 8px;">
                            <div class="report-info-text" style="margin-bottom: 4px;">
                                <h4>Batch Report: ${reportId}</h4>
                                <span>Created: ${dateStr}</span>
                            </div>
                            <div class="report-download-buttons-row" style="display: flex; gap: 6px; flex-wrap: wrap;">
                                <button class="btn-download-pdf" style="flex: 1; padding: 6px; font-size: 11px;" onclick="downloadReport('${reportId}', 'pdf')"><i class="fa-solid fa-file-pdf"></i> PDF</button>
                                <button class="btn-download-word" style="flex: 1; padding: 6px; font-size: 11px; background: linear-gradient(135deg, #2b5797 0%, #1e3f7a 100%); color: #fff; border: none; border-radius: 4px; cursor: pointer; transition: opacity 0.2s;" onclick="downloadReport('${reportId}', 'docx')"><i class="fa-solid fa-file-word"></i> Word</button>
                                <button class="btn-download-markdown" style="flex: 1; padding: 6px; font-size: 11px; background: linear-gradient(135deg, #333 0%, #111 100%); color: #fff; border: none; border-radius: 4px; cursor: pointer; transition: opacity 0.2s;" onclick="downloadReport('${reportId}', 'markdown')"><i class="fa-solid fa-file-code"></i> MD</button>
                                <button class="btn-download-json" style="flex: 1; padding: 6px; font-size: 11px; background: linear-gradient(135deg, #d2691e 0%, #b22222 100%); color: #fff; border: none; border-radius: 4px; cursor: pointer; transition: opacity 0.2s;" onclick="downloadReport('${reportId}', 'json')"><i class="fa-solid fa-braces"></i> JSON</button>
                            </div>
                        </div>
                    `;
                } else {
                    container.innerHTML = `
                        <div class="no-data-card text-center">
                            <i class="fa-solid fa-file-pdf"></i>
                            <p>No analytical report generated for this batch.</p>
                        </div>`;
                }
            }

            const chatSelect = document.getElementById('chat-batch-select');
            chatSelect.value = batchId;
            state.chatContextBatchId = batchId;

        } catch (e) {
            loggerError('fetchSelectedBatchInsights', e);
        }

        wrapper.classList.remove('fade-out');
    }, 250);
}

// Load Global Dashboard statistics
async function loadDashboardStats() {
    try {
        const response = await fetch('/api/v1/dashboard/summary');
        if (!response.ok) return;
        const stats = await response.json();
        
        document.getElementById('stat-total-processed').textContent = stats.total_rows_processed.toLocaleString();
        document.getElementById('stat-success-rate').textContent = `${stats.success_rate}%`;
        document.getElementById('stat-avg-runtime').textContent = `${stats.processing_time_avg.toFixed(1)}s`;
        document.getElementById('stat-failed-records').textContent = stats.failed_records.toLocaleString();
        
        const tableBody = document.querySelector('#recent-runs-table tbody');
        tableBody.innerHTML = '';
        
        if (stats.recent_runs.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="5" class="text-center">No runs logged yet.</td></tr>';
            return;
        }
        
        stats.recent_runs.forEach(run => {
            const tr = document.createElement('tr');
            let badgeClass = 'success';
            if (run.status === 'Failed') badgeClass = 'failed';
            else if (run.status === 'Passed with Warnings') badgeClass = 'warning';
            else if (run.status === 'Running') badgeClass = 'running';
            
            const startStr = run.start_time ? new Date(run.start_time).toLocaleTimeString() : 'N/A';
            const runtimeStr = run.execution_time ? `${run.execution_time.toFixed(1)}s` : '--';
            
            tr.innerHTML = `
                <td><strong>${run.pipeline_id}</strong></td>
                <td>${startStr}</td>
                <td>${runtimeStr}</td>
                <td><span class="badge ${badgeClass}">${run.status}</span></td>
                <td>
                    <button class="btn-refresh" style="padding: 2px 8px; font-size:10px;" onclick="viewRunLogs('${run.pipeline_id}')"><i class="fa-solid fa-code"></i> Logs</button>
                    <button class="btn-refresh" style="padding: 2px 8px; font-size:10px;" onclick="selectBatchDetail('${run.pipeline_id.replace('pipe_', '')}')"><i class="fa-solid fa-eye"></i> Insights</button>
                </td>
            `;
            tableBody.appendChild(tr);
        });
        
        renderCharts(stats.recent_runs);
    } catch (e) {
        loggerError('loadDashboardStats', e);
    }
}

window.selectBatchDetail = function(batchId) {
    document.getElementById('explorer-drawer').classList.remove('active');
    document.getElementById('btn-toggle-explorer').classList.remove('active');
    document.querySelector('.network-workspace').classList.remove('blur-bg');
    
    fetchSelectedBatchInsights(batchId);
    showToast('info', `Loaded insights: ${batchId}`);
};

function viewRunLogs(pipelineId) {
    document.getElementById('console-drawer').classList.add('active');
    document.getElementById('btn-toggle-logs').classList.add('active');
    document.querySelector('.network-workspace').classList.add('blur-bg');
    startPipelinePolling(pipelineId);
}

function renderCharts(recentRuns) {
    const ctxHistory = document.getElementById('executionHistoryChart').getContext('2d');
    if (state.historyChart) state.historyChart.destroy();
    
    const labels = recentRuns.map(r => r.pipeline_id.replace('pipe_batch_', '')).reverse();
    const runtimes = recentRuns.map(r => r.execution_time || 0.0).reverse();
    
    state.historyChart = new Chart(ctxHistory, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Duration (s)',
                data: runtimes,
                borderColor: '#00f0ff',
                backgroundColor: 'rgba(0, 240, 255, 0.08)',
                fill: true,
                tension: 0.3,
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { color: '#94a3b8', font: { family: 'Outfit', size: 9 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { color: '#94a3b8', font: { family: 'Outfit', size: 9 } }
                }
            }
        }
    });
}

// Storage Explorer Operations
function initExplorer() {
    const searchInput = document.getElementById('explorer-search');
    searchInput.addEventListener('input', (e) => {
        state.explorerSearchQuery = e.target.value.toLowerCase();
        renderExplorerFiles();
    });
    
    const folderCards = document.querySelectorAll('.folder-card');
    folderCards.forEach(card => {
        card.addEventListener('click', () => {
            folderCards.forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            
            const folder = card.getAttribute('data-folder');
            state.explorerFolderFilter = folder;
            
            document.getElementById('explorer-folder-title').textContent = `${folder.toUpperCase()} Storage Directory`;
            renderExplorerFiles();
        });
    });
}

async function loadExplorerFiles() {
    try {
        const response = await fetch('/api/v1/dashboard/datasets');
        if (!response.ok) return;
        const data = await response.json();
        
        state.explorerFiles = data.files || [];
        
        document.getElementById('folder-all-count').textContent = `${state.explorerFiles.length} files`;
        document.getElementById('folder-csv-count').textContent = `${state.explorerFiles.filter(f => f.format === 'CSV').length} files`;
        document.getElementById('folder-word-count').textContent = `${state.explorerFiles.filter(f => f.format === 'WORD').length} files`;
        document.getElementById('folder-sql-count').textContent = `${state.explorerFiles.filter(f => f.format === 'SQL').length} files`;
        
        renderExplorerFiles();
    } catch (e) {
        loggerError('loadExplorerFiles', e);
    }
}

function renderExplorerFiles() {
    const tableBody = document.querySelector('#explorer-files-table tbody');
    tableBody.innerHTML = '';
    
    let filtered = state.explorerFiles;
    if (state.explorerFolderFilter !== 'all') {
        filtered = filtered.filter(f => f.format.toLowerCase() === state.explorerFolderFilter);
    }
    
    if (state.explorerSearchQuery) {
        filtered = filtered.filter(f => f.name.toLowerCase().includes(state.explorerSearchQuery) || f.path.toLowerCase().includes(state.explorerSearchQuery));
    }
    
    if (filtered.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="5" class="text-center">No formatted datasets found.</td></tr>';
        return;
    }
    
    filtered.forEach(file => {
        const tr = document.createElement('tr');
        const fileIcon = file.format === 'CSV' ? 'fa-file-csv text-green' : file.format === 'WORD' ? 'fa-file-word text-blue' : 'fa-database text-purple';
        
        tr.innerHTML = `
            <td><i class="fa-solid ${fileIcon}"></i> <strong>${file.name}</strong></td>
            <td><code>${file.directory}</code></td>
            <td><span class="badge ${file.format.toLowerCase() === 'csv' ? 'success' : file.format.toLowerCase() === 'word' ? 'running' : 'warning'}">${file.format}</span></td>
            <td>${new Date(file.modified_time).toLocaleString()}</td>
            <td>
                <button class="btn-download-file" onclick="downloadDataFile('${file.path}')"><i class="fa-solid fa-download"></i> Get</button>
            </td>
        `;
        tableBody.appendChild(tr);
    });
}

function downloadDataFile(filePath) {
    window.open(`/api/v1/dashboard/download?file_path=${encodeURIComponent(filePath)}`, '_blank');
}

// PDF Reports List Operations
async function loadReportsList() {
    try {
        const response = await fetch('/api/v1/reports/history');
        if (!response.ok) return;
        const reports = await response.json();
        
        if (reports.length > 0 && !state.currentBatchId) {
            fetchSelectedBatchInsights(reports[0].batch_id);
        }
    } catch (e) {
        loggerError('loadReportsList', e);
    }
}

window.downloadReport = function(batchId, format) {
    window.open(`/api/v1/reports/download/${batchId}?format=${format}`, '_blank');
};

// AI Assistant Chat operations
async function loadChatBatchContexts() {
    try {
        const response = await fetch('/api/v1/reports/history');
        if (!response.ok) return;
        const reports = await response.json();
        
        const selectEl = document.getElementById('chat-batch-select');
        selectEl.innerHTML = '<option value="">No Batch Context</option>';
        
        reports.forEach(report => {
            const opt = document.createElement('option');
            opt.value = report.batch_id;
            opt.textContent = report.batch_id;
            if (state.chatContextBatchId === report.batch_id) {
                opt.selected = true;
            }
            selectEl.appendChild(opt);
        });
    } catch (e) {
        loggerError('loadChatBatchContexts', e);
    }
}

document.getElementById('chat-batch-select').addEventListener('change', (e) => {
    state.chatContextBatchId = e.target.value;
    state.chatHistory = [];
    document.getElementById('chat-messages-container').innerHTML = '';
    if (state.chatContextBatchId) {
        fetchSelectedBatchInsights(state.chatContextBatchId);
    } else {
        showToast('info', 'Chat context cleared.');
    }
});

function initChat() {
    const sendBtn = document.getElementById('chat-send-btn');
    const chatInput = document.getElementById('chat-input');
    
    const sendMessage = async () => {
        const message = chatInput.value.trim();
        if (!message) return;
        
        appendChatMessage('user', message);
        chatInput.value = '';
        
        const thinkingId = appendChatMessage('assistant', '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing data logs...', true);
        
        const removeThinking = () => {
            const el = document.getElementById(thinkingId);
            if (el) el.remove();
        };
        
        try {
            const response = await fetch('/api/v1/agent/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    message: message, 
                    batch_id: state.chatContextBatchId || null,
                    history: state.chatHistory
                })
            });
            
            removeThinking();
            
            if (!response.ok) throw new Error('Chat failed');
            const data = await response.json();
            
            appendChatMessage('assistant', data.response);
            
            // Auto-trigger browser download for the first download link found in the response
            const downloadMatch = data.response.match(/\[Download [^\]]+\]\(([^\)]+)\)/);
            if (downloadMatch) {
                const downloadUrl = downloadMatch[1];
                const tempLink = document.createElement('a');
                tempLink.href = downloadUrl;
                tempLink.setAttribute('download', '');
                document.body.appendChild(tempLink);
                tempLink.click();
                document.body.removeChild(tempLink);
            }
        } catch (e) {
            loggerError('chat', e);
            removeThinking();
            appendChatMessage('assistant', 'Connection lost. Confirm microservices status.');
        }
    };
    
    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
}

function appendChatMessage(sender, content, isHtml = false) {
    const container = document.getElementById('chat-messages-container');
    const msgDiv = document.createElement('div');
    const id = `msg-${Date.now()}`;
    msgDiv.id = id;
    msgDiv.className = `message ${sender}`;
    msgDiv.setAttribute('data-raw-content', content);
    
    const icon = sender === 'user' ? 'fa-user' : 'fa-robot';
    let bubbleContent = isHtml ? content : `<p>${content.replace(/\n/g, '<br>')}</p>`;
    if (!isHtml) {
        // Convert Markdown links [text](url) to HTML anchors
        bubbleContent = bubbleContent.replace(/\[([^\]]+)\]\(([^\)]+)\)/g, '<a href="$2" class="chat-link" target="_blank">$1</a>');
        // Store in local history for context awareness
        state.chatHistory.push({ role: sender === 'user' ? 'user' : 'assistant', content: content });
    }
    
    const showCopyBtn = (sender === 'assistant' && !content.includes('typing-loader'));
    
    msgDiv.innerHTML = `
        <div class="message-icon"><i class="fa-solid ${icon}"></i></div>
        <div class="message-bubble" style="position: relative;">
            ${bubbleContent}
            ${showCopyBtn ? `
                <button class="chat-copy-btn" onclick="copyChatMessageText(this, '${id}')" title="Copy response">
                    <i class="fa-regular fa-copy"></i>
                </button>
            ` : ''}
        </div>
    `;
    container.appendChild(msgDiv);
    setTimeout(() => {
        container.scrollTop = container.scrollHeight;
    }, 50);
    return id;
}

window.copyChatMessageText = (btn, msgId) => {
    const msgDiv = document.getElementById(msgId);
    if (!msgDiv) return;
    const textToCopy = msgDiv.getAttribute('data-raw-content') || '';
    
    navigator.clipboard.writeText(textToCopy).then(() => {
        const icon = btn.querySelector('i');
        icon.className = 'fa-solid fa-check';
        btn.style.color = '#14b8a6';
        showToast('success', 'Response copied to clipboard!');
        setTimeout(() => {
            icon.className = 'fa-regular fa-copy';
            btn.style.color = '';
        }, 1500);
    }).catch(err => {
        console.error('Failed to copy text: ', err);
        showToast('error', 'Failed to copy text.');
    });
};

// Notifications Helper
function showToast(type, text) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = 'fa-info-circle';
    if (type === 'success') icon = 'fa-check-circle';
    else if (type === 'error') icon = 'fa-exclamation-triangle';
    
    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${text}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function loggerError(context, err) {
    console.error(`[${context} Error]`, err);
}

function initChatbotToggle() {
    const triggerBtn = document.getElementById('chatbot-trigger-btn');
    const popupContainer = document.getElementById('chatbot-popup');
    const closeBtn = document.getElementById('chatbot-close-btn');
    
    if (triggerBtn && popupContainer) {
        triggerBtn.addEventListener('click', () => {
            triggerBtn.classList.toggle('active');
            popupContainer.classList.toggle('active');
        });
    }
    
    if (closeBtn && popupContainer && triggerBtn) {
        closeBtn.addEventListener('click', () => {
            triggerBtn.classList.remove('active');
            popupContainer.classList.remove('active');
        });
    }
}

// User Profile Username Manager & First-Time Setup Modal
function initUserProfileManager() {
    const modal = document.getElementById('user-profile-modal');
    const inputUsername = document.getElementById('input-username');
    const saveBtn = document.getElementById('btn-save-username');
    const closeBtn = document.getElementById('btn-close-user-modal');
    const userDisplayName = document.getElementById('user-display-name');
    const userDisplayEmail = document.getElementById('user-display-email');
    const btnProfileSettings = document.getElementById('btn-dropdown-profile');
    const btnToggleProfile = document.getElementById('btn-toggle-profile');

    // Update profile text in header dropdown
    const updateProfileUI = () => {
        let storedName = localStorage.getItem('controlai_username');
        if (storedName && storedName.includes('@')) {
            localStorage.removeItem('controlai_username');
            storedName = null;
        }

        if (storedName && storedName.trim() !== '') {
            if (userDisplayName) userDisplayName.textContent = storedName.trim();
        } else {
            if (userDisplayName) userDisplayName.textContent = 'System Administrator';
        }

        const storedEmail = localStorage.getItem('controlai_email');
        if (storedEmail && storedEmail.trim() !== '' && userDisplayEmail) {
            userDisplayEmail.textContent = storedEmail.trim();
        }
    };

    // Show Modal helper
    const openUserModal = () => {
        if (!modal) return;
        const currentName = localStorage.getItem('controlai_username') || '';
        if (inputUsername) inputUsername.value = currentName;

        const titleEl = document.getElementById('user-modal-title');
        const subtitleEl = document.getElementById('user-modal-subtitle');
        if (titleEl) titleEl.textContent = 'Account Profile';
        if (subtitleEl) subtitleEl.textContent = 'Enter your username to personalize your account profile.';
        if (closeBtn) closeBtn.style.display = 'block';

        modal.classList.add('active');
        if (inputUsername) setTimeout(() => inputUsername.focus(), 150);
    };

    const closeUserModal = () => {
        if (modal) modal.classList.remove('active');
    };

    // Save Action
    const handleSaveUsername = () => {
        const name = inputUsername ? inputUsername.value.trim() : '';
        if (!name) {
            showToast('error', 'Please enter a valid username.');
            if (inputUsername) inputUsername.focus();
            return;
        }

        localStorage.setItem('controlai_username', name);
        updateProfileUI();
        closeUserModal();
        showToast('success', `Profile updated! Welcome, ${name}.`);
    };

    if (saveBtn) saveBtn.addEventListener('click', handleSaveUsername);
    if (inputUsername) {
        inputUsername.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handleSaveUsername();
        });
    }

    if (closeBtn) closeBtn.addEventListener('click', closeUserModal);

    // Click outside modal to close
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeUserModal();
            }
        });
    }

    // Initial update of UI without forcing auto pop-up modal
    updateProfileUI();
    window.updateProfileUI = updateProfileUI;

    // Update profile on login success without forcing auto pop-up modal
    window.addEventListener('controlai_login_success', () => {
        updateProfileUI();
    });
}

// Helper to escape HTML characters
function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, 
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

// Full Settings & Profile Management Controller
function initSettingsPage() {
    const overlay = document.getElementById('settings-page-overlay');
    if (!overlay) return;

    const btnBackDashboard = document.getElementById('btn-back-dashboard');
    const tabBtns = document.querySelectorAll('.settings-tab-btn');
    const tabPanels = document.querySelectorAll('.settings-tab-panel');

    // Menu Triggers
    const btnDropdownProfile = document.getElementById('btn-dropdown-profile');
    const btnDropdownSecurity = document.getElementById('btn-dropdown-security');
    const btnDropdownPreferences = document.getElementById('btn-dropdown-preferences');
    const btnToggleProfile = document.getElementById('btn-toggle-profile');

    // Profile Tab Inputs & Buttons
    const inputUsername = document.getElementById('settings-username');
    const inputEmail = document.getElementById('settings-email');
    const inputDob = document.getElementById('settings-dob');
    const inputCurrentPass = document.getElementById('settings-current-pass');
    const inputNewPass = document.getElementById('settings-new-pass');
    const inputConfirmPass = document.getElementById('settings-confirm-pass');
    const btnSaveProfile = document.getElementById('btn-save-profile-settings');

    // API Keys Inputs & Buttons
    const inputKeyName = document.getElementById('new-api-key-name');
    const selectKeyEnv = document.getElementById('new-api-key-env');
    const btnCreateKey = document.getElementById('btn-create-api-key');
    const apiKeysTbody = document.getElementById('api-keys-tbody');
    const apiLogsList = document.getElementById('api-logs-list');
    const btnSaveApiKeys = document.getElementById('btn-save-apikeys');

    // Preferences Inputs & Buttons
    const selectAccent = document.getElementById('pref-accent-theme');
    const selectGlass = document.getElementById('pref-glass-intensity');
    const selectDbEngine = document.getElementById('pref-db-engine');
    const selectLogLevel = document.getElementById('pref-log-level');
    const checkAutoAi = document.getElementById('pref-auto-ai');
    const checkAudioAlerts = document.getElementById('pref-audio-alerts');
    const btnSavePreferences = document.getElementById('btn-save-preferences');

    // Open Settings View at target tab
    window.openSettingsPage = function(targetTabId = 'tab-profile-settings') {
        // Close profile dropdown if open
        const profileDropdown = document.getElementById('profile-dropdown');
        if (profileDropdown) profileDropdown.classList.remove('active');

        // Activate matching tab
        tabBtns.forEach(btn => {
            if (btn.getAttribute('data-tab') === targetTabId) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        tabPanels.forEach(panel => {
            if (panel.id === targetTabId) {
                panel.classList.add('active');
            } else {
                panel.classList.remove('active');
            }
        });

        // Populate fields
        loadProfileData();
        loadApiKeysData();
        loadPreferencesData();

        // Show Overlay
        overlay.style.display = 'flex';
        overlay.classList.add('active');
    };

    const closeSettingsPage = function() {
        overlay.style.display = 'none';
        overlay.classList.remove('active');
    };

    // Bind Back to Dashboard
    if (btnBackDashboard) {
        btnBackDashboard.addEventListener('click', () => {
            closeSettingsPage();
            showToast('info', 'Returned to Dashboard.');
        });
    }

    // Bind Tab switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.getAttribute('data-tab');
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanels.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const targetPanel = document.getElementById(tabId);
            if (targetPanel) targetPanel.classList.add('active');
        });
    });

    // Bind Navbar / Dropdown Triggers
    if (btnDropdownProfile) {
        btnDropdownProfile.addEventListener('click', (e) => {
            e.preventDefault();
            openSettingsPage('tab-profile-settings');
        });
    }
    if (btnDropdownSecurity) {
        btnDropdownSecurity.addEventListener('click', (e) => {
            e.preventDefault();
            openSettingsPage('tab-api-keys');
        });
    }
    if (btnDropdownPreferences) {
        btnDropdownPreferences.addEventListener('click', (e) => {
            e.preventDefault();
            openSettingsPage('tab-preferences');
        });
    }
    if (btnToggleProfile) {
        btnToggleProfile.addEventListener('click', (e) => {
            e.preventDefault();
            openSettingsPage('tab-profile-settings');
        });
    }

    // Load Profile Data
    function loadProfileData() {
        const storedName = localStorage.getItem('controlai_username') || 'System Administrator';
        const storedEmail = localStorage.getItem('controlai_email') || 'admin@controlai.net';
        const storedDob = localStorage.getItem('controlai_dob') || '';

        if (inputUsername) inputUsername.value = storedName;
        if (inputEmail) inputEmail.value = storedEmail;
        if (inputDob) inputDob.value = storedDob;
        if (inputCurrentPass) inputCurrentPass.value = '';
        if (inputNewPass) inputNewPass.value = '';
        if (inputConfirmPass) inputConfirmPass.value = '';
    }

    // Save Profile Action
    if (btnSaveProfile) {
        btnSaveProfile.addEventListener('click', () => {
            const username = inputUsername ? inputUsername.value.trim() : '';
            const email = inputEmail ? inputEmail.value.trim() : '';
            const dob = inputDob ? inputDob.value : '';
            const newPass = inputNewPass ? inputNewPass.value : '';
            const confirmPass = inputConfirmPass ? inputConfirmPass.value : '';

            if (!username) {
                showToast('error', 'Please enter a valid username.');
                if (inputUsername) inputUsername.focus();
                return;
            }

            if (newPass !== '' && newPass !== confirmPass) {
                showToast('error', 'New passwords do not match!');
                if (inputConfirmPass) inputConfirmPass.focus();
                return;
            }

            // Save to localStorage
            localStorage.setItem('controlai_username', username);
            if (email) localStorage.setItem('controlai_email', email);
            if (dob) localStorage.setItem('controlai_dob', dob);

            // Synchronize UI display names across whole project
            const userDisplayName = document.getElementById('user-display-name');
            const userDisplayEmail = document.getElementById('user-display-email');
            if (userDisplayName) userDisplayName.textContent = username;
            if (userDisplayEmail && email) userDisplayEmail.textContent = email;

            showToast('success', `Profile updated! Welcome, ${username}.`);
            closeSettingsPage();
        });
    }

    // API Keys State & Rendering
    function getStoredApiKeys() {
        const raw = localStorage.getItem('controlai_apikeys');
        if (raw) {
            try { return JSON.parse(raw); } catch (e) {}
        }
        // Initial Default Keys if none exist
        const initialKeys = [
            { id: '1', name: 'Production Pipeline Automation', key: 'ctl_live_8f93a74b12e0912c', env: 'Production', created: '2026-07-28' },
            { id: '2', name: 'Staging Analytics Integration', key: 'ctl_live_3b11c900e57211fa', env: 'Staging', created: '2026-08-01' }
        ];
        localStorage.setItem('controlai_apikeys', JSON.stringify(initialKeys));
        return initialKeys;
    }

    function loadApiKeysData() {
        const keys = getStoredApiKeys();
        renderApiKeysTable(keys);
        renderApiLogs();
    }

    function renderApiKeysTable(keys) {
        if (!apiKeysTbody) return;
        apiKeysTbody.innerHTML = '';
        if (keys.length === 0) {
            apiKeysTbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-secondary); padding:20px;">No API keys created yet.</td></tr>`;
            return;
        }

        keys.forEach(k => {
            const tr = document.createElement('tr');
            const masked = k.key.substring(0, 9) + '••••••••' + k.key.substring(k.key.length - 4);
            const envClass = k.env.toLowerCase();
            tr.innerHTML = `
                <td><strong>${escapeHTML(k.name)}</strong></td>
                <td>
                    <div class="key-code-wrapper">
                        <span class="key-code">${masked}</span>
                        <button class="btn-icon-subtle copy-key-btn" data-key="${k.key}" title="Copy API Key"><i class="fa-solid fa-copy"></i></button>
                    </div>
                </td>
                <td><span class="env-badge ${envClass}">${k.env}</span></td>
                <td><span style="color:var(--text-secondary); font-size:0.85rem;">${k.created}</span></td>
                <td>
                    <button class="btn-icon-subtle delete delete-key-btn" data-id="${k.id}" title="Delete Key"><i class="fa-solid fa-trash-can"></i></button>
                </td>
            `;
            apiKeysTbody.appendChild(tr);
        });

        // Copy Key event handlers
        apiKeysTbody.querySelectorAll('.copy-key-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const keyVal = btn.getAttribute('data-key');
                navigator.clipboard.writeText(keyVal).then(() => {
                    showToast('success', 'API Secret Key copied to clipboard!');
                }).catch(() => {
                    showToast('info', `API Key: ${keyVal}`);
                });
            });
        });

        // Delete Key event handlers
        apiKeysTbody.querySelectorAll('.delete-key-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const keyId = btn.getAttribute('data-id');
                let currentKeys = getStoredApiKeys();
                currentKeys = currentKeys.filter(item => item.id !== keyId);
                localStorage.setItem('controlai_apikeys', JSON.stringify(currentKeys));
                renderApiKeysTable(currentKeys);
                showToast('info', 'API Key deleted successfully.');
            });
        });
    }

    // Generate New API Key
    if (btnCreateKey) {
        btnCreateKey.addEventListener('click', () => {
            const keyName = inputKeyName ? inputKeyName.value.trim() : '';
            const env = selectKeyEnv ? selectKeyEnv.value : 'Production';

            if (!keyName) {
                showToast('error', 'Please enter a key description name.');
                if (inputKeyName) inputKeyName.focus();
                return;
            }

            const randHex = Array.from({length: 16}, () => Math.floor(Math.random() * 16).toString(16)).join('');
            const newKeyObj = {
                id: Date.now().toString(),
                name: keyName,
                key: `ctl_live_${randHex}`,
                env: env,
                created: new Date().toISOString().split('T')[0]
            };

            const currentKeys = getStoredApiKeys();
            currentKeys.unshift(newKeyObj);
            localStorage.setItem('controlai_apikeys', JSON.stringify(currentKeys));
            renderApiKeysTable(currentKeys);

            if (inputKeyName) inputKeyName.value = '';
            showToast('success', `Generated API Key for ${keyName}`);
        });
    }

    // Render API Activity Logs
    function renderApiLogs() {
        if (!apiLogsList) return;
        const now = new Date();
        const logs = [
            { time: new Date(now - 120000).toLocaleTimeString(), endpoint: 'POST /api/pipeline/start', ip: '192.168.1.45', status: '200' },
            { time: new Date(now - 450000).toLocaleTimeString(), endpoint: 'GET /api/reports/list', ip: '192.168.1.45', status: '200' },
            { time: new Date(now - 1800000).toLocaleTimeString(), endpoint: 'POST /api/upload', ip: '10.0.0.12', status: '401' }
        ];

        apiLogsList.innerHTML = logs.map(l => `
            <div class="api-log-entry status-${l.status}">
                <div class="log-meta">
                    <span class="log-time">${l.time}</span>
                    <span class="log-endpoint">${l.endpoint}</span>
                    <span class="log-ip">(${l.ip})</span>
                </div>
                <span class="log-status s${l.status}">${l.status} ${l.status === '200' ? 'OK' : 'UNAUTHORIZED'}</span>
            </div>
        `).join('');
    }

    if (btnSaveApiKeys) {
        btnSaveApiKeys.addEventListener('click', () => {
            showToast('success', 'API Keys configuration saved.');
            closeSettingsPage();
        });
    }

    // Preferences Tab Load & Save
    function loadPreferencesData() {
        if (selectAccent) selectAccent.value = localStorage.getItem('pref_accent_theme') || 'cyan';
        if (selectGlass) selectGlass.value = localStorage.getItem('pref_glass_intensity') || 'high';
        if (selectDbEngine) selectDbEngine.value = localStorage.getItem('pref_db_engine') || 'sqlite';
        if (selectLogLevel) selectLogLevel.value = localStorage.getItem('pref_log_level') || 'INFO';
        if (checkAutoAi) checkAutoAi.checked = localStorage.getItem('pref_auto_ai') !== 'false';
        if (checkAudioAlerts) checkAudioAlerts.checked = localStorage.getItem('pref_audio_alerts') !== 'false';
    }

    // Apply saved accent theme on init
    applyAccentTheme(localStorage.getItem('pref_accent_theme') || 'cyan');

    if (btnSavePreferences) {
        btnSavePreferences.addEventListener('click', () => {
            const themeVal = selectAccent ? selectAccent.value : 'cyan';
            if (selectAccent) localStorage.setItem('pref_accent_theme', themeVal);
            if (selectGlass) localStorage.setItem('pref_glass_intensity', selectGlass.value);
            if (selectDbEngine) localStorage.setItem('pref_db_engine', selectDbEngine.value);
            if (selectLogLevel) localStorage.setItem('pref_log_level', selectLogLevel.value);
            if (checkAutoAi) localStorage.setItem('pref_auto_ai', checkAutoAi.checked ? 'true' : 'false');
            if (checkAudioAlerts) localStorage.setItem('pref_audio_alerts', checkAudioAlerts.checked ? 'true' : 'false');

            applyAccentTheme(themeVal);
            showToast('success', 'Preferences saved & applied successfully!');
            closeSettingsPage();
        });
    }
}

// Accent Theme Dynamic Switcher
function applyAccentTheme(theme) {
    const root = document.documentElement;
    if (theme === 'emerald') {
        root.style.setProperty('--color-blue', '#10b981');
        root.style.setProperty('--color-teal', '#059669');
        root.style.setProperty('--border-glow', 'rgba(16, 185, 129, 0.35)');
    } else if (theme === 'violet') {
        root.style.setProperty('--color-blue', '#a855f7');
        root.style.setProperty('--color-teal', '#8b5cf6');
        root.style.setProperty('--border-glow', 'rgba(168, 85, 247, 0.35)');
    } else {
        root.style.setProperty('--color-blue', '#00f0ff');
        root.style.setProperty('--color-teal', '#14b8a6');
        root.style.setProperty('--border-glow', 'rgba(0, 240, 255, 0.25)');
    }
}

// SnapLogic Stage Inspector modal initialization
function initStageInspector() {
    const stages = ['intake', 'transformation', 'storage', 'report', 'pbi'];
    stages.forEach(stageId => {
        const el = document.getElementById(`flow-${stageId}`);
        if (el) {
            el.addEventListener('click', () => {
                openStageInspector(stageId);
            });
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    openStageInspector(stageId);
                }
            });
        }
    });

    const closeBtn = document.getElementById('btn-close-stage-inspector');
    const modal = document.getElementById('stage-inspector-modal');
    if (closeBtn && modal) {
        closeBtn.addEventListener('click', () => {
            modal.style.display = 'none';
        });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    }
}

// Opens the stage inspector overlay and queries stage processed data in real time
function renderPreviewTable(previewData, title) {
    if (!previewData || !Array.isArray(previewData) || previewData.length === 0) return '';
    
    const headers = Object.keys(previewData[0]);
    let html = `
        <div style="margin-top: 10px; margin-bottom: 14px;">
            <h4 style="font-size:12px; margin-bottom:6px; color:var(--color-blue);"><i class="fa-solid fa-table"></i> ${title}</h4>
            <div style="max-height: 180px; overflow-x: auto; overflow-y: auto; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px;">
                <table class="inspector-table" style="font-size:10px; margin-bottom:0; width:100%; white-space:nowrap;">
                    <thead>
                        <tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>
                    </thead>
                    <tbody>
                        ${previewData.map(row => `
                            <tr>${headers.map(h => {
                                const val = row[h];
                                return `<td>${val === null || val === undefined ? '<em>null</em>' : val}</td>`;
                            }).join('')}</tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
    return html;
}

function openStageInspector(stageId) {
    const modal = document.getElementById('stage-inspector-modal');
    if (!modal) return;
    
    const titleEl = document.getElementById('stage-inspector-title');
    const subtitleEl = document.getElementById('stage-inspector-subtitle');
    const iconEl = document.getElementById('stage-inspector-icon');
    const metaComponent = document.getElementById('stage-meta-component');
    const metaStatus = document.getElementById('stage-meta-status');
    const metaQuality = document.getElementById('stage-meta-quality');
    const metaType = document.getElementById('stage-meta-type');
    const previewContainer = document.getElementById('stage-inspector-data-preview');
    
    const pipeData = state.currentPipelineData || {};
    const stages = pipeData.stages || {};
    const stage = stages[stageId] || {
        status: 'waiting',
        start_time: null,
        end_time: null,
        input: {},
        output: {},
        logs: [],
        metadata: {}
    };
    
    let componentName = '';
    let iconClass = '';
    let stageTitle = '';
    let subtitle = '';
    let statusText = 'Waiting';
    let statusClass = 'badge warning';
    let qualityText = 'N/A';
    let typeText = 'N/A';
    
    const status = stage.status || 'waiting';
    if (status === 'completed') {
        statusText = 'Completed';
        statusClass = 'badge success';
    } else if (status === 'processing') {
        statusText = 'Running / Executing';
        statusClass = 'badge running';
    } else if (status === 'failed') {
        statusText = 'Failed / Error';
        statusClass = 'badge failed';
    }
    
    if (stageId === 'intake') {
        stageTitle = 'File Reader & Iris AI Intake Snap';
        subtitle = 'Ingests raw files and analyzes metadata profiling';
        componentName = 'com.snaplogic.snaps.ai.IrisIntakeSnap';
        iconClass = 'fa-solid fa-inbox';
        qualityText = stage.output && stage.output.estimated_quality ? `${stage.output.estimated_quality}%` : 'N/A';
        typeText = stage.metadata && stage.metadata.file_type ? stage.metadata.file_type : 'N/A';
    } 
    else if (stageId === 'transformation') {
        stageTitle = 'Data Cleanser Snap';
        subtitle = 'Applies schema profiling, duplicate removal, date formatting, and null imputation';
        componentName = 'com.snaplogic.snaps.transform.DataCleanserSnap';
        iconClass = 'fa-solid fa-wand-magic-sparkles';
        qualityText = stage.output && stage.output.quality_after ? `${stage.output.quality_after}%` : 'N/A';
        typeText = 'Dataset';
    }
    else if (stageId === 'storage') {
        stageTitle = 'SQL Staging & Target Format Snap';
        subtitle = 'Orchestrates loading into MySQL staging databases and selects optimal physical formats';
        componentName = 'com.snaplogic.snaps.database.MySQLStagingSnap';
        iconClass = 'fa-solid fa-database';
        typeText = stage.output && stage.output.format_selected ? stage.output.format_selected : 'N/A';
    }
    else if (stageId === 'report') {
        stageTitle = 'Docx & Report Exporter Snap';
        subtitle = 'Generates PDF analysis reports and saves Microsoft Word (.docx) copies to Cleaned Data';
        componentName = 'com.snaplogic.snaps.docx.DocxReportSnap';
        iconClass = 'fa-solid fa-file-word';
        typeText = 'DOCX/PDF';
    }
    else if (stageId === 'pbi') {
        stageTitle = 'Power BI Gateway Sync Snap';
        subtitle = 'Connected directly to SnapLogic pipeline for real-time model updates';
        componentName = 'com.snaplogic.snaps.powerbi.PowerBIGatewaySnap';
        iconClass = 'fa-solid fa-chart-column';
        typeText = 'Star Schema';
    }
    
    // Format timestamps
    const startTimeStr = stage.start_time ? new Date(stage.start_time).toLocaleTimeString() : 'N/A';
    const endTimeStr = stage.end_time ? new Date(stage.end_time).toLocaleTimeString() : (status === 'processing' ? 'Running...' : 'N/A');
    const duration = stage.start_time && stage.end_time 
        ? ((new Date(stage.end_time) - new Date(stage.start_time)) / 1000).toFixed(2) + 's' 
        : (status === 'processing' ? 'Running' : 'N/A');
        
    let dataPreviewHtml = '';
    
    if (status === 'waiting') {
        dataPreviewHtml = `
            <div style="text-align: center; padding: 40px 20px;">
                <div style="font-size: 32px; margin-bottom: 12px; color: rgba(255,255,255,0.2);"><i class="fa-solid fa-hourglass-start"></i></div>
                <h4 style="margin-bottom: 6px;">Awaiting Pipeline Execution</h4>
                <p class="text-secondary" style="font-size:12px;">This stage is waiting for the upstream SnapLogic execution nodes to complete.</p>
            </div>
        `;
    } else {
        // Inputs table rows
        let inputRows = '';
        Object.keys(stage.input || {}).forEach(k => {
            if (k !== 'preview') {
                inputRows += `<tr><td>${k}</td><td><code>${stage.input[k]}</code></td></tr>`;
            }
        });
        if (!inputRows) inputRows = '<tr><td colspan="2" class="text-secondary">No input parameters registered.</td></tr>';
        
        // Outputs table rows
        let outputRows = '';
        Object.keys(stage.output || {}).forEach(k => {
            if (k !== 'preview' && k !== 'sql_preview') {
                outputRows += `<tr><td>${k}</td><td><strong>${stage.output[k]}</strong></td></tr>`;
            }
        });
        if (!outputRows) outputRows = '<tr><td colspan="2" class="text-secondary">No processed output data yet.</td></tr>';
        
        // Metadata table rows
        let metaRows = '';
        Object.keys(stage.metadata || {}).forEach(k => {
            if (k !== 'transformation_history') {
                const val = typeof stage.metadata[k] === 'object' ? JSON.stringify(stage.metadata[k], null, 1) : stage.metadata[k];
                metaRows += `<tr><td>${k}</td><td><code>${val}</code></td></tr>`;
            }
        });
        if (!metaRows) metaRows = '<tr><td colspan="2" class="text-secondary">No additional metadata parameters.</td></tr>';
        
        // Logs lines
        let logLinesHtml = '';
        if (stage.logs && stage.logs.length > 0) {
            stage.logs.forEach(log => {
                logLinesHtml += `<div style="color: rgba(255,255,255,0.85); margin-bottom: 4px;"><span style="color: var(--color-blue); margin-right: 6px;">[${startTimeStr}]</span>${log}</div>`;
            });
        } else {
            logLinesHtml = '<div class="text-secondary">No execution logs recorded for this stage.</div>';
        }
        
        // Side-by-side or singular Previews
        let previewHtml = '';
        
        // 1. Intake Stage Raw Data Preview
        if (stageId === 'intake' && stage.output && stage.output.preview) {
            previewHtml += renderPreviewTable(stage.output.preview, 'Ingested Raw Data Preview (First 5 Rows)');
        }
        
        // 2. Transformation Stage Raw Input vs Cleaned Output Previews
        if (stageId === 'transformation') {
            if (stage.input && stage.input.preview) {
                previewHtml += renderPreviewTable(stage.input.preview, 'Raw Data Before Cleansing (Input)');
            }
            if (stage.output && stage.output.preview) {
                previewHtml += renderPreviewTable(stage.output.preview, 'Standardized Clean Data After Cleansing (Output)');
            }
            
            // Add column-by-column transformation history timeline/table
            let historyRows = '';
            const historyList = stage.metadata ? stage.metadata.transformation_history : null;
            if (historyList && Array.isArray(historyList) && historyList.length > 0) {
                historyList.forEach(step => {
                    historyRows += `
                        <tr>
                            <td><code>${step.column_name || 'General'}</code></td>
                            <td><span style="color:var(--color-red); text-decoration:line-through; font-size:10px;">${step.old_value !== null ? step.old_value : 'null'}</span></td>
                            <td><span style="color:var(--color-green); font-weight:600;">${step.new_value !== null ? step.new_value : 'null'}</span></td>
                            <td><span style="font-size:10px; color:rgba(255,255,255,0.7);">${step.reason || 'Auto-cleansed'}</span></td>
                        </tr>
                    `;
                });
                
                previewHtml += `
                    <div style="margin-top: 10px; margin-bottom: 14px;">
                        <h4 style="font-size:12px; margin-bottom:6px; color:var(--color-blue);"><i class="fa-solid fa-clock-rotate-left"></i> Column Transformation Audit Log (Transformation History)</h4>
                        <div style="max-height: 180px; overflow-y: auto; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px;">
                            <table class="inspector-table" style="font-size:10px; margin-bottom:0; width:100%;">
                                <thead>
                                    <tr><th>Target Column</th><th>Original State</th><th>Cleaned State</th><th>Operation Performed</th></tr>
                                </thead>
                                <tbody>
                                    ${historyRows}
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
            }
        }
        
        // 3. Storage Stage Clean Input vs SQL Script Preview
        if (stageId === 'storage') {
            if (stage.input && stage.input.preview) {
                previewHtml += renderPreviewTable(stage.input.preview, 'Clean Data Before Loading (Input)');
            }
            if (stage.output && stage.output.sql_preview) {
                previewHtml += `
                    <div style="margin-top: 10px; margin-bottom: 14px;">
                        <h4 style="font-size:12px; margin-bottom:6px; color:var(--color-blue);"><i class="fa-solid fa-code"></i> Generated SQL Schema & Insert Statements (Output Preview)</h4>
                        <pre style="background: rgba(0,0,0,0.45); border-radius:6px; padding:10px; font-family:monospace; font-size:10px; border:1px solid rgba(255,255,255,0.08); overflow-x:auto; color:#ccc; max-height: 180px; margin:0;">${stage.output.sql_preview}</pre>
                    </div>
                `;
            }
        }
        
        // 4. Report Stage Download Action
        if (stageId === 'report' && stage.output && (stage.output.pdf_path || stage.output.docx_path)) {
            previewHtml += `
                <div style="margin-top: 10px; margin-bottom: 14px; padding: 12px; background: rgba(20, 184, 166, 0.06); border-radius: 6px; border: 1px dashed var(--color-blue); font-size:12px;">
                    <h5 style="margin-top:0; margin-bottom:8px; color:var(--color-blue); font-weight:600;"><i class="fa-solid fa-file-arrow-down" style="margin-right:4px;"></i> Download Exported Documents</h5>
                    <div style="display:flex; gap:16px;">
            `;
            if (stage.output.pdf_path) {
                previewHtml += `<div><i class="fa-regular fa-file-pdf" style="color:var(--color-red); margin-right:4px;"></i> <a href="/api/v1/dashboard/download?file_path=${encodeURIComponent(stage.output.pdf_path)}" target="_blank" style="color:#fff; text-decoration:underline; font-weight:600;">Executive PDF Report</a></div>`;
            }
            if (stage.output.docx_path) {
                previewHtml += `<div><i class="fa-regular fa-file-word" style="color:var(--color-blue); margin-right:4px;"></i> <a href="/api/v1/dashboard/download?file_path=${encodeURIComponent(stage.output.docx_path)}" target="_blank" style="color:#fff; text-decoration:underline; font-weight:600;">Microsoft Word (.docx) Clean Export</a></div>`;
            }
            previewHtml += `
                    </div>
                </div>
            `;
        }
        
        dataPreviewHtml = `
            <!-- Timings Section -->
            <div style="display:flex; justify-content:space-between; margin-bottom:14px; padding: 10px; background: rgba(255,255,255,0.03); border-radius:6px; border:1px solid rgba(255,255,255,0.05); font-size:12px;">
                <div><i class="fa-regular fa-clock" style="margin-right:4px;"></i> Started: <strong>${startTimeStr}</strong></div>
                <div><i class="fa-solid fa-clock-rotate-left" style="margin-right:4px;"></i> Ended: <strong>${endTimeStr}</strong></div>
                <div><i class="fa-solid fa-stopwatch" style="margin-right:4px;"></i> Duration: <strong style="color: var(--color-blue);">${duration}</strong></div>
            </div>
            
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:14px;">
                <!-- Inputs Section -->
                <div>
                    <h4 style="font-size:13px; margin-bottom:6px; color:rgba(255,255,255,0.7);"><i class="fa-solid fa-sign-in" style="margin-right:4px;"></i> Input Received</h4>
                    <table class="inspector-table" style="font-size:11px; margin-bottom:0;">
                        <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
                        <tbody>${inputRows}</tbody>
                    </table>
                </div>
                
                <!-- Outputs Section -->
                <div>
                    <h4 style="font-size:13px; margin-bottom:6px; color:rgba(255,255,255,0.7);"><i class="fa-solid fa-sign-out" style="margin-right:4px;"></i> Processed Output</h4>
                    <table class="inspector-table" style="font-size:11px; margin-bottom:0;">
                        <thead><tr><th>Metric</th><th>Staging Value</th></tr></thead>
                        <tbody>${outputRows}</tbody>
                    </table>
                </div>
            </div>
            
            <!-- Dynamic Previews (Tables, Timelines, SQL scripts) -->
            ${previewHtml}
            
            <!-- Metadata & Config Section -->
            <div style="margin-bottom:14px;">
                <h4 style="font-size:13px; margin-bottom:6px; color:rgba(255,255,255,0.7);"><i class="fa-solid fa-circle-info" style="margin-right:4px;"></i> Metadata & Configuration Parameters</h4>
                <table class="inspector-table" style="font-size:11px; margin-bottom:0;">
                    <thead><tr><th>Config Key</th><th>Value</th></tr></thead>
                    <tbody>${metaRows}</tbody>
                </table>
            </div>
            
            <!-- Logs Terminal -->
            <div>
                <h4 style="font-size:13px; margin-bottom:6px; color:rgba(255,255,255,0.7);"><i class="fa-solid fa-terminal" style="margin-right:4px;"></i> Stage-Specific Execution Log</h4>
                <div style="background: rgba(0, 0, 0, 0.45); border-radius: 6px; padding: 12px; font-family: monospace; max-height: 180px; overflow-y: auto; font-size: 11px; border: 1px solid rgba(255,255,255,0.08); line-height: 1.5; color: #ccc;">
                    ${logLinesHtml}
                </div>
            </div>
        `;
    }
    
    titleEl.textContent = stageTitle;
    subtitleEl.textContent = subtitle;
    iconEl.innerHTML = `<i class="${iconClass}"></i>`;
    metaComponent.textContent = componentName;
    metaStatus.textContent = statusText;
    metaStatus.className = statusClass;
    metaQuality.textContent = qualityText;
    metaType.textContent = typeText;
    previewContainer.innerHTML = dataPreviewHtml;
    
    modal.style.display = 'flex';
}


