// Session token issued by /api/v1/auth/login; the backend derives the account from it
function getAuthToken() {
    // "Remember me" keeps the session in localStorage; otherwise it lives only for this browser session
    return localStorage.getItem('controlai_token') || sessionStorage.getItem('controlai_token');
}

function storeAuthToken(token, remember) {
    localStorage.removeItem('controlai_token');
    sessionStorage.removeItem('controlai_token');
    (remember ? localStorage : sessionStorage).setItem('controlai_token', token);
}

function isApiUrl(url) {
    const path = typeof url === 'string' ? url : (url && url.url) || '';
    return path.startsWith('/api/v1/') || path.startsWith(`${window.location.origin}/api/v1/`);
}

// Appends ?token= to API links opened outside fetch (downloads, new tabs, chat links)
function withAuthToken(url) {
    const token = getAuthToken();
    if (!token || typeof url !== 'string' || !isApiUrl(url) || /[?&]token=/.test(url)) return url;
    return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
}

function handleSessionExpired() {
    if (localStorage.getItem('isLoggedIn') !== 'true') return;
    localStorage.setItem('isLoggedIn', 'false');
    localStorage.removeItem('controlai_token');
    sessionStorage.removeItem('controlai_token');
    if (typeof showToast === 'function') showToast('error', 'Your session has expired. Please sign in again.');
    setTimeout(() => window.location.reload(), 1200);
}

// Hijack window.fetch to attach the session token to every API request
const originalFetch = window.fetch;
window.fetch = function(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    const token = getAuthToken();
    if (token && isApiUrl(url)) {
        if (options.headers instanceof Headers) {
            options.headers.set('Authorization', `Bearer ${token}`);
        } else if (Array.isArray(options.headers)) {
            options.headers.push(['Authorization', `Bearer ${token}`]);
        } else {
            options.headers['Authorization'] = `Bearer ${token}`;
        }
    }
    return originalFetch(url, options).then((response) => {
        const path = typeof url === 'string' ? url : (url && url.url) || '';
        if (response.status === 401 && isApiUrl(url) && !path.includes('/api/v1/auth/')) {
            handleSessionExpired();
        }
        return response;
    });
};

const originalWindowOpen = window.open.bind(window);
window.open = function(url, ...rest) {
    return originalWindowOpen(withAuthToken(url), ...rest);
};

// Plain <a href="/api/v1/..."> links (e.g. download links rendered in chat answers) need the token too
document.addEventListener('click', (e) => {
    const link = e.target.closest && e.target.closest('a[href]');
    if (!link) return;
    const href = link.getAttribute('href');
    if (href && isApiUrl(href)) link.setAttribute('href', withAuthToken(href));
}, true);

function parseUTCDate(dateStr) {
    if (!dateStr) return null;
    if (dateStr instanceof Date) return dateStr;
    if (typeof dateStr === 'string' && dateStr.includes('T') && !dateStr.endsWith('Z') && !dateStr.includes('+')) {
        if (!/[-+]\d{2}:\d{2}$/.test(dateStr)) {
            return new Date(dateStr + 'Z');
        }
    }
    return new Date(dateStr);
}

// App Shell: sidebar navigation + topbar (Dashboard/Pipeline view switching,
// sidebar shortcuts forwarded to their existing drawer/modal toggle buttons)
function initAppShell() {
    const sidebar = document.getElementById('app-sidebar');
    const collapseBtn = document.getElementById('btn-sidebar-collapse');
    if (collapseBtn && sidebar) {
        collapseBtn.addEventListener('click', () => {
            sidebar.classList.toggle('collapsed');
            const icon = collapseBtn.querySelector('i');
            if (icon) {
                icon.classList.toggle('fa-angles-left');
                icon.classList.toggle('fa-angles-right');
            }
        });
    }

    const topbarTitle = document.getElementById('app-topbar-title');
    const topbarCrumb = document.getElementById('app-topbar-crumb');
    const viewMeta = {
        'dashboard-view': { title: 'Dashboard', crumb: 'Overview & recent activity' },
        'pipeline-monitor-page': { title: 'Pipeline', crumb: 'Real-Time Ingestion Data Flow' },
        'history-view': { title: 'History', crumb: 'Every pipeline run and its results' },
        'reports-view': { title: 'Reports', crumb: 'Generated PDF, Word, Markdown & JSON reports' },
        'logs-view': { title: 'Logs', crumb: 'Full process log of each run' },
        'storage-view': { title: 'Storage', crumb: 'Raw uploads, cleaned data, reports, logs & exports' },
        'powerbi-view': { title: 'Power BI', crumb: 'Star-schema dataset exports & DAX measures' }
    };
    const viewLoaders = {
        'history-view': () => window.loadHistoryView && window.loadHistoryView(),
        'reports-view': () => window.loadReportsView && window.loadReportsView(),
        'logs-view': () => window.loadLogsView && window.loadLogsView(),
        'storage-view': () => loadExplorerFiles(),
        'powerbi-view': () => window.loadPowerBIView && window.loadPowerBIView()
    };

    function activateView(viewId) {
        // The live log console belongs to the Pipeline page
        if (viewId !== 'pipeline-monitor-page') {
            const consoleDrawer = document.getElementById('console-drawer');
            if (consoleDrawer) consoleDrawer.classList.remove('active');
            const logsBtn = document.getElementById('btn-toggle-logs');
            if (logsBtn) logsBtn.classList.remove('active');
        }
        document.querySelectorAll('.app-view').forEach(v => v.classList.remove('active'));
        const target = document.getElementById(viewId);
        if (target) target.classList.add('active');

        document.querySelectorAll('.app-nav-item[data-view]').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-view') === viewId);
        });

        const meta = viewMeta[viewId];
        if (meta) {
            if (topbarTitle) topbarTitle.textContent = meta.title;
            if (topbarCrumb) topbarCrumb.textContent = meta.crumb;
        }

        if (viewId === 'dashboard-view' && typeof loadDashboardStats === 'function') {
            loadDashboardStats();
        }
        if (viewLoaders[viewId]) viewLoaders[viewId]();
        if (viewId === 'pipeline-monitor-page') {
            setTimeout(() => {
                if (typeof updateMonitorPaths === 'function') updateMonitorPaths();
            }, 50);
        }
    }

    window.activateView = activateView;
    document.querySelectorAll('.app-nav-item[data-view]').forEach(btn => {
        btn.addEventListener('click', () => activateView(btn.getAttribute('data-view')));
    });

    document.querySelectorAll('.app-nav-item[data-forward]').forEach(btn => {
        btn.addEventListener('click', () => {
            const forwardEl = document.getElementById(btn.getAttribute('data-forward'));
            if (forwardEl) forwardEl.click();
        });
    });

    const navIngestion = document.getElementById('nav-ingestion');
    if (navIngestion) {
        navIngestion.addEventListener('click', () => {
            activateView('pipeline-monitor-page');
            const batchTab = document.getElementById('tab-mode-batch');
            if (batchTab) batchTab.click();
        });
    }

    const notifBtn = document.getElementById('btn-topbar-notifications');
    if (notifBtn) {
        notifBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.toggleNotifications) window.toggleNotifications();
        });
    }
}

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
    chatHistory: [],
    ingestMode: 'batch', // 'batch' | 'realtime'
    streamBatchSize: 30,
    streamCycle: 0,
    streamIntervalId: null,
    isStreaming: false
};

// Real-Time & Batch Ingestion Mode Switcher
window.switchIngestMode = function(mode) {
    state.ingestMode = mode;
    const tabBatch = document.getElementById('tab-mode-batch');
    const tabRealtime = document.getElementById('tab-mode-realtime');
    const tabUrl = document.getElementById('tab-mode-url');
    const dropZone = document.getElementById('file-drop-zone');
    const urlPanel = document.getElementById('url-ingest-panel');
    const streamPanel = document.getElementById('realtime-stream-panel');
    const realtimePill = document.getElementById('realtime-header-pill');

    if (mode !== 'realtime' && state.isStreaming) window.stopRealtimeStreamRunner();
    if (tabBatch) tabBatch.classList.toggle('active', mode === 'batch');
    if (tabUrl) tabUrl.classList.toggle('active', mode === 'url');
    if (tabRealtime) tabRealtime.classList.toggle('active', mode === 'realtime');
    if (dropZone) dropZone.style.display = mode === 'batch' ? 'block' : 'none';
    if (urlPanel) urlPanel.style.display = mode === 'url' ? 'flex' : 'none';
    if (streamPanel) streamPanel.style.display = mode === 'realtime' ? 'flex' : 'none';
    if (realtimePill) realtimePill.style.display = mode === 'realtime' ? 'inline-flex' : 'none';
    updateRunButtonLabel();
};

function updateRunButtonLabel() {
    const runBtn = document.getElementById('btn-run-pipeline');
    if (!runBtn) return;
    runBtn.classList.toggle('btn-realtime-glow', state.ingestMode === 'realtime');
    if (state.ingestMode === 'realtime') {
        runBtn.innerHTML = state.isStreaming
            ? '<i class="fa-solid fa-stop"></i> Stop Streaming'
            : '<i class="fa-solid fa-satellite-dish"></i> Start Streaming';
    } else if (state.ingestMode === 'url') {
        runBtn.innerHTML = '<i class="fa-solid fa-link"></i> Fetch URL & Run Data Flow';
    } else {
        runBtn.innerHTML = '<i class="fa-solid fa-play"></i> Run Data Flow';
    }
}

window.setStreamBatchSize = function(size) {
    state.streamBatchSize = size;
    const sizeLabel = document.getElementById('stream-size-label');
    if (sizeLabel) sizeLabel.textContent = `${size} rows`;
    
    const chips = document.querySelectorAll('.stream-size-chip');
    chips.forEach(chip => {
        if (parseInt(chip.getAttribute('data-size'), 10) === size) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });
};


// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
    initAppShell();
    initAuth();
    initUserProfileManager();
    initSettingsPage();
    initDrawers();
    initDragAndDrop();
    initPipelineControls();
    initChat();
    initChatbotToggle();
    
    // Initial data load
    loadDashboardStats();
    loadLatestRun();
    
    // Initialize permanent Data Flow Pipeline
    setTimeout(() => {
        setupMonitorSvg();
        updateMonitorPaths();
        initGamificationCanvas();
    }, 200);
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
        // Sessions from before token auth have no token and must sign in again
        const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true' && !!getAuthToken();
        if (isLoggedIn) {
            loginScreen.classList.add('fade-out');
            mainApp.classList.remove('app-hidden');
            setTimeout(() => {
                setupMonitorSvg();
                updateMonitorPaths();
                initGamificationCanvas();
            }, 300);
        } else {
            loginScreen.classList.remove('fade-out');
            mainApp.classList.add('app-hidden');
        }
    };
    checkSession();

    // Sign In / Sign Up Toggle Logic
    const toggleSignupLink = document.getElementById('link-toggle-signup');
    const signupConfirmGroup = document.getElementById('signup-confirm-group');
    const loginRememberRow = document.getElementById('login-remember-row');
    const linkForgotPassword = document.getElementById('link-forgot-password');
    const loginHeaderTitle = document.getElementById('login-header-title');
    const toggleSignupWrapper = document.getElementById('toggle-signup-wrapper');
    const loginUsername = document.getElementById('login-username');
    const loginPassword = document.getElementById('login-password');
    const signupConfirmPassword = document.getElementById('signup-confirm-password');

    let isSignUp = false;

    if (toggleSignupLink) {
        toggleSignupLink.addEventListener('click', (e) => {
            e.preventDefault();
            isSignUp = !isSignUp;
            if (isSignUp) {
                loginHeaderTitle.textContent = 'Sign up';
                signupConfirmGroup.style.display = 'flex';
                signupConfirmPassword.setAttribute('required', 'required');
                loginRememberRow.style.display = 'none';
                linkForgotPassword.style.display = 'none';
                loginBtnText.textContent = 'Sign up';
                toggleSignupWrapper.innerHTML = 'Already have an account? <a href="#" id="link-toggle-signup">Sign in</a>';
            } else {
                loginHeaderTitle.textContent = 'Sign in';
                signupConfirmGroup.style.display = 'none';
                signupConfirmPassword.removeAttribute('required');
                loginRememberRow.style.display = 'flex';
                linkForgotPassword.style.display = 'inline-block';
                loginBtnText.textContent = 'Sign in';
                toggleSignupWrapper.innerHTML = "Don't have an account? <a href=\"#\" id=\"link-toggle-signup\">Sign up</a>";
            }
            // Re-bind the toggle event listener since the innerHTML overwrite destroys it
            const newToggleLink = document.getElementById('link-toggle-signup');
            if (newToggleLink) {
                newToggleLink.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    toggleSignupLink.click();
                });
            }
        });
    }

    // 2. Authentication submission
    loginForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const user = loginUsername.value.trim();
        const pass = loginPassword.value.trim();

        if (user === '' || pass === '') {
            showToast('error', 'Please fill in all required fields.');
            return;
        }

        if (isSignUp) {
            const confirmPass = signupConfirmPassword.value.trim();
            if (pass !== confirmPass) {
                showToast('error', 'Passwords do not match!');
                signupConfirmPassword.focus();
                return;
            }

            loginBtnText.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating account...';
            
            fetch('/api/v1/auth/signup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: user, password: pass })
            })
            .then(async (response) => {
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Registration failed');
                }
                return response.json();
            })
            .then(data => {
                showToast('success', 'Account created successfully! Please sign in.');
                // Revert to sign in state
                if (toggleSignupLink) toggleSignupLink.click();
                loginUsername.value = user;
                loginPassword.value = '';
                loginPassword.focus();
            })
            .catch(err => {
                loginBtnText.textContent = 'Sign up';
                showToast('error', err.message || 'Registration failed.');
            });

        } else {
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
                const rememberEl = document.getElementById('login-remember');
                storeAuthToken(data.token, rememberEl ? rememberEl.checked : true);

                let displayName = 'System Administrator';
                let email = user;
                
                if (data && data.user) {
                    if (data.user.username) {
                        email = data.user.username;
                        displayName = email.split('@')[0];
                        // Capitalize first letter
                        displayName = displayName.charAt(0).toUpperCase() + displayName.slice(1);
                    }
                }
                
                localStorage.setItem('controlai_username', displayName);
                localStorage.setItem('controlai_email', email);
                localStorage.removeItem('controlai_avatar'); // default avatar
                
                showToast('success', `Access granted! Welcome, ${displayName}.`);
                
                // Transition views
                loginScreen.classList.add('fade-out');
                mainApp.classList.remove('app-hidden');
                
                // Clear inputs
                loginForm.reset();
                loginBtnText.textContent = 'Sign in';
                
                // Trigger login success event for profile manager
                window.dispatchEvent(new Event('controlai_login_success'));

                // Reload data for the logged-in user
                loadDashboardStats();
                loadLatestRun();

                // Draw graph components
            })
            .catch(err => {
                loginBtnText.textContent = 'Sign in';
                showToast('error', err.message || 'Authentication failed. Please check inputs.');
            });
        }
    });

    // Forgot Password Wizards Flow
    const forgotLink = document.getElementById('link-forgot-password');
    const forgotContainer = document.getElementById('forgot-container');
    const signinContainer = document.getElementById('signin-container');
    const btnForgotBack = document.getElementById('btn-forgot-back');

    const forgotStepEmail = document.getElementById('forgot-step-email');
    const forgotStepCode = document.getElementById('forgot-step-code');
    const forgotStepPassword = document.getElementById('forgot-step-password');

    const btnForgotSend = document.getElementById('btn-forgot-send');
    const btnForgotVerify = document.getElementById('btn-forgot-verify');
    const btnForgotReset = document.getElementById('btn-forgot-reset');

    const inputForgotEmail = document.getElementById('forgot-email');
    const inputForgotCode = document.getElementById('forgot-code');
    const inputForgotNewPass = document.getElementById('forgot-new-password');
    const inputForgotConfirmPass = document.getElementById('forgot-confirm-password');
    const forgotHeaderTitle = document.getElementById('forgot-header-title');
    const forgotHeaderSubtitle = document.getElementById('forgot-header-subtitle');

    if (forgotLink && forgotContainer && signinContainer) {
        forgotLink.addEventListener('click', (e) => {
            e.preventDefault();
            signinContainer.style.display = 'none';
            forgotContainer.style.display = 'flex';
            
            // Reset forgot wizard to step 1
            forgotStepEmail.style.display = 'block';
            forgotStepCode.style.display = 'none';
            forgotStepPassword.style.display = 'none';
            forgotHeaderTitle.textContent = 'Forgot Password';
            forgotHeaderSubtitle.textContent = 'Enter your email to request a verification code.';
            inputForgotEmail.value = loginUsername.value.trim();
        });
    }

    if (btnForgotBack && signinContainer && forgotContainer) {
        btnForgotBack.addEventListener('click', (e) => {
            e.preventDefault();
            forgotContainer.style.display = 'none';
            signinContainer.style.display = 'flex';
        });
    }

    // Step 1: Send Code
    if (btnForgotSend) {
        btnForgotSend.addEventListener('click', () => {
            const email = inputForgotEmail.value.trim();
            if (!email) {
                showToast('error', 'Please enter your email address.');
                inputForgotEmail.focus();
                return;
            }

            btnForgotSend.innerHTML = '<span><i class="fa-solid fa-spinner fa-spin"></i> Sending...</span>';
            btnForgotSend.disabled = true;

            fetch('/api/v1/auth/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email })
            })
            .then(async (res) => {
                if (!res.ok) {
                    const errorData = await res.json();
                    throw new Error(errorData.detail || 'Email verification request failed.');
                }
                return res.json();
            })
            .then(data => {
                // Email delivery is not configured, so the server returns the code; it is filled in for you
                showToast('info', `Verification code: ${data.demo_code} (email delivery is not configured, so it has been filled in).`);

                // Transition step
                forgotStepEmail.style.display = 'none';
                forgotStepCode.style.display = 'block';
                forgotHeaderTitle.textContent = 'Verify Code';
                forgotHeaderSubtitle.textContent = `Enter the 6-digit code for ${email}`;
                inputForgotCode.value = data.demo_code || '';
                inputForgotCode.focus();
            })
            .catch(err => {
                showToast('error', err.message || 'No account associated with this email.');
            })
            .finally(() => {
                btnForgotSend.innerHTML = '<span>Send Verification Code</span>';
                btnForgotSend.disabled = false;
            });
        });
    }

    // Step 2: Verify Code
    if (btnForgotVerify) {
        btnForgotVerify.addEventListener('click', () => {
            const email = inputForgotEmail.value.trim();
            const code = inputForgotCode.value.trim();
            if (!code || code.length !== 6) {
                showToast('error', 'Please enter a valid 6-digit verification code.');
                inputForgotCode.focus();
                return;
            }

            btnForgotVerify.innerHTML = '<span><i class="fa-solid fa-spinner fa-spin"></i> Verifying...</span>';
            btnForgotVerify.disabled = true;

            fetch('/api/v1/auth/verify-reset-code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email, code: code })
            })
            .then(async (res) => {
                if (!res.ok) {
                    const errorData = await res.json();
                    throw new Error(errorData.detail || 'Invalid verification code.');
                }
                return res.json();
            })
            .then(data => {
                showToast('success', 'Verification successful! Set a new password.');
                forgotStepCode.style.display = 'none';
                forgotStepPassword.style.display = 'block';
                forgotHeaderTitle.textContent = 'New Password';
                forgotHeaderSubtitle.textContent = 'Choose a strong, new password for your account.';
                inputForgotNewPass.value = '';
                inputForgotConfirmPass.value = '';
                inputForgotNewPass.focus();
            })
            .catch(err => {
                showToast('error', err.message || 'Invalid code. Please try again.');
            })
            .finally(() => {
                btnForgotVerify.innerHTML = '<span>Verify Code</span>';
                btnForgotVerify.disabled = false;
            });
        });
    }

    // Step 3: Reset Password
    if (btnForgotReset) {
        btnForgotReset.addEventListener('click', () => {
            const email = inputForgotEmail.value.trim();
            const code = inputForgotCode.value.trim();
            const newPass = inputForgotNewPass.value.trim();
            const confirmPass = inputForgotConfirmPass.value.trim();

            if (!newPass || newPass.length < 4) {
                showToast('error', 'New password must be at least 4 characters long.');
                inputForgotNewPass.focus();
                return;
            }

            if (newPass !== confirmPass) {
                showToast('error', 'Passwords do not match!');
                inputForgotConfirmPass.focus();
                return;
            }

            btnForgotReset.innerHTML = '<span><i class="fa-solid fa-spinner fa-spin"></i> Updating...</span>';
            btnForgotReset.disabled = true;

            fetch('/api/v1/auth/reset-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email, code: code, new_password: newPass })
            })
            .then(async (res) => {
                if (!res.ok) {
                    const errorData = await res.json();
                    throw new Error(errorData.detail || 'Failed to reset password.');
                }
                return res.json();
            })
            .then(data => {
                showToast('success', 'Password reset successfully! Log in to continue.');
                forgotContainer.style.display = 'none';
                signinContainer.style.display = 'flex';
                loginUsername.value = email;
                loginPassword.value = '';
                loginPassword.focus();
            })
            .catch(err => {
                showToast('error', err.message || 'Failed to update password.');
            })
            .finally(() => {
                btnForgotReset.innerHTML = '<span>Update Password</span>';
                btnForgotReset.disabled = false;
            });
        });
    }

    // Simulated Social Logins & OAuth Modal Flow
    const oauthModal = document.getElementById('oauth-modal');
    const btnCloseOauth = document.getElementById('btn-close-oauth');
    const oauthProviderLogo = document.getElementById('oauth-provider-logo');
    const oauthTitle = document.getElementById('oauth-title');
    const oauthLoading = document.getElementById('oauth-loading');
    const oauthLoadingText = document.getElementById('oauth-loading-text');
    const oauthAccounts = document.getElementById('oauth-accounts');
    const oauthAccountList = document.getElementById('oauth-account-list');

    const socialProfiles = {
        google: {
            title: 'Sign in with Google',
            logoClass: 'google',
            logoHtml: '<i class="fa-brands fa-google"></i>',
            accounts: [
                { name: 'John Doe', email: 'john.doe@gmail.com', avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=60&q=80' },
                { name: 'Jane Smith', email: 'jane.smith@gmail.com', avatar: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=60&q=80' }
            ]
        },
        github: {
            title: 'Sign in with GitHub',
            logoClass: 'github',
            logoHtml: '<i class="fa-brands fa-github"></i>',
            accounts: [
                { name: 'octocat', email: 'octocat@github.com', avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=60&q=80' },
                { name: 'ai_coder', email: 'ai.coder@github.com', avatar: 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=60&q=80' }
            ]
        },
        facebook: {
            title: 'Log in with Facebook',
            logoClass: 'facebook',
            logoHtml: '<i class="fa-brands fa-facebook-f"></i>',
            accounts: [
                { name: 'Sarah Connor', email: 'sarah.c@facebook.com', avatar: 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=60&q=80' },
                { name: 'Mark Zuckerberg', email: 'zuck@meta.com', avatar: 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=60&q=80' }
            ]
        }
    };

    const openSocialOauth = (provider) => {
        const config = socialProfiles[provider];
        if (!config || !oauthModal) return;

        // Reset state
        oauthTitle.textContent = config.title;
        oauthProviderLogo.className = `oauth-provider-logo ${config.logoClass}`;
        oauthProviderLogo.innerHTML = config.logoHtml;
        oauthLoading.style.display = 'flex';
        oauthLoadingText.textContent = 'Connecting securely...';
        oauthAccounts.style.display = 'none';
        oauthModal.style.display = 'flex';

        // Stage 1: Load secure connection (simulated latency)
        setTimeout(() => {
            oauthLoading.style.display = 'none';
            oauthAccounts.style.display = 'block';

            // Generate profiles list
            oauthAccountList.innerHTML = config.accounts.map(acc => `
                <div class="oauth-account-card" onclick="triggerSocialAuth('${provider}', '${acc.name.replace(/'/g, "\\'")}', '${acc.email}', '${acc.avatar}')">
                    <div class="oauth-account-avatar">
                        <img src="${acc.avatar}" alt="${acc.name}">
                    </div>
                    <div class="oauth-account-info">
                        <span class="oauth-account-name">${acc.name}</span>
                        <span class="oauth-account-email">${acc.email}</span>
                    </div>
                </div>
            `).join('');
        }, 1200);
    };

    const closeSocialOauth = () => {
        if (oauthModal) oauthModal.style.display = 'none';
    };

    if (btnCloseOauth) btnCloseOauth.addEventListener('click', closeSocialOauth);
    if (oauthModal) {
        oauthModal.addEventListener('click', (e) => {
            if (e.target === oauthModal) closeSocialOauth();
        });
    }

    // Register social button click listeners
    const googleBtn = document.querySelector('.google-btn');
    const githubBtn = document.querySelector('.github-btn');
    const facebookBtn = document.querySelector('.facebook-btn');

    if (googleBtn) googleBtn.addEventListener('click', (e) => { e.preventDefault(); openSocialOauth('google'); });
    if (githubBtn) githubBtn.addEventListener('click', (e) => { e.preventDefault(); openSocialOauth('github'); });
    if (facebookBtn) facebookBtn.addEventListener('click', (e) => { e.preventDefault(); openSocialOauth('facebook'); });

    // Expose social callback handler to window
    window.triggerSocialAuth = function(provider, name, email, avatar) {
        oauthAccounts.style.display = 'none';
        oauthLoading.style.display = 'flex';
        oauthLoadingText.textContent = `Completing secure login with ${provider}...`;

        fetch('/api/v1/auth/social-login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: provider, email: email, name: name })
        })
        .then(async (res) => {
            if (!res.ok) {
                const errorData = await res.json();
                throw new Error(errorData.detail || 'OAuth validation failed.');
            }
            return res.json();
        })
        .then(data => {
            // Save state
            localStorage.setItem('isLoggedIn', 'true');
            storeAuthToken(data.token, true);
            localStorage.setItem('controlai_username', name);
            localStorage.setItem('controlai_email', email);
            localStorage.setItem('controlai_avatar', avatar);

            showToast('success', `Logged in via ${provider.charAt(0).toUpperCase() + provider.slice(1)}! Welcome, ${name}.`);

            // Transition main views
            closeSocialOauth();
            loginScreen.classList.add('fade-out');
            mainApp.classList.remove('app-hidden');

            // Trigger profile UI updates and SVG redraw
            window.dispatchEvent(new Event('controlai_login_success'));
        })
        .catch(err => {
            showToast('error', err.message || 'OAuth authentication failed.');
            oauthAccounts.style.display = 'block';
            oauthLoading.style.display = 'none';
        });
    };

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

    // Logout account
    logoutBtn.addEventListener('click', (e) => {
        e.preventDefault();
        profileDropdown.classList.remove('active');
        
        localStorage.setItem('isLoggedIn', 'false');
        localStorage.removeItem('controlai_token');
        sessionStorage.removeItem('controlai_token');
        localStorage.removeItem('controlai_username');
        localStorage.removeItem('controlai_email');
        localStorage.removeItem('controlai_avatar');
        
        // Clear cached or memory lists
        state.currentBatchId = null;
        state.chatHistory = [];
        const chatWindow = document.getElementById('chat-messages-container');
        if (chatWindow) chatWindow.innerHTML = '';
        
        // Refresh UI state
        if (window.updateProfileUI) window.updateProfileUI();

        // Reload data (will query under anonymous/empty state)
        loadDashboardStats();
        loadLatestRun();

        showToast('info', 'Logged out successfully.');

        // Revert views
        mainApp.classList.add('app-hidden');
        loginScreen.classList.remove('fade-out');
    });
}


// Drawers & Manual Paste Panel Toggles
// Pipeline toolbar: live log console toggle, plus shortcuts to the Storage and Power BI pages
function initDrawers() {
    const consoleDrawer = document.getElementById('console-drawer');
    const btnToggleLogs = document.getElementById('btn-toggle-logs');

    const closeAllMenus = () => {
        if (consoleDrawer) consoleDrawer.classList.remove('active');
        if (btnToggleLogs) btnToggleLogs.classList.remove('active');
        const settingsOverlay = document.getElementById('settings-page-overlay');
        if (settingsOverlay) {
            settingsOverlay.style.display = 'none';
            settingsOverlay.classList.remove('active');
        }
    };
    window.closeAllMenus = closeAllMenus;

    const goTo = (viewId) => () => {
        closeAllMenus();
        if (window.activateView) window.activateView(viewId);
    };
    const btnTogglePowerBI = document.getElementById('btn-toggle-powerbi');
    if (btnTogglePowerBI) btnTogglePowerBI.addEventListener('click', goTo('powerbi-view'));
    const btnToggleExplorer = document.getElementById('btn-toggle-explorer');
    if (btnToggleExplorer) btnToggleExplorer.addEventListener('click', goTo('storage-view'));

    if (btnToggleLogs && consoleDrawer) {
        btnToggleLogs.addEventListener('click', () => {
            const open = !consoleDrawer.classList.contains('active');
            consoleDrawer.classList.toggle('active', open);
            btnToggleLogs.classList.toggle('active', open);
        });
    }
    const btnCloseLogs = document.getElementById('btn-close-logs');
    if (btnCloseLogs) btnCloseLogs.addEventListener('click', () => {
        if (consoleDrawer) consoleDrawer.classList.remove('active');
        if (btnToggleLogs) btnToggleLogs.classList.remove('active');
    });
}





// // Drag & Drop Ingestion
function initDragAndDrop() {
    const dropZone = document.getElementById('file-drop-zone');
    const fileInput = document.getElementById('file-input');
    const fileBanner = document.getElementById('file-banner');
    const fileNameEl = document.getElementById('selected-file-name');
    const fileSizeEl = document.getElementById('selected-file-size');
    const clearFileBtn = document.getElementById('btn-clear-file');
    
    if (dropZone && fileInput) {
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
    }
    
    if (clearFileBtn) {
        clearFileBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            state.selectedFile = null;
            if (fileInput) fileInput.value = '';
            if (fileBanner) fileBanner.style.display = 'none';
            if (dropZone) {
                const dropContent = dropZone.querySelector('.upload-drop-content') || dropZone.querySelector('.node-card-header');
                if (dropContent) dropContent.style.display = 'block';
            }
            showToast('info', 'File cleared.');
        });
    }

    // Allow clicking or dragging directly onto the Raw Input node
    const mnodeRaw = document.getElementById('mnode-raw');
    if (mnodeRaw && fileInput) {
        mnodeRaw.addEventListener('click', (e) => {
            if (e.target.closest('a')) return;
            fileInput.click();
        });
        mnodeRaw.addEventListener('dragover', (e) => {
            e.preventDefault();
            mnodeRaw.classList.add('dragover');
        });
        mnodeRaw.addEventListener('dragleave', () => {
            mnodeRaw.classList.remove('dragover');
        });
        mnodeRaw.addEventListener('drop', (e) => {
            e.preventDefault();
            mnodeRaw.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                handleFileSelection(e.dataTransfer.files[0]);
            }
        });
    }
    
    function handleFileSelection(file) {
        state.selectedFile = file;
        if (fileNameEl) fileNameEl.textContent = file.name;
        
        let sizeStr = `${(file.size / 1024).toFixed(1)} KB`;
        if (file.size > 1024 * 1024) {
            sizeStr = `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
        }
        if (fileSizeEl) fileSizeEl.textContent = sizeStr;
        
        if (dropZone) {
            const dropContent = dropZone.querySelector('.upload-drop-content') || dropZone.querySelector('.node-card-header');
            if (dropContent) dropContent.style.display = 'none';
        }
        if (fileBanner) fileBanner.style.display = 'flex';
        
        const rawFileEl = document.getElementById('mnode-raw-file');
        if (rawFileEl) rawFileEl.textContent = file.name;
        
        showToast('info', `Loaded dataset: ${file.name}`);
    }
}

function osBasename(path) {
    return path.substring(path.lastIndexOf('/') + 1).substring(path.lastIndexOf('\\') + 1);
}

// Pipeline controls trigger
function initPipelineControls() {
    const runBtn = document.getElementById('btn-run-pipeline');
    if (!runBtn) return;
    
    runBtn.addEventListener('click', () => {
        if (state.ingestMode === 'realtime') {
            if (state.isStreaming) {
                window.stopRealtimeStreamRunner();
            } else {
                const intervalSel = document.getElementById('stream-interval-select');
                window.startRealtimeStreamRunner(intervalSel ? parseInt(intervalSel.value, 10) : 30000);
            }
            return;
        }
        runIngestionCycle();
    });
}

// One ingestion: upload (file / URL / stream cycle) then start and monitor the pipeline
async function runIngestionCycle() {
        const urlEl = document.getElementById('ingest-url-input');
        const urlVal = (state.ingestMode === 'url' && urlEl) ? urlEl.value.trim() : '';
        let uploadResult = null;
        if (state.ingestMode === 'url' && !urlVal) {
            showToast('error', 'Enter a direct link to a data file first.');
            return;
        }
        if (state.ingestMode === 'batch' && !state.selectedFile) {
            showToast('error', 'Choose a file to ingest first.');
            return;
        }
        // Clear the previous run's result while the new file uploads
        const statusEl = document.getElementById('monitor-overall-status');
        if (statusEl) statusEl.textContent = 'Uploading...';
        const statusPill = document.getElementById('monitor-overall-status-pill');
        if (statusPill) statusPill.className = 'monitor-stat-pill processing';
                
        clearConsole();
        
        if (window.closeAllMenus) window.closeAllMenus();
        const conDrawer = document.getElementById('console-drawer');
        if (conDrawer) conDrawer.classList.add('active');
        const togLogs = document.getElementById('btn-toggle-logs');
        if (togLogs) togLogs.classList.add('active');

        if (urlVal) {
            writeConsoleLog('[System] Fetching file from remote URL...');
            try {
                const uploadRes = await fetch('/api/v1/upload/url', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: urlVal })
                });
                if (!uploadRes.ok) {
                    const err = await uploadRes.json();
                    writeConsoleLog(`[System Error] URL upload failed: ${err.detail || 'Unknown error'}`, 'text-red');
                    showToast('error', err.detail || 'URL ingestion failed.');
                    return;
                }
                uploadResult = await uploadRes.json();
            } catch (err) {
                writeConsoleLog(`[System Error] URL upload connection failed: ${err}`, 'text-red');
                showToast('error', 'Connection to URL upload failed.');
                return;
            }
        } else if (state.ingestMode === 'realtime') {
            const streamTypeSelect = document.getElementById('stream-type-select');
            const streamType = streamTypeSelect ? streamTypeSelect.value : 'live_url';
            const streamUrlEl = document.getElementById('stream-url-input');
            const streamUrl = streamUrlEl ? streamUrlEl.value.trim() : '';
            if (streamType === 'live_url' && !streamUrl) {
                showToast('error', 'Enter the feed URL to stream from.');
                window.stopRealtimeStreamRunner();
                return;
            }
            state.streamCycle = (state.streamCycle || 0) + 1;

            writeConsoleLog(streamType === 'live_url'
                ? `[Real-Time Stream] Cycle #${state.streamCycle}: pulling live snapshot from ${streamUrl}...`
                : `[Real-Time Stream] Cycle #${state.streamCycle}: simulator generating ${state.streamBatchSize || 30} ${streamType} records...`);
            
            const pulseDot = document.getElementById('stream-pulse-dot');
            const statusText = document.getElementById('stream-status-text');
            const cycleCounter = document.getElementById('stream-cycle-counter');
            
            if (pulseDot) pulseDot.classList.add('streaming');
            if (statusText) statusText.textContent = `Streaming ${streamType}...`;
            if (cycleCounter) cycleCounter.textContent = `Cycle #${state.streamCycle}`;
            
            uploadResult = await uploadRealtimeStream(streamType, state.streamBatchSize || 30, state.streamCycle, streamType === 'live_url' ? streamUrl : null);
        } else {
            if (!state.selectedFile) {
                showToast('error', 'Choose a file to ingest first.');
                return;
            }
            writeConsoleLog('[System] Ingesting local file upload...');
            uploadResult = await uploadFile(state.selectedFile);
        }
        
        if (!uploadResult) {
            writeConsoleLog('[System Error] Upload registration failed. Aborting pipeline.', 'text-red');
            showToast('error', 'Ingestion upload failed.');
            return;
        }
        
        const { file_path, batch_id } = uploadResult;
        state.currentBatchId = batch_id;
        const bBadge = document.getElementById('batch-badge-id');
        if (bBadge) bBadge.textContent = `Batch: ${batch_id}`;
        

        writeConsoleLog(`[Intake] Preserved original raw file at: ${file_path}`);
        writeConsoleLog(`[System] Initializing autonomous agents graph for pipeline: pipe_${batch_id}`);
        

        const startSuccess = await startPipeline(file_path, batch_id);
        if (startSuccess) {
            
            // Open full-screen pipeline monitor
            if (window.openPipelineMonitorOverlay) {
                window.openPipelineMonitorOverlay(batch_id, osBasename(file_path));
            }
            
            startPipelinePolling(`pipe_${batch_id}`);
        } else {
            showToast('error', 'Failed to start pipeline.');
        }
}

async function uploadRealtimeStream(streamType, recordCount, cycleIndex, streamUrl = null) {
    try {
        const response = await fetch('/api/v1/upload/realtime', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                stream_type: streamType,
                stream_url: streamUrl,
                record_count: recordCount,
                cycle_index: cycleIndex
            })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Real-time stream upload failed.');
        }
        return await response.json();
    } catch (e) {
        writeConsoleLog(`[Error] Real-time stream upload failed: ${e.message}`, 'text-red');
        return null;
    }
}

