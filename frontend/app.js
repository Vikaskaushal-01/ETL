// Hijack window.fetch to inject X-User-Email header for account separation
const originalFetch = window.fetch;
window.fetch = function(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    const email = localStorage.getItem('controlai_email');
    if (email) {
        if (options.headers instanceof Headers) {
            options.headers.set('X-User-Email', email);
        } else if (Array.isArray(options.headers)) {
            options.headers.push(['X-User-Email', email]);
        } else {
            options.headers['X-User-Email'] = email;
        }
    }
    return originalFetch(url, options);
};

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
    activeInspectedStageId: null
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
                loadExplorerFiles();
                loadReportsList();

                // Draw graph components
                setTimeout(drawNetworkConnections, 600);
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
                showToast('success', 'Verification code sent to your email.');
                // Dynamic OTP notification for ease of demo copy-paste
                setTimeout(() => {
                    showToast('info', `[DEMO OTP CODE]: ${data.demo_code}`, 10000);
                }, 800);

                // Transition step
                forgotStepEmail.style.display = 'none';
                forgotStepCode.style.display = 'block';
                forgotHeaderTitle.textContent = 'Verify Code';
                forgotHeaderSubtitle.textContent = `We've sent a 6-digit code to ${email}`;
                inputForgotCode.value = '';
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
            setTimeout(drawNetworkConnections, 600);
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
        loadExplorerFiles();
        loadReportsList();

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

    const closeAllMenus = () => {
        document.getElementById('btn-toggle-graph').classList.remove('active');
        const pbiBtn = document.getElementById('btn-toggle-powerbi');
        if (pbiBtn) pbiBtn.classList.remove('active');
        document.getElementById('btn-toggle-explorer').classList.remove('active');
        document.getElementById('btn-toggle-logs').classList.remove('active');
        const profBtn = document.getElementById('btn-toggle-profile');
        if (profBtn) profBtn.classList.remove('active');

        explorerDrawer.classList.remove('active');
        consoleDrawer.classList.remove('active');
        if (powerbiDrawer) powerbiDrawer.classList.remove('active');

        const settingsOverlay = document.getElementById('settings-page-overlay');
        if (settingsOverlay) {
            settingsOverlay.style.display = 'none';
            settingsOverlay.classList.remove('active');
        }
        workspace.classList.remove('blur-bg');
    };
    window.closeAllMenus = closeAllMenus;

    if (btnTogglePowerBI && powerbiDrawer) {
        btnTogglePowerBI.addEventListener('click', () => {
            const wasActive = powerbiDrawer.classList.contains('active');
            closeAllMenus();
            if (!wasActive) {
                powerbiDrawer.classList.add('active');
                btnTogglePowerBI.classList.add('active');
                fetchPowerBIStatus();
                workspace.classList.add('blur-bg');
            } else {
                btnToggleGraph.classList.add('active');
            }
        });
    }

    if (btnClosePowerBI && powerbiDrawer) {
        btnClosePowerBI.addEventListener('click', () => {
            closeAllMenus();
            btnToggleGraph.classList.add('active');
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
        const wasActive = explorerDrawer.classList.contains('active');
        closeAllMenus();
        if (!wasActive) {
            explorerDrawer.classList.add('active');
            btnToggleExplorer.classList.add('active');
            loadExplorerFiles();
            loadDashboardStats();
            workspace.classList.add('blur-bg');
        } else {
            btnToggleGraph.classList.add('active');
        }
    });

    btnCloseExplorer.addEventListener('click', () => {
        closeAllMenus();
        btnToggleGraph.classList.add('active');
    });

    btnToggleLogs.addEventListener('click', () => {
        const wasActive = consoleDrawer.classList.contains('active');
        closeAllMenus();
        if (!wasActive) {
            consoleDrawer.classList.add('active');
            btnToggleLogs.classList.add('active');
            workspace.classList.add('blur-bg');
        } else {
            btnToggleGraph.classList.add('active');
        }
    });

    btnCloseLogs.addEventListener('click', () => {
        closeAllMenus();
        btnToggleGraph.classList.add('active');
    });

    btnToggleGraph.addEventListener('click', () => {
        closeAllMenus();
        btnToggleGraph.classList.add('active');
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
            const timeStr = data.dataset.last_refresh ? parseUTCDate(data.dataset.last_refresh).toLocaleTimeString() : 'Just now';
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

function osBasename(path) {
    return path.substring(path.lastIndexOf('/') + 1).substring(path.lastIndexOf('\\') + 1);
}

// Pipeline controls trigger
function initPipelineControls() {
    const runBtn = document.getElementById('btn-run-pipeline');
    
    runBtn.addEventListener('click', async () => {
        const hasVirtualInput = document.getElementById('manual-textarea').value.trim() !== '';
        const urlVal = document.getElementById('ingest-url-input') ? document.getElementById('ingest-url-input').value.trim() : '';
        let uploadResult = null;
        
        resetFlowVisual();
        clearConsole();
        
        if (window.closeAllMenus) window.closeAllMenus();
        document.getElementById('console-drawer').classList.add('active');
        document.getElementById('btn-toggle-logs').classList.add('active');
        document.querySelector('.network-workspace').classList.add('blur-bg');

        if (urlVal) {
            writeConsoleLog('[System] Fetching file from remote URL...');
            try {
                const uploadRes = await fetch('/api/v1/upload/url', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-User-Email': state.currentUserEmail || ''
                    },
                    body: JSON.stringify({ url: urlVal })
                });
                if (!uploadRes.ok) {
                    const err = await uploadRes.json();
                    writeConsoleLog(`[System Error] URL upload failed: ${err.detail || 'Unknown error'}`, 'text-red');
                    showToast('error', 'URL Ingestion failed.');
                    return;
                }
                uploadResult = await uploadRes.json();
            } catch (err) {
                writeConsoleLog(`[System Error] URL upload connection failed: ${err}`, 'text-red');
                showToast('error', 'Connection to URL upload failed.');
                return;
            }
        } else if (!hasVirtualInput) {
            if (!state.selectedFile) {
                showToast('error', 'Select a file or enter text data to ingest.');
                return;
            }
            writeConsoleLog('[System] Ingesting local file upload...');
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
            
            // Open full-screen pipeline monitor
            if (window.openPipelineMonitorOverlay) {
                window.openPipelineMonitorOverlay(batch_id, osBasename(file_path));
            }
            
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

            if (state.activeInspectedStageId && document.getElementById('stage-inspector-modal').style.display === 'flex') {
                openStageInspector(state.activeInspectedStageId);
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
    
    let htmlContent = text;
    
    if (status === 'completed' && state.currentPipelineData) {
        const data = state.currentPipelineData;
        const batchId = data.batch_id || state.currentBatchId;
        const filename = data.filename || 'dataset.csv';
        const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
        const emailPath = email.replace('@','_').replace('.','_');
        
        let linksHtml = '';
        if (step === 'intake') {
            linksHtml = `<div class="step-card-links"><a href="#" onclick="downloadStageMetadata('intake'); event.stopPropagation();" class="node-inline-link" title="Download Profile JSON"><i class="fa-solid fa-file-code"></i> Profile</a></div>`;
        } else if (step === 'transformation') {
            const rel_clean = `Accounts/${emailPath}/cleaned data/${filename}`;
            linksHtml = `<div class="step-card-links"><a href="#" onclick="downloadNodeData('${rel_clean}'); event.stopPropagation();" class="node-inline-link" title="Download Clean CSV"><i class="fa-solid fa-file-csv"></i> Clean CSV</a></div>`;
        } else if (step === 'storage') {
            linksHtml = `<div class="step-card-links"><a href="#" onclick="downloadStageMetadata('storage'); event.stopPropagation();" class="node-inline-link" title="Download SQL DDL"><i class="fa-solid fa-database"></i> SQL DDL</a></div>`;
        } else if (step === 'report') {
            linksHtml = `
                <div class="step-card-links">
                    <a href="#" onclick="downloadReport('${batchId}', 'pdf'); event.stopPropagation();" class="node-inline-link" title="PDF Report"><i class="fa-solid fa-file-pdf"></i> PDF</a>
                    <a href="#" onclick="downloadReport('${batchId}', 'docx'); event.stopPropagation();" class="node-inline-link" title="Word Report"><i class="fa-solid fa-file-word"></i> Word</a>
                </div>`;
        } else if (step === 'pbi') {
            linksHtml = `<div class="step-card-links"><span class="node-inline-link text-green"><i class="fa-solid fa-circle-check"></i> Sync OK</span></div>`;
        }
        htmlContent = `<div>${text}</div>${linksHtml}`;
    }
    
    stepEl.querySelector('.flow-status-text').innerHTML = htmlContent;
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

            const repRes = await fetch('/api/v1/reports/folders');
            const container = document.getElementById('pdf-reports-container');
            container.innerHTML = '';
            
            if (repRes.ok) {
                const folders = await repRes.json();
                if (folders && folders.length > 0) {
                    const batchFolder = folders.find(r => r.batch_id === batchId) || folders[0];
                    const reportId = batchFolder.batch_id;
                    const folderName = batchFolder.folder_name || 'dataset';
                    const dateStr = batchFolder.created_at ? parseUTCDate(batchFolder.created_at).toLocaleDateString() : 'Active';
                    
                    let switcherHtml = '';
                    if (folders.length > 1) {
                        switcherHtml = `
                            <div style="margin-bottom: 8px;">
                                <label style="font-size: 10px; color: #94a3b8; font-weight: 600; text-transform: uppercase;">Switch Report Folder:</label>
                                <select id="reports-folder-switcher" style="width: 100%; margin-top: 3px; padding: 5px 8px; font-size: 11px; background: #0f172a; color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 4px; cursor: pointer;" onchange="fetchSelectedBatchInsights(this.value)">
                                    ${folders.map(f => `<option value="${f.batch_id}" ${f.batch_id === reportId ? 'selected' : ''}>📁 reports/${f.folder_name}/ (${f.batch_id})</option>`).join('')}
                                </select>
                            </div>
                        `;
                    }
                    
                    container.innerHTML = `
                        <div class="report-item-download" style="flex-direction: column; align-items: stretch; gap: 10px; background: rgba(15, 23, 42, 0.6); padding: 14px; border-radius: 8px; border: 1px solid rgba(59, 130, 246, 0.2);">
                            ${switcherHtml}
                            <div class="report-info-text" style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 2px;">
                                <div>
                                    <h4 style="color: #60a5fa; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                                        <i class="fa-solid fa-folder-open text-yellow"></i> reports/${folderName}/
                                    </h4>
                                    <span style="font-size: 11px; color: #94a3b8;">Batch: <code>${reportId}</code> | ${dateStr}</span>
                                </div>
                                <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 10px; padding: 2px 6px;">4 Formats</span>
                            </div>
                            <p style="font-size: 11px; color: #cbd5e1; margin: 0;">Multi-format executive reports ready for download:</p>
                            <div class="report-download-buttons-row" style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                                <button class="btn-download-pdf" style="padding: 7px 10px; font-size: 11px; font-weight: 600; background: linear-gradient(135deg, #e11d48 0%, #be123c 100%); color: #fff; border: none; border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(225,29,72,0.2);" onclick="downloadReport('${reportId}', 'pdf')">
                                    <i class="fa-solid fa-file-pdf"></i> PDF (.pdf)
                                </button>
                                <button class="btn-download-word" style="padding: 7px 10px; font-size: 11px; font-weight: 600; background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: #fff; border: none; border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(37,99,235,0.2);" onclick="downloadReport('${reportId}', 'docx')">
                                    <i class="fa-solid fa-file-word"></i> Word (.docx)
                                </button>
                                <button class="btn-download-markdown" style="padding: 7px 10px; font-size: 11px; font-weight: 600; background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%); color: #fff; border: none; border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(14,165,233,0.2);" onclick="downloadReport('${reportId}', 'markdown')">
                                    <i class="fa-solid fa-file-code"></i> Markdown (.md)
                                </button>
                                <button class="btn-download-json" style="padding: 7px 10px; font-size: 11px; font-weight: 600; background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: #fff; border: none; border-radius: 6px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(245,158,11,0.2);" onclick="downloadReport('${reportId}', 'json')">
                                    <i class="fa-solid fa-braces"></i> JSON (.json)
                                </button>
                            </div>
                        </div>
                    `;
                } else {
                    container.innerHTML = `
                        <div class="no-data-card text-center">
                            <i class="fa-solid fa-file-pdf"></i>
                            <p>No analytical report generated yet. Run pipeline to generate reports.</p>
                        </div>`;
                }
            }

            // Fetch pipeline status to update 4 Sidebar KPIs and flowchart nodes dynamically
            try {
                const pipeStatusRes = await fetch(`/api/v1/pipeline/status?pipeline_id=pipe_${batchId}`);
                if (pipeStatusRes.ok) {
                    const pipeData = await pipeStatusRes.json();
                    if (pipeData) {
                        state.currentPipelineData = pipeData;
                        
                        // Update main flowchart nodes visually to match selected batch status
                        if (pipeData.stages) {
                            updateFlowVisualFromStages(pipeData.stages);
                        }
                        
                        // 1. Rows Ingested (stat-total-processed)
                        const rowsIngested = (pipeData.stages && pipeData.stages.intake && pipeData.stages.intake.output && typeof pipeData.stages.intake.output.rows === 'number') 
                            ? pipeData.stages.intake.output.rows 
                            : 0;
                        document.getElementById('stat-total-processed').textContent = rowsIngested.toLocaleString();
                        
                        // 2. Rejections (stat-failed-records)
                        const rejections = (pipeData.stages && pipeData.stages.storage && pipeData.stages.storage.output && typeof pipeData.stages.storage.output.rows_rejected === 'number') 
                            ? pipeData.stages.storage.output.rows_rejected 
                            : 0;
                        document.getElementById('stat-failed-records').textContent = rejections.toLocaleString();
                        
                        // 3. Pipeline Duration (stat-avg-runtime)
                        let durationVal = 0;
                        if (pipeData.execution_time) {
                            durationVal = pipeData.execution_time;
                        } else if (pipeData.start_time && pipeData.end_time) {
                            durationVal = (parseUTCDate(pipeData.end_time) - parseUTCDate(pipeData.start_time)) / 1000;
                        }
                        document.getElementById('stat-avg-runtime').textContent = `${durationVal.toFixed(1)}s`;
                        
                        // 4. Success Rate (stat-success-rate)
                        let successRate = 100;
                        if (rowsIngested > 0) {
                            successRate = ((rowsIngested - rejections) / rowsIngested) * 100;
                        } else {
                            if (pipeData.status === 'Failed') successRate = 0;
                            else if (pipeData.status === 'Success' || pipeData.status === 'Passed with Warnings') successRate = 100;
                        }
                        document.getElementById('stat-success-rate').textContent = `${successRate.toFixed(1)}%`;
                    }
                }
            } catch (err) {
                loggerError('fetchSelectedBatchInsights.pipeStatus', err);
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
            
            const startStr = run.start_time ? parseUTCDate(run.start_time).toLocaleTimeString() : 'N/A';
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
    if (window.closeAllMenus) window.closeAllMenus();
    document.getElementById('btn-toggle-graph').classList.add('active');
    
    fetchSelectedBatchInsights(batchId);
    showToast('info', `Loaded insights: ${batchId}`);
};

function viewRunLogs(pipelineId) {
    if (window.closeAllMenus) window.closeAllMenus();
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
    const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
    window.open(`/api/v1/dashboard/download?file_path=${encodeURIComponent(filePath)}&email=${encodeURIComponent(email)}`, '_blank');
}

// PDF Reports List Operations
async function loadReportsList() {
    try {
        const response = await fetch('/api/v1/reports/folders');
        if (!response.ok) return;
        const folders = await response.json();
        
        if (folders && folders.length > 0) {
            const targetBatch = state.currentBatchId || folders[0].batch_id;
            fetchSelectedBatchInsights(targetBatch);
        } else {
            const repRes = await fetch('/api/v1/reports/history');
            if (repRes.ok) {
                const reports = await repRes.json();
                if (reports && reports.length > 0) {
                    const targetBatch = state.currentBatchId || reports[0].batch_id;
                    fetchSelectedBatchInsights(targetBatch);
                }
            }
        }
    } catch (e) {
        loggerError('loadReportsList', e);
    }
}

window.downloadReport = function(batchId, format) {
    const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
    window.open(`/api/v1/reports/download/${batchId}?format=${format}&email=${encodeURIComponent(email)}`, '_blank');
};

// AI Assistant Chat operations
async function loadChatBatchContexts() {
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
                    history: state.chatHistory
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

        const storedAvatar = localStorage.getItem('controlai_avatar');
        const avatarImg = document.getElementById('user-display-avatar');
        if (storedAvatar && avatarImg) {
            avatarImg.src = storedAvatar;
        } else if (avatarImg) {
            avatarImg.src = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=100&q=80';
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
        if (window.closeAllMenus) window.closeAllMenus();
        document.getElementById('btn-toggle-graph').classList.add('active');
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
            if (window.closeAllMenus) window.closeAllMenus();
            if (btnToggleProfile) btnToggleProfile.classList.add('active');
            openSettingsPage('tab-profile-settings');
        });
    }
    if (btnDropdownSecurity) {
        btnDropdownSecurity.addEventListener('click', (e) => {
            e.preventDefault();
            if (window.closeAllMenus) window.closeAllMenus();
            if (btnToggleProfile) btnToggleProfile.classList.add('active');
            openSettingsPage('tab-api-keys');
        });
    }
    if (btnDropdownPreferences) {
        btnDropdownPreferences.addEventListener('click', (e) => {
            e.preventDefault();
            if (window.closeAllMenus) window.closeAllMenus();
            if (btnToggleProfile) btnToggleProfile.classList.add('active');
            openSettingsPage('tab-preferences');
        });
    }
    if (btnToggleProfile) {
        btnToggleProfile.addEventListener('click', (e) => {
            e.preventDefault();
            const wasActive = overlay && overlay.classList.contains('active');
            if (!wasActive) {
                if (window.closeAllMenus) window.closeAllMenus();
                btnToggleProfile.classList.add('active');
                openSettingsPage('tab-profile-settings');
            } else {
                closeSettingsPage();
            }
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
            state.activeInspectedStageId = null;
        });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
                state.activeInspectedStageId = null;
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
    
    state.activeInspectedStageId = stageId;
    
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
    const startTimeStr = stage.start_time ? parseUTCDate(stage.start_time).toLocaleTimeString() : 'N/A';
    const endTimeStr = stage.end_time ? parseUTCDate(stage.end_time).toLocaleTimeString() : (status === 'processing' ? 'Running...' : 'N/A');
    const duration = stage.start_time && stage.end_time 
        ? ((parseUTCDate(stage.end_time) - parseUTCDate(stage.start_time)) / 1000).toFixed(2) + 's' 
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

        // Build dynamic button generator for premium aesthetics
        const makeDownloadButton = (label, iconClass, onClickString, themeColor = 'rgba(255,255,255,0.06)', textColor = '#fff', borderColor = 'rgba(255,255,255,0.15)') => {
            return `<button style="padding: 6px 12px; font-size: 11px; background: ${themeColor}; border: 1px solid ${borderColor}; color: ${textColor}; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-family:inherit; font-weight:500; transition: all 0.2s;" onmouseover="this.style.transform='translateY(-1px)'; this.style.boxShadow='0 2px 4px rgba(0,0,0,0.2)';" onmouseout="this.style.transform='none'; this.style.boxShadow='none';" onclick="${onClickString}"><i class="${iconClass}"></i> ${label}</button>`;
        };

        // Construct dynamic actions html
        const batchId = pipeData.batch_id || state.currentBatchId || '';
        const filename = pipeData.dataset_name || (state.selectedFile ? state.selectedFile.name : 'dataset.csv');
        
        let downloadActionsHtml = `
            <div style="margin-bottom: 14px; padding: 12px; background: rgba(255, 255, 255, 0.03); border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.08);">
                <h4 style="font-size:12px; margin-top:0; margin-bottom:8px; color: var(--color-blue); font-weight:600;"><i class="fa-solid fa-cloud-arrow-down" style="margin-right:4px;"></i> Node Data & Outputs Download</h4>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
        `;

        if (stageId === 'intake') {
            downloadActionsHtml += makeDownloadButton('Download Raw Input', 'fa-solid fa-file-import', `downloadNodeData('data/raw/${filename}')`, 'rgba(0, 240, 255, 0.15)', '#fff', 'var(--color-blue)') + ' ';
            downloadActionsHtml += makeDownloadButton('Download Profile (JSON)', 'fa-solid fa-code', "downloadStageMetadata('intake')", 'rgba(20, 184, 166, 0.15)', '#fff', 'var(--color-teal)') + ' ';
        } else if (stageId === 'transformation') {
            downloadActionsHtml += makeDownloadButton('Download Raw Input', 'fa-solid fa-file-import', `downloadNodeData('data/raw/${filename}')`) + ' ';
            downloadActionsHtml += makeDownloadButton('Download Cleaned Output', 'fa-solid fa-wand-magic-sparkles', `downloadNodeData('cleaned data/${filename}')`, 'rgba(16, 185, 129, 0.15)', '#fff', '#10b981') + ' ';
            downloadActionsHtml += makeDownloadButton('Download Audit Log (JSON)', 'fa-solid fa-clock-rotate-left', "downloadStageMetadata('transformation')", 'rgba(245, 158, 11, 0.15)', '#fff', '#f59e0b') + ' ';
        } else if (stageId === 'storage') {
            downloadActionsHtml += makeDownloadButton('Download Cleaned Input', 'fa-solid fa-wand-magic-sparkles', `downloadNodeData('cleaned data/${filename}')`) + ' ';
            if (stage.output && stage.output.formatted_file_path) {
                const fmt = stage.output.format_selected || 'Export';
                downloadActionsHtml += makeDownloadButton(`Download Target ${fmt}`, 'fa-solid fa-database', `downloadNodeData('${stage.output.formatted_file_path.replace(/\\/g, '/')}')`, 'rgba(59, 130, 246, 0.15)', '#fff', '#3b82f6') + ' ';
            }
        } else if (stageId === 'report') {
            if (stage.output && stage.output.pdf_path) {
                downloadActionsHtml += makeDownloadButton('Download PDF Report', 'fa-solid fa-file-pdf', `downloadReport('${batchId}', 'pdf')`, 'rgba(239, 68, 68, 0.15)', '#fff', '#ef4444') + ' ';
            }
            if (stage.output && stage.output.docx_path) {
                downloadActionsHtml += makeDownloadButton('Download Word Doc', 'fa-solid fa-file-word', `downloadReport('${batchId}', 'docx')`, 'rgba(59, 130, 246, 0.15)', '#fff', '#3b82f6') + ' ';
            }
        } else if (stageId === 'pbi') {
            downloadActionsHtml += makeDownloadButton('Download Schema Metadata', 'fa-solid fa-chart-column', "downloadStageMetadata('pbi')", 'rgba(245, 158, 11, 0.15)', '#fff', '#f59e0b') + ' ';
        }

        downloadActionsHtml += makeDownloadButton('Download Graph JSON', 'fa-solid fa-network-wired', `downloadGraphJson('${batchId}')`, 'rgba(168, 85, 247, 0.15)', '#fff', 'var(--color-blue)') + ' ';
        downloadActionsHtml += makeDownloadButton('Download Flowchart (SVG)', 'fa-solid fa-project-diagram', `downloadFlowchart('${batchId}')`, 'rgba(20, 184, 166, 0.15)', '#fff', 'var(--color-teal)') + ' ';
        downloadActionsHtml += makeDownloadButton('Download Stage Logs', 'fa-solid fa-terminal', `downloadStageLogs('${stageId}')`) + ' ';

        downloadActionsHtml += `
                </div>
            </div>
        `;
        
        dataPreviewHtml = `
            <!-- Timings Section -->
            <div style="display:flex; justify-content:space-between; margin-bottom:14px; padding: 10px; background: rgba(255,255,255,0.03); border-radius:6px; border:1px solid rgba(255,255,255,0.05); font-size:12px;">
                <div><i class="fa-regular fa-clock" style="margin-right:4px;"></i> Started: <strong>${startTimeStr}</strong></div>
                <div><i class="fa-solid fa-clock-rotate-left" style="margin-right:4px;"></i> Ended: <strong>${endTimeStr}</strong></div>
                <div><i class="fa-solid fa-stopwatch" style="margin-right:4px;"></i> Duration: <strong style="color: var(--color-blue);">${duration}</strong></div>
            </div>
            
            <!-- Real-time Flowchart Diagram -->
            <div style="margin-bottom:14px;">
                <h4 style="font-size:12px; margin-bottom:6px; color:var(--color-blue); font-weight:600;"><i class="fa-solid fa-project-diagram"></i> Real-time Ingestion Data Flow</h4>
                <div style="background: rgba(15, 23, 42, 0.45); border-radius: 6px; padding: 8px; border: 1px solid rgba(255,255,255,0.08); text-align: center; overflow: hidden;">
                    <img src="/api/v1/pipeline/flowchart?batch_id=${batchId}&t=${Date.now()}" style="width:100%; max-height:160px; object-fit:contain;" alt="Pipeline Flowchart">
                </div>
            </div>
            
            ${downloadActionsHtml}
            
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

window.downloadStageLogs = function(stageId) {
    const pipeData = state.currentPipelineData || {};
    const stages = pipeData.stages || {};
    const stage = stages[stageId] || {};
    const logs = stage.logs || [];
    const dataStr = "data:text/plain;charset=utf-8," + encodeURIComponent(logs.join("\n"));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href",     dataStr);
    downloadAnchor.setAttribute("download", `${stageId}_stage_logs.txt`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
};

window.downloadReport = function(batchId, format) {
    const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
    window.open(`/api/v1/reports/download/${batchId}?format=${format}&email=${encodeURIComponent(email)}`, '_blank');
};

window.downloadGraphJson = function(batchId) {
    const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
    window.open(`/api/v1/pipeline/graph-json?batch_id=${encodeURIComponent(batchId)}&email=${encodeURIComponent(email)}`, '_blank');
};

window.downloadFlowchart = function(batchId) {
    const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
    window.open(`/api/v1/pipeline/flowchart?batch_id=${encodeURIComponent(batchId)}&email=${encodeURIComponent(email)}`, '_blank');
};

/* ==========================================================================
   Real-Time Pipeline Ingestion Monitor & RAG Handlers
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
    // Accordion Toggle for Ingest URL
    const toggleUrlBtn = document.getElementById('toggle-url-input');
    const urlInputBody = document.getElementById('url-input-body');
    if (toggleUrlBtn && urlInputBody) {
        toggleUrlBtn.addEventListener('click', () => {
            const isHidden = urlInputBody.style.display === 'none';
            urlInputBody.style.display = isHidden ? 'block' : 'none';
            toggleUrlBtn.querySelector('.arrow-icon').className = isHidden 
                ? 'fa-solid fa-chevron-up arrow-icon' 
                : 'fa-solid fa-chevron-down arrow-icon';
        });
    }

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

    // Exit Pipeline Monitor button handler
    const btnCloseMonitorPage = document.getElementById('btn-close-monitor-page');
    if (btnCloseMonitorPage) {
        btnCloseMonitorPage.addEventListener('click', () => {
            document.getElementById('pipeline-monitor-page').style.display = 'none';
            document.querySelector('.network-workspace').classList.remove('blur-bg');
            if (state.monitorTimerInterval) {
                clearInterval(state.monitorTimerInterval);
                state.monitorTimerInterval = null;
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
        if (document.getElementById('pipeline-monitor-page').style.display === 'flex') {
            updateMonitorPaths();
        }
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
                    <div class="rag-doc-info" title="${doc.filename} (Uploaded: ${timeStr})">
                        <i class="fa-solid ${doc.file_type === 'url' ? 'fa-link' : 'fa-file-lines'}"></i>
                        <span>${doc.filename}</span>
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
    // Show overlay
    document.getElementById('pipeline-monitor-page').style.display = 'flex';
    document.querySelector('.network-workspace').classList.add('blur-bg');
    
    // Set Header Info
    document.getElementById('monitor-batch-id').textContent = batchId;
    document.getElementById('monitor-file-name').textContent = filename;
    document.getElementById('mnode-raw-file').textContent = filename;
    
    // Reset Stats
    document.getElementById('monitor-stat-rows').textContent = '0';
    document.getElementById('monitor-stat-rejections').textContent = '0';
    document.getElementById('monitor-stat-quality').textContent = '100%';
    document.getElementById('monitor-stat-loss-rate').textContent = '0%';
    document.getElementById('monitor-progress-bar-fill').style.width = '0%';
    document.getElementById('monitor-overall-status').textContent = 'Initializing...';
    document.getElementById('monitor-overall-status-pill').className = 'monitor-stat-pill success';
    
    // Set all nodes to waiting
    const nodeIds = ['intake', 'transformation', 'storage', 'report', 'pbi'];
    nodeIds.forEach(id => {
        const el = document.getElementById(`mnode-${id}`);
        if (el) {
            el.className = 'monitor-node-card waiting';
            el.querySelector('.node-desc').textContent = 'Waiting';
        }
        
        const label = document.getElementById(`label-step-${id}`);
        if (label) label.className = '';
    });
    document.getElementById('mnode-raw').className = 'monitor-node-card raw-node';
    
    // Clear inspector panel
    document.getElementById('monitor-inspector-empty').style.display = 'flex';
    document.getElementById('monitor-inspector-content').style.display = 'none';

    // Start timer clock
    state.monitorStartTime = Date.now();
    if (state.monitorTimerInterval) clearInterval(state.monitorTimerInterval);
    state.monitorTimerInterval = setInterval(() => {
        const elapsed = ((Date.now() - state.monitorStartTime) / 1000).toFixed(1);
        document.getElementById('monitor-duration').textContent = `${elapsed}s`;
    }, 100);

    // Render connecting lines
    setupMonitorSvg();
    
    // Reset badges
    document.getElementById('badge-dup-slayer').className = 'badge-item locked';
    document.getElementById('badge-null-hunter').className = 'badge-item locked';
    document.getElementById('badge-schema-shield').className = 'badge-item locked';
    
    // Retrieve stored XP
    const currentXp = parseInt(localStorage.getItem('user_xp') || '350');
    const currentLevel = parseInt(localStorage.getItem('user_xp_level') || '1');
    document.getElementById('user-xp-current').textContent = currentXp;
    document.getElementById('user-xp-level').textContent = currentLevel;
    document.getElementById('xp-progress-bar').style.width = `${(currentXp % 1000) / 10}%`;
    
    // Initialize gamification canvas
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
    if (document.getElementById('pipeline-monitor-page').style.display !== 'flex') return;
    
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
                const rel_clean = `Accounts/${emailPath}/cleaned data/${filename}`;
                linksHtml = `<div class="node-card-links"><a href="#" onclick="downloadNodeData('${rel_clean}'); event.stopPropagation();" class="node-inline-link" title="Download Clean CSV"><i class="fa-solid fa-file-csv"></i> Clean CSV</a></div>`;
            } else if (key === 'storage') {
                linksHtml = `<div class="node-card-links"><a href="#" onclick="downloadStageMetadata('storage'); event.stopPropagation();" class="node-inline-link" title="Download SQL DDL"><i class="fa-solid fa-database"></i> SQL DDL</a></div>`;
            } else if (key === 'report') {
                linksHtml = `
                    <div class="node-card-links">
                        <a href="#" onclick="downloadReport('${batchId}', 'pdf'); event.stopPropagation();" class="node-inline-link" title="PDF Report"><i class="fa-solid fa-file-pdf"></i> PDF</a>
                        <a href="#" onclick="downloadReport('${batchId}', 'docx'); event.stopPropagation();" class="node-inline-link" title="Word Report"><i class="fa-solid fa-file-word"></i> Word</a>
                    </div>`;
            } else if (key === 'pbi') {
                linksHtml = `<div class="node-card-links"><span class="node-inline-link text-green"><i class="fa-solid fa-circle-check"></i> Sync OK</span></div>`;
            }
            
            nodeEl.querySelector('.node-desc').innerHTML = `<div>${getStageDesc(key, stage)}</div>${linksHtml}`;
            if (pathEl) pathEl.className = 'svg-flow-path completed';
            if (labelEl) labelEl.className = 'active';
            progress = Math.max(progress, (index + 1) * 20);

            // Confetti and floating text triggers on node completion transition
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
                        spawnFloatingText(x, y - 50, `+200 XP`, flowColor);
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
            const filename = data.filename || 'dataset.csv';
            const email = localStorage.getItem('controlai_email') || 'admin@controlai.net';
            const emailPath = email.replace('@','_').replace('.','_');
            const rel_raw = `Accounts/${emailPath}/data/raw/${filename}`;
            rawNodeEl.querySelector('.node-desc').innerHTML = `
                <div>${filename}</div>
                <div class="node-card-links"><a href="#" onclick="downloadNodeData('${rel_raw}'); event.stopPropagation();" class="node-inline-link" title="Download Raw Input"><i class="fa-solid fa-download"></i> Raw Input</a></div>
            `;
            
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
    
    document.getElementById('monitor-stat-rows').textContent = rowsCount;
    document.getElementById('monitor-stat-rejections').textContent = rejectionsCount;
    document.getElementById('monitor-stat-quality').textContent = `${qualityScore}%`;
    
    const lossRate = rowsCount > 0 ? ((rejectionsCount / (rowsCount + rejectionsCount)) * 100).toFixed(1) : 0;
    document.getElementById('monitor-stat-loss-rate').textContent = `${lossRate}%`;
    
    document.getElementById('monitor-progress-bar-fill').style.width = `${progress}%`;

    // Process general state status
    if (data.status === 'Success' || data.status === 'Passed with Warnings') {
        overallStatus = 'Finished';
        statusClass = 'monitor-stat-pill success';
        document.getElementById('monitor-progress-bar-fill').style.width = '100%';
        if (state.monitorTimerInterval) {
            clearInterval(state.monitorTimerInterval);
            state.monitorTimerInterval = null;
        }
        
        // Trigger gamification XP increment
        awardXpPoints(rejectionsCount, qualityScore);
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
    
    document.getElementById('monitor-overall-status').textContent = overallStatus;
    document.getElementById('monitor-overall-status-pill').className = statusClass;
}

function getStageDesc(key, stage) {
    const output = stage.output || {};
    if (key === 'intake') return `${output.rows || 0} rows profiled`;
    if (key === 'transformation') return `Quality: ${output.quality_after || 100}%`;
    if (key === 'storage') return `${output.format_selected || 'SQL'} | Staged`;
    if (key === 'report') return 'PDF Exporter ready';
    if (key === 'pbi') return 'Facts Synced';
    return 'Completed';
}

// Intercept polling loop to hook monitor UI updates
const originalPolling = startPipelinePolling;
startPipelinePolling = function(pipelineId) {
    originalPolling(pipelineId);
    
    // Poll hook to update full-screen monitor UI
    const customInterval = setInterval(async () => {
        if (!state.pipelinePollingInterval) {
            // Stop this custom hook loop as well if main is cancelled
            clearInterval(customInterval);
            return;
        }
        try {
            const res = await fetch(`/api/v1/pipeline/status?pipeline_id=${pipelineId}`);
            if (res.ok) {
                const data = await res.json();
                updatePipelineMonitorUI(data);
            }
        } catch (e) {}
    }, 1500);
};

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

// 6. Gamification XP Engine
function awardXpPoints(rejectionsCount, qualityScore) {
    // XP math: base 300XP for completion + bonus for high quality
    let xpGain = 300;
    if (qualityScore > 95) xpGain += 100;
    if (rejectionsCount === 0) xpGain += 100;
    
    let currentXp = parseInt(localStorage.getItem('user_xp') || '350');
    let currentLevel = parseInt(localStorage.getItem('user_xp_level') || '1');
    
    let newXp = currentXp + xpGain;
    let newLevel = Math.floor(newXp / 1000) + 1;
    let levelUp = newLevel > currentLevel;
    
    localStorage.setItem('user_xp', newXp);
    localStorage.setItem('user_xp_level', newLevel);
    
    document.getElementById('user-xp-current').textContent = newXp;
    document.getElementById('user-xp-level').textContent = newLevel;
    document.getElementById('xp-progress-bar').style.width = `${(newXp % 1000) / 10}%`;
    
    showToast('info', `+${xpGain} XP Gained! (Level ${newLevel})`);
    
    if (levelUp) {
        setTimeout(() => {
            spawnBanner("LEVEL UP!", `Level ${newLevel} ETL Architect`, "#8b5cf6");
            const canvasEl = document.getElementById('gamification-canvas');
            if (canvasEl) {
                spawnExplosion(canvasEl.width / 2, canvasEl.height / 2, "#8b5cf6");
            }
        }, 1000);
    }
    
    // Check and unlock badges
    setTimeout(() => {
        if (rejectionsCount === 0) {
            unlockBadge('badge-schema-shield', 'Schema Guard badge unlocked! Perfect data formatting validation.');
        }
        if (qualityScore > 90) {
            unlockBadge('badge-null-hunter', 'Null Hunter badge unlocked! Perfect missing data repair.');
        }
        // Duplicate row count from intake
        const intakeStage = (state.currentPipelineData || {}).stages?.['intake'] || {};
        if (intakeStage.output && intakeStage.output.duplicate_rows > 0) {
            unlockBadge('badge-dup-slayer', 'Duplicate Slayer badge unlocked! Removed duplicate records.');
        }
    }, 1500);
}

function unlockBadge(badgeId, message) {
    const badge = document.getElementById(badgeId);
    if (badge && badge.classList.contains('locked')) {
        badge.classList.remove('locked');
        showToast('success', message);
        
        // Canvas banner trigger
        const badgeName = badge.querySelector('span')?.textContent || "Achievement Unlocked";
        const canvasEl = document.getElementById('gamification-canvas');
        if (canvasEl) {
            spawnBanner("ACHIEVEMENT UNLOCKED!", badgeName, "#ffb703");
            spawnExplosion(canvasEl.width / 2, canvasEl.height / 2, "#ffb703");
        }
    }
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
    
    // Play "Initiate" banner
    spawnBanner("AUTONOMOUS ETL ACTIVE", "Data Pipeline Ingesting...", "#00f0ff");
    
    if (animFrameId) cancelAnimationFrame(animFrameId);
    animFrameId = requestAnimationFrame(canvasAnimationLoop);
}

function spawnBanner(title, subtitle, color = "#00f0ff") {
    canvasBanners.push({
        title: title,
        subtitle: subtitle,
        color: color,
        alpha: 0,
        scale: 0.8,
        life: 150, // frames (~2.5 seconds)
        maxLife: 150
    });
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

function spawnFloatingText(x, y, text, color = "#00f0ff") {
    canvasFloatingTexts.push({
        x: x,
        y: y,
        text: text,
        color: color,
        vy: -1.2,
        alpha: 1,
        decay: 0.012
    });
}

function canvasAnimationLoop() {
    const canvas = document.getElementById('gamification-canvas');
    if (!canvas || canvas.parentElement.style.display !== 'flex') {
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