// Continuous Real-Time Streaming Cycle Runner
window.startRealtimeStreamRunner = function(intervalMs = 30000) {
    if (state.streamIntervalId) clearInterval(state.streamIntervalId);
    state.isStreaming = true;
    state.streamCycle = 0;
    updateRunButtonLabel();
    const pulseDot = document.getElementById('stream-pulse-dot');
    if (pulseDot) pulseDot.classList.add('streaming');
    showToast('success', `Streaming started: a new cycle every ${intervalMs / 1000}s`);

    runIngestionCycle();
    state.streamIntervalId = setInterval(() => {
        if (!state.isStreaming) {
            clearInterval(state.streamIntervalId);
            state.streamIntervalId = null;
            return;
        }
        // Skip a tick while the previous cycle's pipeline is still running
        if (state.pipelinePollingInterval) {
            writeConsoleLog('[Real-Time Stream] Previous cycle still running, waiting for the next interval.', 'text-yellow');
            return;
        }
        runIngestionCycle();
    }, intervalMs);
};

window.stopRealtimeStreamRunner = function() {
    const wasStreaming = state.isStreaming;
    state.isStreaming = false;
    if (state.streamIntervalId) {
        clearInterval(state.streamIntervalId);
        state.streamIntervalId = null;
    }
    const pulseDot = document.getElementById('stream-pulse-dot');
    const statusText = document.getElementById('stream-status-text');
    if (pulseDot) pulseDot.classList.remove('streaming');
    if (statusText) statusText.textContent = 'Stream Ingest: Standby';
    updateRunButtonLabel();
    if (wasStreaming) showToast('info', `Streaming stopped after ${state.streamCycle} cycle(s).`);
};


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

// Pipeline Polling Status: drives the monitor, console and notifications until the run finishes
function startPipelinePolling(pipelineId) {
    if (state.pipelinePollingInterval) clearInterval(state.pipelinePollingInterval);
    const stopPolling = () => {
        clearInterval(state.pipelinePollingInterval);
        state.pipelinePollingInterval = null;
    };

    state.pipelinePollingInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/v1/pipeline/status?pipeline_id=${pipelineId}`);
            if (response.status === 404) {
                stopPolling();
                writeConsoleLog('[System Error] This pipeline run no longer exists.', 'text-red');
                return;
            }
            if (!response.ok) return;
            const data = await response.json();
            state.currentPipelineData = data;
            updatePipelineMonitorUI(data);
            updateLogsConsole(data.logs);

            if (data.status === 'Success' || data.status === 'Passed with Warnings') {
                stopPolling();
                writeConsoleLog(`[System Success] Pipeline complete! Status: ${data.status}. Duration: ${(data.execution_time || 0).toFixed(2)}s`, 'text-green');
                showToast(data.status === 'Success' ? 'success' : 'info', `${data.filename || data.batch_id}: ${data.status}`);
                playAlertChime(true);
            } else if (data.status === 'Failed') {
                stopPolling();
                writeConsoleLog(`[System Failure] Pipeline execution aborted: ${data.error || 'see the process log for details'}`, 'text-red');
                showToast('error', `${data.filename || data.batch_id}: pipeline failed. ${data.error || ''}`);
                playAlertChime(false);
            } else {
                return;
            }
            // Run finished: refresh everything that depends on run results
            if (window.refreshNotifications) window.refreshNotifications();
            loadDashboardStats();
            loadChatBatchContexts();
            if (data.status !== 'Failed' && localStorage.getItem('pref_auto_ai') !== 'false') {
                fetchSelectedBatchInsights(state.currentBatchId);
            }
        } catch (e) {
            loggerError('polling', e);
        }
    }, 1500);
}

// Short success / failure chime when a run finishes (Preferences > Audio Alerts)
function playAlertChime(success) {
    if (localStorage.getItem('pref_audio_alerts') === 'false') return;
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();
        const notes = success ? [660, 880] : [440, 330];
        notes.forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0.08, ctx.currentTime + i * 0.15);
            gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.15 + 0.14);
            osc.connect(gain).connect(ctx.destination);
            osc.start(ctx.currentTime + i * 0.15);
            osc.stop(ctx.currentTime + i * 0.15 + 0.15);
        });
    } catch (e) { /* audio is optional */ }
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






function clearConsole() {
    document.getElementById('console-logs').innerHTML = '';
}

function writeConsoleLog(text, colorClass = '') {
    // Preferences > Console Log Level: WARN shows only warnings/errors
    if (localStorage.getItem('pref_log_level') === 'WARN' && !/text-(red|yellow)/.test(colorClass)) return;
    const consoleBody = document.getElementById('console-logs');
    const p = document.createElement('p');
    if (colorClass) p.className = colorClass;
    p.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
    consoleBody.appendChild(p);
    consoleBody.scrollTop = consoleBody.scrollHeight;
}

// Fetch insights details with a smooth fade animation
// Shows a finished (or running) batch on the Pipeline page: flow nodes, stats, console and chat context
async function fetchSelectedBatchInsights(batchId) {
    if (!batchId) return;
    state.currentBatchId = batchId;
    try {
        const res = await fetch(`/api/v1/pipeline/status?pipeline_id=pipe_${batchId}`);
        if (!res.ok) return;
        const data = await res.json();
        state.currentPipelineData = data;
        updatePipelineMonitorUI(data);
        updateLogsConsole(data.logs || []);
        const bBadge = document.getElementById('batch-badge-id');
        if (bBadge) bBadge.textContent = `Batch: ${batchId}`;
        const rawFile = document.getElementById('mnode-raw-file');
        if (rawFile && data.filename && !rawFile.querySelector('.node-card-links')) rawFile.textContent = data.filename;
        if (data.status === 'Running' && !state.pipelinePollingInterval) startPipelinePolling(`pipe_${batchId}`);
    } catch (e) {
        loggerError('fetchSelectedBatchInsights', e);
    }
    const chatSelect = document.getElementById('chat-batch-select');
    if (chatSelect) chatSelect.value = batchId;
    state.chatContextBatchId = batchId;
}

// Load Global Dashboard statistics
async function loadDashboardStats() {
    if (!getAuthToken()) return;
    try {
        const response = await fetch('/api/v1/dashboard/summary');
        if (!response.ok) return;
        const stats = await response.json();
        
        const elTotal = document.getElementById('stat-total-processed');
        if (elTotal) elTotal.textContent = (stats.total_rows_processed || 0).toLocaleString();
        const elSuccess = document.getElementById('stat-success-rate');
        if (elSuccess) elSuccess.textContent = `${stats.success_rate || 100}%`;
        const elRuntime = document.getElementById('stat-avg-runtime');
        if (elRuntime) elRuntime.textContent = `${(stats.processing_time_avg || 0).toFixed(1)}s`;
        const elFailed = document.getElementById('stat-failed-records');
        if (elFailed) elFailed.textContent = (stats.failed_records || 0).toLocaleString();
        
        // Also update monitor sidebar performance stats if present
        const monRows = document.getElementById('monitor-stat-rows');
        if (monRows && (monRows.textContent === '0' || !monRows.textContent) && stats.total_rows_processed) {
            monRows.textContent = stats.total_rows_processed.toLocaleString();
        }
        
        const tableBody = document.querySelector('#recent-runs-table tbody');
        if (tableBody) {
            tableBody.innerHTML = '';
            
            if (!stats.recent_runs || stats.recent_runs.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="5" class="text-center">No runs logged yet.</td></tr>';
            } else {
                stats.recent_runs.forEach(run => {
                    const tr = document.createElement('tr');
                    let badgeClass = 'success';
                    if (run.status === 'Failed') badgeClass = 'failed';
                    else if (run.status === 'Passed with Warnings') badgeClass = 'warning';
                    else if (run.status === 'Running') badgeClass = 'running';
                    
                    const startStr = run.start_time ? parseUTCDate(run.start_time).toLocaleString() : 'N/A';
                    const runtimeStr = run.execution_time ? `${run.execution_time.toFixed(1)}s` : '--';
                    
                    const runBatch = run.pipeline_id.replace('pipe_', '');
                    tr.innerHTML = `
                        <td><strong>${escapeHtml(run.filename || runBatch)}</strong><div class="text-secondary" style="font-size:10px;">${runBatch}</div></td>
                        <td>${startStr}</td>
                        <td>${runtimeStr}</td>
                        <td><span class="badge ${badgeClass}">${run.status}</span></td>
                        <td>
                            <button class="btn-refresh" style="padding: 2px 8px; font-size:10px;" onclick="openRunLog('${runBatch}')"><i class="fa-solid fa-code"></i> Logs</button>
                            <button class="btn-refresh" style="padding: 2px 8px; font-size:10px;" onclick="selectBatchDetail('${runBatch}')"><i class="fa-solid fa-eye"></i> Open</button>
                        </td>
                    `;
                    tableBody.appendChild(tr);
                });
            }
        }
        
        if (stats.recent_runs) {
            renderCharts(stats.recent_runs);
        }
    } catch (e) {
        loggerError('loadDashboardStats', e);
    }
}

window.selectBatchDetail = function(batchId) {
    if (window.closeAllMenus) window.closeAllMenus();
    if (window.activateView) window.activateView('pipeline-monitor-page');
    fetchSelectedBatchInsights(batchId);
};

function renderCharts(recentRuns) {
    const canvas = document.getElementById('executionHistoryChart');
    if (!canvas) return;
    const ctxHistory = canvas.getContext('2d');
    if (state.historyChart) state.historyChart.destroy();
    
    const labels = recentRuns.map(r => r.filename || r.pipeline_id.replace('pipe_', '')).reverse();
    const runtimes = recentRuns.map(r => r.execution_time || 0.0).reverse();
    
    state.historyChart = new Chart(ctxHistory, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Duration (s)',
                data: runtimes,
                borderColor: '#4f46e5',
                backgroundColor: 'rgba(79, 70, 229, 0.08)',
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
                    grid: { color: 'rgba(15, 23, 42, 0.06)' },
                    ticks: { color: '#8a8f9a', font: { family: 'Plus Jakarta Sans', size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(15, 23, 42, 0.06)' },
                    ticks: { color: '#8a8f9a', font: { family: 'Plus Jakarta Sans', size: 10 } }
                }
            }
        }
    });
}




function downloadDataFile(filePath) {
    const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
    window.open(`/api/v1/dashboard/download?file_path=${encodeURIComponent(filePath)}&email=${encodeURIComponent(email)}`, '_blank');
}

// PDF Reports List Operations
// After sign-in, show the most recent run on the Pipeline page
async function loadLatestRun() {
    if (!getAuthToken()) return;
    try {
        const response = await fetch('/api/v1/history?limit=20');
        if (!response.ok) return;
        const runs = await response.json();
        const latest = runs.find(r => r.status !== 'Not Run');
        if (latest) fetchSelectedBatchInsights(state.currentBatchId || latest.batch_id);
    } catch (e) {
        loggerError('loadLatestRun', e);
    }
}

window.downloadReport = function(batchId, format) {
    // Fall back to the batch currently shown when a caller has no id (e.g. before status data arrives)
    const id = (batchId && batchId !== 'undefined' && batchId !== 'null') ? batchId : state.currentBatchId;
    if (!id) {
        showToast('error', 'No processed batch selected yet. Run a pipeline first.');
        return;
    }
    window.open(`/api/v1/reports/download/${encodeURIComponent(id)}?format=${format}`, '_blank');
};

// AI Assistant Chat operations
async function loadChatBatchContexts() {
    if (!getAuthToken()) return;
    try {
        const response = await fetch('/api/v1/reports/folders');
        if (!response.ok) return;
        const folders = await response.json();
        
        const selectEl = document.getElementById('chat-batch-select');
        selectEl.innerHTML = '<option value="">No Batch Context</option>';
        
        folders.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.batch_id;
            opt.textContent = `📁 ${item.folder_name || item.dataset_name} (${item.batch_id})`;
            if (state.chatContextBatchId === item.batch_id) {
                opt.selected = true;
            }
            selectEl.appendChild(opt);
        });
        
        renderChatSuggestions();
    } catch (e) {
        loggerError('loadChatBatchContexts', e);
    }
}

function renderChatSuggestions() {
    const container = document.getElementById('chat-messages-container');
    if (!container || container.children.length > 0) return;
    
    const suggestionsDiv = document.createElement('div');
    suggestionsDiv.className = 'chat-suggestions-wrapper';
    suggestionsDiv.style = 'padding: 12px; margin: 10px 0; background: rgba(30, 41, 59, 0.4); border-radius: 8px; border: 1px dashed rgba(59, 130, 246, 0.3);';
    suggestionsDiv.innerHTML = `
        <p style="font-size: 11px; color: #94a3b8; margin: 0 0 8px 0; font-weight: 600;">
            <i class="fa-solid fa-wand-magic-sparkles text-blue"></i> Quick Questions:
        </p>
        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
            <button class="chat-chip" onclick="quickAskChat('Why were records rejected during validation?')">🔍 Root Causes & Rejections</button>
            <button class="chat-chip" onclick="quickAskChat('What transformations were applied to this dataset?')">🧹 Transformations Applied</button>
            <button class="chat-chip" onclick="quickAskChat('Explain the columns and schema data types')">📊 Schema & Data Types</button>
            <button class="chat-chip" onclick="quickAskChat('Generate SQL queries for staging and production tables')">💻 SQL Queries</button>
            <button class="chat-chip" onclick="quickAskChat('Provide executive summary and recommendations')">📈 Executive Summary</button>
        </div>
    `;
    container.appendChild(suggestionsDiv);
}

window.quickAskChat = function(query) {
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
        chatInput.value = query;
        const sendBtn = document.getElementById('chat-send-btn');
        if (sendBtn) sendBtn.click();
    }
};

document.getElementById('chat-batch-select').addEventListener('change', (e) => {
    state.chatContextBatchId = e.target.value;
    state.chatHistory = [];
    document.getElementById('chat-messages-container').innerHTML = '';
    renderChatSuggestions();
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
                    history: state.chatHistory.slice(-10)
                })
            });
            
            removeThinking();
            
            if (!response.ok) throw new Error('Chat failed');
            const data = await response.json();
            
            appendChatMessage('assistant', data.response);
            
            // Auto-trigger browser download for the first download link found in the response
            // only when the user's prompt explicitly requests downloading and doesn't negate it
            const hasDownloadWord = /\b(download|save)\b/i.test(message);
            const hasNegation = /\b(don'?t|no|without|never|stop|not)\b/i.test(message);
            const isDownloadRequested = hasDownloadWord && !hasNegation;
            if (isDownloadRequested) {
                // Only when exactly one downloadable item was returned (e.g. "download the pdf report")
                const apiLinks = [...data.response.matchAll(/\]\((\/api\/v1\/[^\)\s]+)\)/g)].map(m => m[1]);
                if (apiLinks.length === 1) {
                    const downloadUrl = withAuthToken(apiLinks[0]);
                    const tempLink = document.createElement('a');
                    tempLink.href = downloadUrl;
                    tempLink.setAttribute('download', '');
                    document.body.appendChild(tempLink);
                    tempLink.click();
                    document.body.removeChild(tempLink);
                }
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

// Encodes a value as a JavaScript string literal that is safe inside an HTML attribute
// (e.g. onclick="fn(${jsArg(path)})"), so Windows paths and quotes cannot break the handler.
function jsArg(value) {
    return escapeHtml(JSON.stringify(String(value ?? '')));
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Minimal, safe Markdown renderer for assistant replies: everything is HTML-escaped first,
// then headings, emphasis, lists, inline code, fenced code blocks and safe links are formatted.
function renderChatMarkdown(markdown) {
    const codeBlocks = [];
    let src = String(markdown || '').replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, code) => {
        codeBlocks.push(code.replace(/\n$/, ''));
        return `\u0000CODE${codeBlocks.length - 1}\u0000`;
    });

    const inline = (text) => escapeHtml(text)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>')
        .replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>')
        .replace(/\[([^\]]+)\]\(([^\)\s]+)\)/g, (match, label, url) => {
            if (!/^(https?:\/\/|\/)/i.test(url.replace(/&amp;/g, '&'))) return match;
            return `<a href="${url}" class="chat-link" target="_blank" rel="noopener noreferrer">${label}</a>`;
        });

    const html = [];
    let list = null;
    const closeList = () => { if (list) { html.push(`</${list}>`); list = null; } };
    src.split('\n').forEach(rawLine => {
        const line = rawLine.trimEnd();
        const codeMatch = line.match(/^\u0000CODE(\d+)\u0000$/);
        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        const bullet = line.match(/^\s*[-*]\s+(.*)$/);
        const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
        if (codeMatch) {
            closeList();
            html.push(`<pre class="chat-code"><code>${escapeHtml(codeBlocks[Number(codeMatch[1])])}</code></pre>`);
        } else if (heading) {
            closeList();
            html.push(`<h4 class="chat-heading">${inline(heading[2])}</h4>`);
        } else if (bullet || numbered) {
            const tag = bullet ? 'ul' : 'ol';
            if (list !== tag) { closeList(); html.push(`<${tag}>`); list = tag; }
            html.push(`<li>${inline((bullet || numbered)[1])}</li>`);
        } else if (!line.trim()) {
            closeList();
        } else {
            closeList();
            html.push(`<p>${inline(line)}</p>`);
        }
    });
    closeList();
    // Code placeholders that ended up inline (unusual) are restored as inline code
    return html.join('').replace(/\u0000CODE(\d+)\u0000/g, (_, i) => `<code>${escapeHtml(codeBlocks[Number(i)])}</code>`);
}

function appendChatMessage(sender, content, isHtml = false) {
    const container = document.getElementById('chat-messages-container');
    const msgDiv = document.createElement('div');
    const id = `msg-${Date.now()}`;
    msgDiv.id = id;
    msgDiv.className = `message ${sender}`;
    msgDiv.setAttribute('data-raw-content', content);
    
    const icon = sender === 'user' ? 'fa-user' : 'fa-robot';
    // Message text can contain LLM output and scraped document text, so it is escaped before rendering
    let bubbleContent = isHtml ? content : (sender === 'user'
        ? `<p>${escapeHtml(content).replace(/\n/g, '<br>')}</p>`
        : renderChatMarkdown(content));
    if (!isHtml) {
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
// Header profile (name, email, avatar) from the signed-in account
function initUserProfileManager() {
    const updateProfileUI = () => {
        const nameEl = document.getElementById('user-display-name');
        const emailEl = document.getElementById('user-display-email');
        const avatarImg = document.getElementById('user-display-avatar');
        const storedName = (localStorage.getItem('controlai_username') || '').trim();
        const storedEmail = (localStorage.getItem('controlai_email') || '').trim();
        if (nameEl) nameEl.textContent = storedName || (storedEmail ? storedEmail.split('@')[0] : 'Signed in');
        if (emailEl) emailEl.textContent = storedEmail;
        if (avatarImg) {
            const storedAvatar = localStorage.getItem('controlai_avatar');
            avatarImg.src = storedAvatar || initialsAvatar(storedName || storedEmail || '?');
        }
    };
    updateProfileUI();
    window.updateProfileUI = updateProfileUI;
    window.addEventListener('controlai_login_success', updateProfileUI);
}

// Local SVG avatar with the user's initials (no external image service)
function initialsAvatar(name) {
    const initials = name.replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" rx="32" fill="#4f46e5"/><text x="32" y="41" font-family="Arial" font-size="24" font-weight="700" fill="#fff" text-anchor="middle">${initials}</text></svg>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
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

    const tabBtns = document.querySelectorAll('.settings-tab-btn');
    const tabPanels = document.querySelectorAll('.settings-tab-panel');

    // Menu Triggers
    const btnDropdownProfile = document.getElementById('btn-dropdown-profile');
    const btnDropdownSecurity = document.getElementById('btn-dropdown-security');
    const btnDropdownPreferences = document.getElementById('btn-dropdown-preferences');

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

    const btnBack = document.getElementById('btn-back-dashboard');
    if (btnBack) btnBack.addEventListener('click', closeSettingsPage);

    // Tab switching
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

    // Profile dropdown entries (the sidebar "Settings" item forwards to the first one)
    [[btnDropdownProfile, 'tab-profile-settings'], [btnDropdownSecurity, 'tab-api-keys'], [btnDropdownPreferences, 'tab-preferences']]
        .forEach(([btn, tab]) => {
            if (!btn) return;
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                if (window.closeAllMenus) window.closeAllMenus();
                openSettingsPage(tab);
            });
        });

    // Load Profile Data from the server
    async function loadProfileData() {
        if (inputCurrentPass) inputCurrentPass.value = '';
        if (inputNewPass) inputNewPass.value = '';
        if (inputConfirmPass) inputConfirmPass.value = '';
        try {
            const res = await fetch('/api/v1/auth/profile');
            if (!res.ok) throw new Error('Could not load profile');
            const profile = await res.json();
            if (inputUsername) inputUsername.value = profile.display_name || '';
            if (inputEmail) inputEmail.value = profile.email;
            if (inputDob) inputDob.value = profile.date_of_birth || '';
            const roleEl = document.getElementById('settings-role');
            if (roleEl) roleEl.value = profile.role;
            const passwordDisabled = profile.sign_in_method !== 'password';
            [inputCurrentPass, inputNewPass, inputConfirmPass].forEach(el => {
                if (!el) return;
                el.disabled = passwordDisabled;
                el.placeholder = passwordDisabled ? 'Social sign-in: no password' : el.placeholder;
            });
        } catch (e) {
            showToast('error', 'Failed to load your profile.');
        }
    }

    // Save Profile Action (display name / date of birth, plus optional password change)
    if (btnSaveProfile) {
        btnSaveProfile.addEventListener('click', async () => {
            const username = inputUsername ? inputUsername.value.trim() : '';
            const dob = inputDob ? inputDob.value : '';
            const currentPass = inputCurrentPass ? inputCurrentPass.value : '';
            const newPass = inputNewPass ? inputNewPass.value : '';
            const confirmPass = inputConfirmPass ? inputConfirmPass.value : '';

            if (!username) {
                showToast('error', 'Please enter a display name.');
                if (inputUsername) inputUsername.focus();
                return;
            }
            if (newPass || confirmPass || currentPass) {
                if (!currentPass) { showToast('error', 'Enter your current password to change it.'); return; }
                if (newPass !== confirmPass) { showToast('error', 'New passwords do not match!'); return; }
            }

            btnSaveProfile.disabled = true;
            try {
                const res = await fetch('/api/v1/auth/profile', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ display_name: username, date_of_birth: dob || '' })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to save profile');

                if (newPass) {
                    const pwRes = await fetch('/api/v1/auth/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ current_password: currentPass, new_password: newPass })
                    });
                    const pwData = await pwRes.json();
                    if (!pwRes.ok) throw new Error(pwData.detail || 'Failed to change password');
                    showToast('success', 'Password changed.');
                }

                localStorage.setItem('controlai_username', data.display_name);
                if (window.updateProfileUI) window.updateProfileUI();
                showToast('success', `Profile saved. Welcome, ${data.display_name}.`);
                closeSettingsPage();
            } catch (err) {
                showToast('error', err.message);
            } finally {
                btnSaveProfile.disabled = false;
            }
        });
    }

    // API Keys: stored on the server (only a hash); the secret is shown once at creation
    async function loadApiKeysData() {
        if (!apiKeysTbody) return;
        try {
            const res = await fetch('/api/v1/auth/api-keys');
            if (!res.ok) throw new Error();
            const keys = await res.json();
            renderApiKeysTable(keys);
            renderApiLogs(keys);
        } catch (e) {
            apiKeysTbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px;">Failed to load API keys.</td></tr>`;
        }
    }

    function renderApiKeysTable(keys) {
        apiKeysTbody.innerHTML = '';
        if (keys.length === 0) {
            apiKeysTbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-secondary); padding:20px;">No API keys created yet.</td></tr>`;
            return;
        }
        keys.forEach(k => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${escapeHTML(k.name)}</strong></td>
                <td><span class="key-code">${escapeHTML(k.key_preview)}</span></td>
                <td><span class="env-badge ${k.environment.toLowerCase()}">${k.environment}</span></td>
                <td><span style="color:var(--text-secondary); font-size:0.85rem;">${k.created_at ? parseUTCDate(k.created_at).toLocaleDateString() : '-'}</span></td>
                <td><button class="btn-icon-subtle delete delete-key-btn" data-id="${k.id}" title="Revoke key"><i class="fa-solid fa-trash-can"></i></button></td>
            `;
            apiKeysTbody.appendChild(tr);
        });
        apiKeysTbody.querySelectorAll('.delete-key-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirmAction('Revoke this API key? Integrations using it will stop working.')) return;
                const res = await fetch(`/api/v1/auth/api-keys/${btn.getAttribute('data-id')}`, { method: 'DELETE' });
                if (res.ok) {
                    showToast('info', 'API key revoked.');
                    loadApiKeysData();
                } else {
                    showToast('error', 'Failed to revoke API key.');
                }
            });
        });
    }

    if (btnCreateKey) {
        btnCreateKey.addEventListener('click', async () => {
            const keyName = inputKeyName ? inputKeyName.value.trim() : '';
            const env = selectKeyEnv ? selectKeyEnv.value : 'Production';
            if (!keyName) {
                showToast('error', 'Please enter a key description name.');
                if (inputKeyName) inputKeyName.focus();
                return;
            }
            btnCreateKey.disabled = true;
            try {
                const res = await fetch('/api/v1/auth/api-keys', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: keyName, environment: env })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Failed to create key');
                if (inputKeyName) inputKeyName.value = '';
                showSecretOnce(data.secret, data.name);
                loadApiKeysData();
            } catch (err) {
                showToast('error', err.message);
            } finally {
                btnCreateKey.disabled = false;
            }
        });
    }

    function showSecretOnce(secret, name) {
        const box = document.createElement('div');
        box.className = 'api-secret-once';
        box.innerHTML = `
            <strong>New key "${escapeHTML(name)}" - copy it now, it will not be shown again:</strong>
            <div class="key-code-wrapper"><code class="key-code">${escapeHTML(secret)}</code>
            <button class="btn-icon-subtle" title="Copy"><i class="fa-solid fa-copy"></i></button></div>
            <span class="text-secondary">Use it as the <code>X-API-Key</code> header, e.g. <code>curl -H "X-API-Key: ${escapeHTML(secret)}" ${window.location.origin}/api/v1/dashboard/summary</code></span>`;
        box.querySelector('button').addEventListener('click', () => {
            navigator.clipboard.writeText(secret).then(() => showToast('success', 'API key copied.'));
        });
        const table = document.getElementById('table-api-keys');
        const existing = document.querySelector('.api-secret-once');
        if (existing) existing.remove();
        if (table) table.parentElement.insertBefore(box, table);
    }

    // Real usage of each key (request count and last use, recorded by the API)
    function renderApiLogs(keys) {
        if (!apiLogsList) return;
        if (!keys || keys.length === 0) {
            apiLogsList.innerHTML = `<p class="text-secondary" style="padding:10px;">No API keys yet.</p>`;
            return;
        }
        apiLogsList.innerHTML = keys.map(k => `
            <div class="api-log-entry">
                <div class="log-meta">
                    <span class="log-endpoint">${escapeHTML(k.name)}</span>
                    <span class="log-time">${k.last_used_at ? 'last used ' + parseUTCDate(k.last_used_at).toLocaleString() : 'never used'}</span>
                </div>
                <span class="log-status">${k.request_count} request(s)</span>
            </div>
        `).join('');
    }

    if (btnSaveApiKeys) {
        btnSaveApiKeys.addEventListener('click', () => closeSettingsPage());
    }

    // Preferences Tab Load & Save (per-browser UI preferences)
    function loadPreferencesData() {
        if (selectAccent) selectAccent.value = localStorage.getItem('pref_accent_theme') || 'cyan';
        if (selectGlass) selectGlass.value = localStorage.getItem('pref_glass_intensity') || 'high';
        if (selectLogLevel) selectLogLevel.value = localStorage.getItem('pref_log_level') || 'INFO';
        if (checkAutoAi) checkAutoAi.checked = localStorage.getItem('pref_auto_ai') !== 'false';
        if (checkAudioAlerts) checkAudioAlerts.checked = localStorage.getItem('pref_audio_alerts') !== 'false';
        if (selectDbEngine) {
            fetch('/api/v1/powerbi/status').then(r => r.ok ? r.json() : null).then(d => {
                if (d && d.connector) selectDbEngine.value = `${d.connector.driver} - ${d.connector.database} (${d.connector.status})`;
            }).catch(() => { selectDbEngine.value = 'Unavailable'; });
        }
    }

    // Apply saved accent theme on init
    applyAccentTheme(localStorage.getItem('pref_accent_theme') || 'cyan');
    applyGlassIntensity(localStorage.getItem('pref_glass_intensity') || 'high');

    if (btnSavePreferences) {
        btnSavePreferences.addEventListener('click', () => {
            const themeVal = selectAccent ? selectAccent.value : 'cyan';
            if (selectAccent) localStorage.setItem('pref_accent_theme', themeVal);
            if (selectGlass) localStorage.setItem('pref_glass_intensity', selectGlass.value);
            if (selectLogLevel) localStorage.setItem('pref_log_level', selectLogLevel.value);
            if (checkAutoAi) localStorage.setItem('pref_auto_ai', checkAutoAi.checked ? 'true' : 'false');
            if (checkAudioAlerts) localStorage.setItem('pref_audio_alerts', checkAudioAlerts.checked ? 'true' : 'false');

            applyAccentTheme(themeVal);
            applyGlassIntensity(selectGlass ? selectGlass.value : 'high');
            showToast('success', 'Preferences saved & applied.');
            closeSettingsPage();
        });
    }
}

function applyGlassIntensity(level) {
    document.body.classList.remove('glass-medium', 'glass-solid');
    if (level === 'medium') document.body.classList.add('glass-medium');
    if (level === 'solid') document.body.classList.add('glass-solid');
}

// Native confirm is avoided in automation contexts; this keeps destructive actions explicit
function confirmAction(message) {
    return window.confirm(message);
}

// Accent Theme Dynamic Switcher
function applyAccentTheme(theme) {
    const root = document.documentElement;
    if (theme === 'emerald') {
        root.style.setProperty('--color-blue', '#059669');
        root.style.setProperty('--color-blue-strong', '#065f46');
        root.style.setProperty('--color-blue-soft', '#ecfdf5');
        root.style.setProperty('--color-teal', '#047857');
        root.style.setProperty('--border-glow', 'rgba(5, 150, 105, 0.3)');
    } else if (theme === 'violet') {
        root.style.setProperty('--color-blue', '#7c3aed');
        root.style.setProperty('--color-blue-strong', '#5b21b6');
        root.style.setProperty('--color-blue-soft', '#f3f0fd');
        root.style.setProperty('--color-teal', '#6d28d9');
        root.style.setProperty('--border-glow', 'rgba(124, 58, 237, 0.3)');
    } else {
        root.style.setProperty('--color-blue', '#4f46e5');
        root.style.setProperty('--color-blue-strong', '#3730a3');
        root.style.setProperty('--color-blue-soft', '#eef0fd');
        root.style.setProperty('--color-teal', '#0d9488');
        root.style.setProperty('--border-glow', 'rgba(79, 70, 229, 0.25)');
    }
}




// Global download helpers
window.downloadNodeData = function(path) {
    const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
    window.open(`/api/v1/reports/download-file?path=${encodeURIComponent(path)}&email=${encodeURIComponent(email)}`, '_blank');
};

window.downloadStageMetadata = function(stageId) {
    const pipeData = state.currentPipelineData || {};
    const stages = pipeData.stages || {};
    const stage = stages[stageId] || {};
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(stage, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href",     dataStr);
    downloadAnchor.setAttribute("download", `${stageId}_stage_metadata.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
};





/* ==========================================================================
   Real-Time Pipeline Ingestion Monitor & RAG Handlers
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
    // RAG Drawer Open/Close Toggle
    const chatAttachBtn = document.getElementById('chat-attach-btn');
    const chatAttachDrawer = document.getElementById('chat-attach-drawer');
    const closeAttachDrawerBtn = document.getElementById('btn-close-attach-drawer');

    if (chatAttachBtn && chatAttachDrawer) {
        chatAttachBtn.addEventListener('click', () => {
            const isHidden = chatAttachDrawer.style.display === 'none';
            chatAttachDrawer.style.display = isHidden ? 'block' : 'none';
            chatAttachBtn.classList.toggle('active', isHidden);
            if (isHidden) {
                loadRagDocuments();
            }
        });
    }
    if (closeAttachDrawerBtn && chatAttachDrawer && chatAttachBtn) {
        closeAttachDrawerBtn.addEventListener('click', () => {
            chatAttachDrawer.style.display = 'none';
            chatAttachBtn.classList.remove('active');
        });
    }

    // RAG File Input Drop Zone Handlers
    const ragDropZone = document.getElementById('rag-file-drop-zone');
    const ragFileInput = document.getElementById('rag-file-input');

    if (ragDropZone && ragFileInput) {
        ragDropZone.addEventListener('click', () => ragFileInput.click());
        ragDropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            ragDropZone.style.borderColor = 'var(--color-blue)';
        });
        ragDropZone.addEventListener('dragleave', () => {
            ragDropZone.style.borderColor = 'rgba(255, 255, 255, 0.15)';
        });
        ragDropZone.addEventListener('drop', async (e) => {
            e.preventDefault();
            ragDropZone.style.borderColor = 'rgba(255, 255, 255, 0.15)';
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                await uploadRagFile(file);
            }
        });
        ragFileInput.addEventListener('change', async () => {
            if (ragFileInput.files.length > 0) {
                const file = ragFileInput.files[0];
                await uploadRagFile(file);
            }
        });
    }

    // RAG URL Ingestion Handler
    const btnRagUrlIngest = document.getElementById('btn-rag-url-ingest');
    const inputRagUrl = document.getElementById('rag-url-input');
    if (btnRagUrlIngest && inputRagUrl) {
        btnRagUrlIngest.addEventListener('click', async () => {
            const urlVal = inputRagUrl.value.trim();
            if (!urlVal) {
                showToast('error', 'Please enter a valid URL.');
                return;
            }
            btnRagUrlIngest.disabled = true;
            btnRagUrlIngest.textContent = 'Indexing...';
            try {
                const res = await fetch('/api/v1/rag/upload/url', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-User-Email': localStorage.getItem('controlai_email') || 'admin@controlai.net'
                    },
                    body: JSON.stringify({ url: urlVal })
                });
                if (res.ok) {
                    showToast('success', 'URL text content successfully indexed to RAG!');
                    inputRagUrl.value = '';
                    loadRagDocuments();
                } else {
                    const err = await res.json();
                    showToast('error', `RAG indexing failed: ${err.detail || 'Unknown error'}`);
                }
            } catch (err) {
                showToast('error', 'Failed to connect to RAG indexer.');
            } finally {
                btnRagUrlIngest.disabled = false;
                btnRagUrlIngest.textContent = 'Index Link';
            }
        });
    }


    // Monitor canvas click listeners for inspection nodes
    const mnodes = ['raw', 'intake', 'transformation', 'storage', 'report', 'pbi'];
    mnodes.forEach(nodeId => {
        const nodeCard = document.getElementById(`mnode-${nodeId}`);
        if (nodeCard) {
            nodeCard.addEventListener('click', () => {
                inspectPipelineMonitorNode(nodeId);
            });
        }
    });

    // Window resize observer to update SVG flowpaths dynamically
    window.addEventListener('resize', () => {
        updateMonitorPaths();
    });
});

// 2. Fetch and Render Indexed RAG Documents
async function loadRagDocuments() {
    const container = document.getElementById('indexed-docs-container');
    if (!container) return;
    try {
        const res = await fetch('/api/v1/rag/documents', {
            headers: {
                'X-User-Email': localStorage.getItem('controlai_email') || 'admin@controlai.net'
            }
        });
        if (!res.ok) throw new Error();
        const docs = await res.json();
        
        if (docs.length === 0) {
            container.innerHTML = `<p class="text-secondary" style="font-size:11px; text-align:center; padding:10px;">No RAG documents indexed yet.</p>`;
            return;
        }

        container.innerHTML = docs.map(doc => {
            const timeStr = new Date(doc.upload_time).toLocaleDateString();
            return `
                <div class="rag-doc-item">
                    <div class="rag-doc-info" title="${escapeHtml(doc.filename)} (Uploaded: ${timeStr})">
                        <i class="fa-solid ${doc.file_type === 'url' ? 'fa-link' : 'fa-file-lines'}"></i>
                        <span>${escapeHtml(doc.filename)}</span>
                    </div>
                    <button class="btn-delete-rag-doc" onclick="deleteRagDocument(${doc.id})" title="Delete knowledge item">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                </div>
            `;
        }).join('');
    } catch (e) {
        container.innerHTML = `<p class="text-red" style="font-size:11px; text-align:center; padding:10px;">Failed to load documents.</p>`;
    }
}

async function deleteRagDocument(docId) {
    try {
        const res = await fetch(`/api/v1/rag/documents/${docId}`, {
            method: 'DELETE',
            headers: {
                'X-User-Email': localStorage.getItem('controlai_email') || 'admin@controlai.net'
            }
        });
        if (res.ok) {
            showToast('success', 'RAG knowledge item deleted successfully.');
            loadRagDocuments();
        } else {
            showToast('error', 'Failed to delete knowledge item.');
        }
    } catch (e) {
        showToast('error', 'Connection error.');
    }
}
window.deleteRagDocument = deleteRagDocument;

async function uploadRagFile(file) {
    const dropZoneLabel = document.getElementById('rag-file-selected-name');
    if (dropZoneLabel) dropZoneLabel.textContent = `Uploading: ${file.name}...`;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/v1/rag/upload', {
            method: 'POST',
            headers: {
                'X-User-Email': localStorage.getItem('controlai_email') || 'admin@controlai.net'
            },
            body: formData
        });
        if (res.ok) {
            showToast('success', `${file.name} text indexed to local RAG storage successfully!`);
            loadRagDocuments();
        } else {
            const err = await res.json();
            showToast('error', `Failed to index file: ${err.detail || 'Unknown error'}`);
        }
    } catch (e) {
        showToast('error', 'Connection error while uploading RAG file.');
    } finally {
        if (dropZoneLabel) dropZoneLabel.textContent = `Click or Drag File to Index`;
    }
}

// 3. Pipeline monitor page initialization
window.openPipelineMonitorOverlay = function(batchId, filename) {
    const monPage = document.getElementById('pipeline-monitor-page');
    if (monPage) monPage.style.display = 'flex';
    
    // Set Header Info
    const bId = document.getElementById('monitor-batch-id');
    if (bId) bId.textContent = batchId;
    const fName = document.getElementById('monitor-file-name');
    if (fName) fName.textContent = filename;
    const rFile = document.getElementById('mnode-raw-file');
    if (rFile) rFile.textContent = filename;
    
    // Reset Stats
    const mRows = document.getElementById('monitor-stat-rows');
    if (mRows) mRows.textContent = '0';
    const mRej = document.getElementById('monitor-stat-rejections');
    if (mRej) mRej.textContent = '0';
    const mQual = document.getElementById('monitor-stat-quality');
    if (mQual) mQual.textContent = '100%';
    const mLoss = document.getElementById('monitor-stat-loss-rate');
    if (mLoss) mLoss.textContent = '0%';
    const pFill = document.getElementById('monitor-progress-bar-fill');
    if (pFill) pFill.style.width = '0%';
    const mStatus = document.getElementById('monitor-overall-status');
    if (mStatus) mStatus.textContent = 'Initializing...';
    const mPill = document.getElementById('monitor-overall-status-pill');
    if (mPill) mPill.className = 'monitor-stat-pill success';
    
    // Set all nodes to waiting
    const nodeIds = ['intake', 'transformation', 'storage', 'report', 'pbi'];
    nodeIds.forEach(id => {
        const el = document.getElementById(`mnode-${id}`);
        if (el) {
            el.className = `monitor-node-card ${id}-squircle waiting`;
            const desc = el.querySelector('.node-desc');
            if (desc) desc.textContent = 'Waiting';
        }
        
        const label = document.getElementById(`label-step-${id}`);
        if (label) label.className = '';
    });
    const rawEl = document.getElementById('mnode-raw');
    if (rawEl) rawEl.className = 'monitor-node-card raw-node';
    
    // Clear inspector panel
    const inspEmpty = document.getElementById('monitor-inspector-empty');
    if (inspEmpty) inspEmpty.style.display = 'flex';
    const inspContent = document.getElementById('monitor-inspector-content');
    if (inspContent) inspContent.style.display = 'none';

    // Start timer clock
    state.monitorStartTime = Date.now();
    if (state.monitorTimerInterval) clearInterval(state.monitorTimerInterval);
    state.monitorTimerInterval = setInterval(() => {
        const elapsed = ((Date.now() - state.monitorStartTime) / 1000).toFixed(1);
        const mDur = document.getElementById('monitor-duration');
        if (mDur) mDur.textContent = `${elapsed}s`;
    }, 100);

    // Render connecting lines
    setupMonitorSvg();
    
    // Initialize flow canvas
    state.previousStageStatuses = {};
    setTimeout(() => {
        initGamificationCanvas();
    }, 100);
};

// Setup and coordinates SVG paths in a branching layout
function setupMonitorSvg() {
    const svg = document.getElementById('monitor-connection-svg');
    if (!svg) return;
    svg.innerHTML = '';
    
    const connections = [
        { from: 'raw', to: 'storage' },
        { from: 'intake', to: 'storage' },
        { from: 'transformation', to: 'storage' },
        { from: 'storage', to: 'report' },
        { from: 'storage', to: 'pbi' }
    ];
    
    connections.forEach(conn => {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('id', `path-${conn.from}-to-${conn.to}`);
        path.setAttribute('class', 'svg-flow-path');
        svg.appendChild(path);
    });
    updateMonitorPaths();
}

function updateMonitorPaths() {
    const canvas = document.querySelector('.monitor-canvas-area');
    if (!canvas) return;
    const canvasRect = canvas.getBoundingClientRect();
    
    const connections = [
        { from: 'raw', to: 'storage' },
        { from: 'intake', to: 'storage' },
        { from: 'transformation', to: 'storage' },
        { from: 'storage', to: 'report' },
        { from: 'storage', to: 'pbi' }
    ];
    
    connections.forEach(conn => {
        const el1 = document.getElementById(`mnode-${conn.from}`);
        const el2 = document.getElementById(`mnode-${conn.to}`);
        const path = document.getElementById(`path-${conn.from}-to-${conn.to}`);
        if (!el1 || !el2 || !path) return;
        
        const r1 = el1.getBoundingClientRect();
        const r2 = el2.getBoundingClientRect();
        
        // Connect center coordinates to center coordinates
        const x1 = (r1.left + r1.right) / 2 - canvasRect.left;
        const y1 = (r1.top + r1.bottom) / 2 - canvasRect.top;
        const x2 = (r2.left + r2.right) / 2 - canvasRect.left;
        const y2 = (r2.top + r2.bottom) / 2 - canvasRect.top;
        
        path.setAttribute('d', `M ${x1} ${y1} L ${x2} ${y2}`);
    });
}

// 4. Update visualizer from stage data
function updatePipelineMonitorUI(data) {
    if (!data || !document.getElementById('pipeline-monitor-page')) return;
    
    const stages = data.stages || {};
    let progress = 0;
    let overallStatus = 'Processing...';
    let statusClass = 'monitor-stat-pill';
    
    // Update node statuses and connect paths
    const stepKeys = ['intake', 'transformation', 'storage', 'report', 'pbi'];
    let reachedActive = false;
    
    stepKeys.forEach((key, index) => {
        const stage = stages[key] || {};
        const nodeEl = document.getElementById(`mnode-${key}`);
        const labelEl = document.getElementById(`label-step-${key}`);
        
        let pathEl = null;
        if (key === 'intake') pathEl = document.getElementById('path-intake-to-storage');
        else if (key === 'transformation') pathEl = document.getElementById('path-transformation-to-storage');
        else if (key === 'storage') pathEl = document.getElementById('path-raw-to-storage');
        else if (key === 'report') pathEl = document.getElementById('path-storage-to-report');
        else if (key === 'pbi') pathEl = document.getElementById('path-storage-to-pbi');
        
        if (!nodeEl) return;
        
        // Node state class mapping
        if (stage.status === 'completed') {
            nodeEl.className = `monitor-node-card ${key}-squircle completed`;
            
            // Render inline download links
            const batchId = data.batch_id;
            const filename = data.filename || 'dataset.csv';
            const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
            const emailPath = email.replace('@','_').replace('.','_');
            
            let linksHtml = '';
            if (key === 'intake') {
                linksHtml = `<div class="node-card-links"><a href="#" onclick="downloadStageMetadata('intake'); event.stopPropagation();" class="node-inline-link" title="Download Profile JSON"><i class="fa-solid fa-file-code"></i> Profile</a></div>`;
            } else if (key === 'transformation') {
                const rel_clean = (data.stages && data.stages.transformation && data.stages.transformation.output && data.stages.transformation.output.clean_dataset_path) || `Accounts/${emailPath}/cleaned data/${filename}`;
                linksHtml = `<div class="node-card-links"><a href="#" onclick="downloadNodeData(${jsArg(rel_clean)}); event.stopPropagation();" class="node-inline-link" title="Download Clean CSV"><i class="fa-solid fa-file-csv"></i> Clean CSV</a></div>`;
            } else if (key === 'storage') {
                linksHtml = `<div class="node-card-links"><a href="#" onclick="downloadStageMetadata('storage'); event.stopPropagation();" class="node-inline-link" title="Download SQL DDL"><i class="fa-solid fa-database"></i> SQL DDL</a></div>`;
            } else if (key === 'report') {
                linksHtml = `
                    <div class="node-card-links">
                        <a href="#" onclick="downloadReport('${batchId}', 'pdf'); event.stopPropagation();" class="node-inline-link" title="PDF Report"><i class="fa-solid fa-file-pdf"></i> PDF</a>
                        <a href="#" onclick="downloadReport('${batchId}', 'docx'); event.stopPropagation();" class="node-inline-link" title="Word Report"><i class="fa-solid fa-file-word"></i> Word</a>
                    </div>`;
            } else if (key === 'pbi') {
                linksHtml = `<div class="node-card-links"><a href="#" onclick="window.activateView && window.activateView('powerbi-view'); event.stopPropagation();" class="node-inline-link"><i class="fa-solid fa-chart-column"></i> Exports</a></div>`;
            }
            
            nodeEl.querySelector('.node-desc').innerHTML = `<div>${getStageDesc(key, stage)}</div>${linksHtml}`;
            if (pathEl) pathEl.className = 'svg-flow-path completed';
            if (labelEl) labelEl.className = 'active';
            progress = Math.max(progress, (index + 1) * 20);

            // Confetti triggers on node completion transition
            state.previousStageStatuses = state.previousStageStatuses || {};
            if (state.previousStageStatuses[key] !== 'completed') {
                state.previousStageStatuses[key] = 'completed';
                setTimeout(() => {
                    const r = nodeEl.getBoundingClientRect();
                    const canvasEl = document.getElementById('gamification-canvas');
                    if (canvasEl) {
                        const canvasRect = canvasEl.getBoundingClientRect();
                        const x = r.left + r.width / 2 - canvasRect.left;
                        const y = r.top + r.height / 2 - canvasRect.top;
                        
                        let flowColor = '#8b5cf6';
                        if (key === 'intake') flowColor = '#ffb703';
                        else if (key === 'transformation') flowColor = '#219ebc';
                        else if (key === 'storage') flowColor = '#8b5cf6';
                        else if (key === 'report') flowColor = '#ef4444';
                        else if (key === 'pbi') flowColor = '#10b981';
                        
                        spawnExplosion(x, y, flowColor);
                    }
                }, 100);
            }
        } else if (stage.status === 'processing') {
            nodeEl.className = `monitor-node-card ${key}-squircle processing`;
            nodeEl.querySelector('.node-desc').textContent = 'Profiling...';
            if (pathEl) pathEl.className = 'svg-flow-path processing';
            if (labelEl) labelEl.className = 'active';
            reachedActive = true;
            progress = Math.max(progress, index * 20 + 10);
        } else if (stage.status === 'failed') {
            nodeEl.className = `monitor-node-card ${key}-squircle failed`;
            nodeEl.querySelector('.node-desc').textContent = 'Failed';
            if (pathEl) pathEl.className = 'svg-flow-path';
            if (labelEl) labelEl.className = 'text-red';
            overallStatus = 'Failed';
            statusClass = 'monitor-stat-pill failed';
        } else {
            nodeEl.className = `monitor-node-card ${key}-squircle waiting`;
            nodeEl.querySelector('.node-desc').textContent = 'Waiting';
            if (pathEl) pathEl.className = 'svg-flow-path';
            if (labelEl) labelEl.className = '';
        }
    });
    
    // Raw Ingest Node Link Update
    const rawNodeEl = document.getElementById('mnode-raw');
    if (rawNodeEl) {
        const intakeStage = stages['intake'] || {};
        if (intakeStage.status === 'completed' || intakeStage.status === 'processing') {
            const filename = data.filename || data.batch_id || '-';
            const rawLink = data.raw_file_path
                ? `<div class="node-card-links"><a href="#" onclick="downloadNodeData(${jsArg(data.raw_file_path)}); event.stopPropagation();" class="node-inline-link" title="Download Raw Input"><i class="fa-solid fa-download"></i> Raw Input</a></div>`
                : '';
            rawNodeEl.querySelector('.node-desc').innerHTML = `<div>${escapeHtml(filename)}</div>${rawLink}`;
            
            const rawPath = document.getElementById('path-raw-to-storage');
            if (rawPath) {
                if (intakeStage.status === 'completed') rawPath.className = 'svg-flow-path completed';
                else rawPath.className = 'svg-flow-path processing';
            }
        }
    }

    // Set Performance Stats from stages output
    let rowsCount = 0;
    let rejectionsCount = 0;
    let qualityScore = 100.0;
    
    if (stages['intake'] && stages['intake'].output) {
        rowsCount = stages['intake'].output.rows || 0;
        qualityScore = stages['intake'].output.estimated_quality || 100.0;
    }
    
    if (stages['transformation'] && stages['transformation'].output) {
        qualityScore = stages['transformation'].output.quality_after || qualityScore;
    }
    
    if (stages['storage'] && stages['storage'].output) {
        rejectionsCount = stages['storage'].output.rows_rejected || 0;
        rowsCount = stages['storage'].output.rows_loaded || rowsCount;
    }
    
    const stRows = document.getElementById('monitor-stat-rows');
    if (stRows) stRows.textContent = rowsCount;
    const stRej = document.getElementById('monitor-stat-rejections');
    if (stRej) stRej.textContent = rejectionsCount;
    const stQual = document.getElementById('monitor-stat-quality');
    if (stQual) stQual.textContent = `${qualityScore}%`;
    
    const lossRate = rowsCount > 0 ? ((rejectionsCount / (rowsCount + rejectionsCount)) * 100).toFixed(1) : 0;
    const stLoss = document.getElementById('monitor-stat-loss-rate');
    if (stLoss) stLoss.textContent = `${lossRate}%`;
    
    const pFill = document.getElementById('monitor-progress-bar-fill');
    if (pFill) pFill.style.width = `${progress}%`;

    // Header info and real duration from the server
    const hdrBatch = document.getElementById('monitor-batch-id');
    if (hdrBatch && data.batch_id) hdrBatch.textContent = data.batch_id;
    const hdrFile = document.getElementById('monitor-file-name');
    if (hdrFile && data.filename) hdrFile.textContent = data.filename;
    if (data.status !== 'Running' && typeof data.execution_time === 'number') {
        const mDur = document.getElementById('monitor-duration');
        if (mDur) mDur.textContent = `${data.execution_time.toFixed(1)}s`;
    }

    // Process general state status
    if (data.status === 'Success' || data.status === 'Passed with Warnings') {
        overallStatus = data.status;
        statusClass = 'monitor-stat-pill success';
        if (pFill) pFill.style.width = '100%';
        if (state.monitorTimerInterval) {
            clearInterval(state.monitorTimerInterval);
            state.monitorTimerInterval = null;
        }
    } else if (data.status === 'Failed') {
        overallStatus = 'Execution Aborted';
        statusClass = 'monitor-stat-pill error';
        if (state.monitorTimerInterval) {
            clearInterval(state.monitorTimerInterval);
            state.monitorTimerInterval = null;
        }
    } else {
        overallStatus = 'Active Ingestion';
        statusClass = 'monitor-stat-pill processing';
    }
    
    const stOverall = document.getElementById('monitor-overall-status');
    if (stOverall) stOverall.textContent = overallStatus;
    const stPill = document.getElementById('monitor-overall-status-pill');
    if (stPill) stPill.className = statusClass;
}

function getStageDesc(key, stage) {
    const output = stage.output || {};
    if (key === 'intake') return `${output.rows ?? '-'} rows profiled`;
    if (key === 'transformation') return `Quality: ${output.quality_after ?? '-'}%`;
    if (key === 'storage') return `${output.format_selected || '-'} | ${output.rows_loaded ?? 0} loaded, ${output.rows_rejected ?? 0} rejected`;
    if (key === 'report') return `${output.rca_alerts_count || 0} RCA finding(s)`;
    if (key === 'pbi') return `${Object.keys(output.tables || {}).length} tables exported`;
    return 'Completed';
}

// 5. Interactive Inspection of monitor nodes
function inspectPipelineMonitorNode(nodeId) {
    const emptyState = document.getElementById('monitor-inspector-empty');
    const content = document.getElementById('monitor-inspector-content');
    if (!emptyState || !content) return;
    
    const pipeData = state.currentPipelineData || {};
    const stages = pipeData.stages || {};
    
    emptyState.style.display = 'none';
    content.style.display = 'block';
    
    let title = '';
    let statusText = 'waiting';
    let statusClass = 'badge';
    let component = '';
    let dataHtml = '';
    let logHtml = '';
    
    if (nodeId === 'raw') {
        const intake = stages['intake'] || {};
        const filename = document.getElementById('monitor-file-name').textContent;
        title = 'Raw Ingestion File';
        statusText = intake.status !== 'waiting' ? 'read' : 'waiting';
        statusClass = 'badge success';
        component = 'com.snaplogic.snaps.file.FileReader';
        
        // Show raw data preview table from intake output
        if (intake.output && intake.output.preview && intake.output.preview.length > 0) {
            dataHtml = renderInspectorGrid(intake.output.preview);
        } else {
            dataHtml = `<p class="text-secondary" style="font-size:10px;">Raw file contents not profiled yet.</p>`;
        }
        logHtml = `<p style="color:#00ff00;">[FileReader] Loaded file buffer: ${filename}</p><p>[FileReader] Auto-detected encoding stream successfully.</p>`;
    } else {
        const stage = stages[nodeId] || {};
        statusText = stage.status || 'waiting';
        
        if (statusText === 'completed') statusClass = 'badge success';
        else if (statusText === 'processing') statusClass = 'badge warning';
        else if (statusText === 'failed') statusClass = 'badge failed';
        else statusClass = 'badge';
        
        const logs = stage.logs || [];
        logHtml = logs.length > 0 
            ? logs.map(line => `<p style="margin:2px 0;">${line}</p>`).join('') 
            : `<p class="text-secondary">No execution logs registered for this step yet.</p>`;
            
        if (nodeId === 'intake') {
            title = 'Iris AI Dataset Profiler';
            component = 'com.snaplogic.snaps.ai.IrisIntakeSnap';
            
            if (stage.output) {
                dataHtml = `
                    <table class="inspector-table">
                        <tr><td><strong>Dataset Rows</strong></td><td>${stage.output.rows || 0}</td></tr>
                        <tr><td><strong>Dataset Columns</strong></td><td>${stage.output.columns || 0}</td></tr>
                        <tr><td><strong>Total Missing Elements</strong></td><td>${stage.output.missing_values_total || 0}</td></tr>
                        <tr><td><strong>Duplicate Rows Found</strong></td><td>${stage.output.duplicate_rows || 0}</td></tr>
                        <tr><td><strong>Calculated Initial Quality</strong></td><td>${stage.output.estimated_quality || 100}%</td></tr>
                    </table>
                `;
            } else {
                dataHtml = `<p class="text-secondary" style="font-size:10px;">Stage waiting execution.</p>`;
            }
        } else if (nodeId === 'transformation') {
            title = 'Data Cleanser Snap';
            component = 'com.snaplogic.snaps.transform.DataCleanserSnap';
            
            if (stage.output && stage.output.preview) {
                dataHtml = `
                    <div style="margin-bottom:8px; font-size:10px; color:var(--color-teal); font-weight:600;">
                        Quality Score Improved: ${stage.output.quality_before}% ➔ ${stage.output.quality_after}%
                    </div>
                    ${renderInspectorGrid(stage.output.preview)}
                `;
            } else {
                dataHtml = `<p class="text-secondary" style="font-size:10px;">Waiting dataset cleanup.</p>`;
            }
        } else if (nodeId === 'storage') {
            title = 'MySQL Staging DB Snap';
            component = 'com.snaplogic.snaps.database.MySQLStagingSnap';
            
            if (stage.output) {
                let sqlCodeSection = '';
                if (stage.output.sql_preview) {
                    sqlCodeSection = `
                        <h5 style="font-size:9px; text-transform:uppercase; color:var(--color-blue); margin:8px 0 4px 0;">Generated DDL Schema & Insert Preview</h5>
                        <pre style="background:rgba(0,0,0,0.5); font-size:9px; padding:6px; border-radius:4px; overflow-x:auto; border:1px solid rgba(255,255,255,0.06); max-height:80px; color:#aaa; font-family:monospace; margin:0;">${stage.output.sql_preview}</pre>
                    `;
                }
                dataHtml = `
                    <table class="inspector-table">
                        <tr><td><strong>Format Selected</strong></td><td><span class="badge warning">${stage.output.format_selected || 'SQL'}</span></td></tr>
                        <tr><td><strong>Rows Staged & Loaded</strong></td><td class="text-green">${stage.output.rows_loaded || 0}</td></tr>
                        <tr><td><strong>Rows Rejected (Data Loss)</strong></td><td class="${stage.output.rows_rejected > 0 ? 'text-red' : 'text-green'}">${stage.output.rows_rejected || 0}</td></tr>
                    </table>
                    ${sqlCodeSection}
                `;
            } else {
                dataHtml = `<p class="text-secondary" style="font-size:10px;">Waiting staging DB load.</p>`;
            }
        } else if (nodeId === 'report') {
            title = 'PDF Report Exporter';
            component = 'com.snaplogic.snaps.file.DocumentGenerator';
            
            if (stage.status === 'completed' && stage.output) {
                const batchId = pipeData.batch_id;
                dataHtml = `
                    <div style="font-size:11px; margin-bottom:8px;">Analytical report has been compiled in multiple formats:</div>
                    <div style="display:flex; flex-direction:column; gap:6px;">
                        <button class="btn-download-file" onclick="downloadReport('${batchId}', 'pdf')" style="width:100%; text-align:left; display:flex; align-items:center; gap:8px;"><i class="fa-solid fa-file-pdf text-red"></i> Download PDF Executive Report</button>
                        <button class="btn-download-file" onclick="downloadReport('${batchId}', 'docx')" style="width:100%; text-align:left; display:flex; align-items:center; gap:8px;"><i class="fa-solid fa-file-word text-blue"></i> Download Word (Docx) Document</button>
                        <button class="btn-download-file" onclick="downloadReport('${batchId}', 'md')" style="width:100%; text-align:left; display:flex; align-items:center; gap:8px;"><i class="fa-solid fa-file-markdown text-purple"></i> Download Markdown Summary</button>
                    </div>
                `;
            } else {
                dataHtml = `<p class="text-secondary" style="font-size:10px;">Waiting document generation.</p>`;
            }
        } else if (nodeId === 'pbi') {
            title = 'Power BI Gateway Sync';
            component = 'com.snaplogic.snaps.bi.PowerBISync';
            
            if (stage.status === 'completed') {
                dataHtml = `
                    <div style="text-align:center; padding:12px; background:rgba(20, 184, 166, 0.05); border-radius:6px; border:1px dashed var(--color-teal);">
                        <i class="fa-solid fa-cloud-arrow-up" style="font-size:24px; color:var(--color-teal); margin-bottom:8px;"></i>
                        <h4 style="font-size:11px; margin:0; color:#fff;">Fact Tables Synchronized</h4>
                        <p style="font-size:9px; color:var(--text-secondary); margin:4px 0 0 0;">Power BI embedded model refreshed successfully.</p>
                    </div>
                `;
            } else {
                dataHtml = `<p class="text-secondary" style="font-size:10px;">Waiting dashboard sync.</p>`;
            }
        }
    }
    
    document.getElementById('inspector-node-title').textContent = title;
    document.getElementById('inspector-node-status').textContent = statusText;
    document.getElementById('inspector-node-status').className = statusClass;
    document.getElementById('inspector-node-component').textContent = component;
    document.getElementById('inspector-data-output').innerHTML = dataHtml;
    document.getElementById('inspector-logs-output').innerHTML = logHtml;
}

function renderInspectorGrid(records) {
    if (!records || records.length === 0) return '';
    const headers = Object.keys(records[0]);
    
    const headerHtml = headers.map(h => `<th>${h}</th>`).join('');
    const rowsHtml = records.slice(0, 4).map(row => {
        const cells = headers.map(h => {
            const val = row[h];
            return `<td>${val === null || val === undefined ? '<span class="text-secondary">null</span>' : String(val)}</td>`;
        }).join('');
        return `<tr>${cells}</tr>`;
    }).join('');
    
    return `
        <div style="overflow-x:auto; background:rgba(0,0,0,0.2); border-radius:4px; max-height:120px;">
            <table class="inspector-table" style="font-size:9px;">
                <thead><tr>${headerHtml}</tr></thead>
                <tbody>${rowsHtml}</tbody>
            </table>
        </div>
    `;
}



// Gamification Canvas Particles System
let animFrameId = null;
let canvasParticles = [];
let canvasExplosions = [];
let canvasFloatingTexts = [];
let canvasBanners = [];

function initGamificationCanvas() {
    const canvas = document.getElementById('gamification-canvas');
    if (!canvas) return;
    
    const resizeCanvas = () => {
        canvas.width = canvas.parentElement.clientWidth || window.innerWidth;
        canvas.height = canvas.parentElement.clientHeight || window.innerHeight;
    };
    
    resizeCanvas();
    window.removeEventListener('resize', resizeCanvas);
    window.addEventListener('resize', resizeCanvas);
    
    canvasParticles = [];
    canvasExplosions = [];
    canvasFloatingTexts = [];
    canvasBanners = [];

    // Boot banner disabled — restrained UI, no splash overlay on load.

    if (animFrameId) cancelAnimationFrame(animFrameId);
    animFrameId = requestAnimationFrame(canvasAnimationLoop);
}


function spawnExplosion(x, y, color = "#ffb703") {
    for (let i = 0; i < 60; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = Math.random() * 4 + 2;
        canvasExplosions.push({
            x: x,
            y: y,
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed,
            color: color,
            size: Math.random() * 4 + 2,
            alpha: 1,
            decay: Math.random() * 0.015 + 0.01,
            gravity: 0.08
        });
    }
}


function canvasAnimationLoop() {
    const canvas = document.getElementById('gamification-canvas');
    if (!canvas || !canvas.parentElement) {
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
        return;
    }
    
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // 1. Spawning Flow Particles based on active/processing node paths
    const stages = (state.currentPipelineData || {}).stages || {};
    const flows = [
        { from: 'mnode-raw', to: 'mnode-intake', key: 'intake', color: '#ffb703' },
        { from: 'mnode-intake', to: 'mnode-transformation', key: 'transformation', color: '#219ebc' },
        { from: 'mnode-transformation', to: 'mnode-storage', key: 'storage', color: '#8b5cf6' },
        { from: 'mnode-storage', to: 'mnode-report', key: 'report', color: '#ef4444' },
        { from: 'mnode-storage', to: 'mnode-pbi', key: 'pbi', color: '#10b981' }
    ];
    
    const canvasRect = canvas.getBoundingClientRect();
    
    flows.forEach(flow => {
        const stage = stages[flow.key] || {};
        if (stage.status === 'processing' || stage.status === 'completed') {
            const elFrom = document.getElementById(flow.from);
            const elTo = document.getElementById(flow.to);
            if (elFrom && elTo && elFrom.parentElement.style.display !== 'none' && elTo.parentElement.style.display !== 'none') {
                const r1 = elFrom.getBoundingClientRect();
                const r2 = elTo.getBoundingClientRect();
                const fromX = r1.left + r1.width / 2 - canvasRect.left;
                const fromY = r1.top + r1.height / 2 - canvasRect.top;
                const toX = r2.left + r2.width / 2 - canvasRect.left;
                const toY = r2.top + r2.height / 2 - canvasRect.top;
                
                // Spawn particle occasionally
                // Higher probability if processing, lower/none if completed
                const probability = stage.status === 'processing' ? 0.25 : 0.03;
                if (Math.random() < probability) {
                    canvasParticles.push({
                        fromX: fromX,
                        fromY: fromY,
                        toX: toX,
                        toY: toY,
                        x: fromX,
                        y: fromY,
                        progress: 0,
                        speed: Math.random() * 0.01 + 0.006,
                        size: Math.random() * 3 + 2,
                        color: flow.color,
                        waveMultiplier: Math.random() * 2 - 1
                    });
                }
            }
        }
    });
    
    // Update & Draw Flow Particles
    canvasParticles.forEach((p, idx) => {
        p.progress += p.speed;
        if (p.progress >= 1) {
            canvasParticles.splice(idx, 1);
            return;
        }
        
        // Linear path
        p.x = p.fromX + (p.toX - p.fromX) * p.progress;
        p.y = p.fromY + (p.toY - p.fromY) * p.progress;
        
        // Sine wave offset for organic look
        const offset = Math.sin(p.progress * Math.PI) * 15 * p.waveMultiplier;
        const normAngle = Math.atan2(p.toY - p.fromY, p.toX - p.fromX) + Math.PI / 2;
        const drawX = p.x + Math.cos(normAngle) * offset;
        const drawY = p.y + Math.sin(normAngle) * offset;
        
        ctx.beginPath();
        ctx.arc(drawX, drawY, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.shadowColor = p.color;
        ctx.shadowBlur = 6;
        ctx.fill();
        ctx.shadowBlur = 0; // reset
    });
    
    // 2. Update & Draw Explosions (Confetti)
    canvasExplosions.forEach((e, idx) => {
        e.x += e.vx;
        e.y += e.vy;
        e.vy += e.gravity;
        e.alpha -= e.decay;
        
        if (e.alpha <= 0) {
            canvasExplosions.splice(idx, 1);
            return;
        }
        
        ctx.beginPath();
        ctx.arc(e.x, e.y, e.size, 0, Math.PI * 2);
        ctx.fillStyle = e.color;
        ctx.globalAlpha = e.alpha;
        ctx.shadowColor = e.color;
        ctx.shadowBlur = 4;
        ctx.fill();
        ctx.shadowBlur = 0; // reset
        ctx.globalAlpha = 1; // reset
    });
    
    // 3. Update & Draw Floating Texts
    canvasFloatingTexts.forEach((t, idx) => {
        t.y += t.vy;
        t.alpha -= t.decay;
        
        if (t.alpha <= 0) {
            canvasFloatingTexts.splice(idx, 1);
            return;
        }
        
        ctx.font = "bold 14px 'Outfit', sans-serif";
        ctx.fillStyle = t.color;
        ctx.globalAlpha = t.alpha;
        ctx.textAlign = "center";
        ctx.shadowColor = "#000000";
        ctx.shadowBlur = 3;
        ctx.fillText(t.text, t.x, t.y);
        ctx.shadowBlur = 0; // reset
        ctx.globalAlpha = 1; // reset
    });
    
    // 4. Update & Draw Active Glow Portal Rings around processing nodes
    const activePortalAngle = (Date.now() / 300) % (Math.PI * 2);
    flows.forEach(flow => {
        const stage = stages[flow.key] || {};
        if (stage.status === 'processing') {
            const nodeEl = document.getElementById(flow.from); // the source of processing flow
            if (nodeEl) {
                const r = nodeEl.getBoundingClientRect();
                const x = r.left + r.width / 2 - canvasRect.left;
                const y = r.top + r.height / 2 - canvasRect.top;
                
                ctx.save();
                ctx.translate(x, y);
                ctx.rotate(activePortalAngle);
                ctx.beginPath();
                ctx.arc(0, 0, r.width / 2 + 10, 0, Math.PI * 2);
                ctx.strokeStyle = flow.color;
                ctx.lineWidth = 3;
                ctx.setLineDash([12, 8]);
                ctx.shadowColor = flow.color;
                ctx.shadowBlur = 10;
                ctx.stroke();
                ctx.restore();
            }
        }
    });
    
    // 5. Update & Draw Central Banner Popups
    canvasBanners.forEach((b, idx) => {
        b.life--;
        if (b.life <= 0) {
            canvasBanners.splice(idx, 1);
            return;
        }
        
        // Easing alpha
        if (b.life > b.maxLife - 20) {
            b.alpha = (b.maxLife - b.life) / 20;
            b.scale = 0.8 + 0.2 * b.alpha;
        } else if (b.life < 20) {
            b.alpha = b.life / 20;
            b.scale = 1.0 + 0.1 * (1 - b.alpha);
        } else {
            b.alpha = 1;
            b.scale = 1;
        }
        
        ctx.save();
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.scale(b.scale, b.scale);
        ctx.globalAlpha = b.alpha;
        
        // Card Background (Futuristic Dark Translucent)
        ctx.beginPath();
        const width = 360;
        const height = 90;
        ctx.roundRect(-width / 2, -height / 2, width, height, 15);
        ctx.fillStyle = "rgba(10, 24, 30, 0.9)";
        ctx.strokeStyle = b.color;
        ctx.lineWidth = 2;
        ctx.shadowColor = b.color;
        ctx.shadowBlur = 15;
        ctx.fill();
        ctx.stroke();
        ctx.shadowBlur = 0;
        
        // Title Text
        ctx.font = "bold 20px 'Outfit', sans-serif";
        ctx.fillStyle = "#ffffff";
        ctx.textAlign = "center";
        ctx.fillText(b.title, 0, -8);
        
        // Subtitle Text
        ctx.font = "500 12px 'Outfit', sans-serif";
        ctx.fillStyle = b.color;
        ctx.fillText(b.subtitle, 0, 16);
        
        ctx.restore();
        ctx.globalAlpha = 1;
    });
    
    animFrameId = requestAnimationFrame(canvasAnimationLoop);
}
