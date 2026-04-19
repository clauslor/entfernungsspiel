/**
 * hCaptcha Handler
 * Manages hCaptcha integration and validation
 */

let captchaValidationToken = null;

function updateCaptchaStatusUi(state) {
    const statusRow = document.getElementById('captchaStatusRow');
    const badge = document.getElementById('captchaStatusBadge');
    const verifyBtn = document.getElementById('captchaVerifyBtn');
    if (!badge || !verifyBtn) return;

    badge.classList.remove('is-required', 'is-ok');

    if (state === 'required') {
        if (statusRow) {
            statusRow.hidden = false;
        }
        badge.classList.add('is-required');
        badge.setAttribute('data-i18n', 'captcha.statusRequired');
        if (typeof t === 'function') {
            badge.textContent = t('captcha.statusRequired');
        }
        verifyBtn.hidden = false;
    } else if (state === 'ok') {
        if (statusRow) {
            statusRow.hidden = true;
        }
        badge.classList.add('is-ok');
        badge.setAttribute('data-i18n', 'captcha.statusReady');
        if (typeof t === 'function') {
            badge.textContent = t('captcha.statusReady');
        }
        verifyBtn.hidden = true;
    } else {
        if (statusRow) {
            statusRow.hidden = false;
        }
        badge.setAttribute('data-i18n', 'captcha.statusLazy');
        if (typeof t === 'function') {
            badge.textContent = t('captcha.statusLazy');
        }
        verifyBtn.hidden = true;
    }
}

/**
 * Initialize hCaptcha on page load
 */
function initializeCaptcha() {
    // Wait for server lobby info before showing a required/verified status.
    captchaValidationToken = localStorage.getItem('captchaToken');
    updateCaptchaStatusUi('lazy');

    // Do not force modal on page load; only show when a protected action actually needs it.
    hideCaptchaModal();
}

function syncCaptchaRequirement(captchaRequired) {
    if (captchaRequired) {
        captchaValidationToken = null;
        localStorage.removeItem('captchaToken');
        updateCaptchaStatusUi('required');
    } else {
        // If no verification is currently required, keep the UI in neutral mode.
        captchaValidationToken = null;
        localStorage.removeItem('captchaToken');
        updateCaptchaStatusUi('lazy');
        hideCaptchaModal();
    }
}

/**
 * Show captcha modal
 */
function showCaptchaModal() {
    const modal = document.getElementById('captchaModal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

/**
 * Hide captcha modal
 */
function hideCaptchaModal() {
    const modal = document.getElementById('captchaModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * Submit the hCaptcha token to the server
 */
function submitCaptcha() {
    if (typeof hcaptcha === 'undefined') {
        showCaptchaError('hCaptcha could not be loaded. Please reload the page.');
        return;
    }

    // Get the hCaptcha token
    const token = hcaptcha.getResponse();
    
    if (!token) {
        showCaptchaError('Please complete the hCaptcha verification.');
        return;
    }
    
    try {
        // Try to get WebSocket from multiple sources
        const activeWs = (typeof ws !== 'undefined' && ws) ? ws : (window.ws || null);
        
        // Debug logging to help troubleshoot
        console.log('WebSocket check at captcha submit:', {
            'local ws defined': typeof ws !== 'undefined',
            'window.ws defined': typeof window.ws !== 'undefined',
            'activeWs exists': !!activeWs,
            'activeWs readyState': activeWs ? activeWs.readyState : 'N/A',
            'OPEN constant': WebSocket.OPEN
        });
        
        if (!activeWs) {
            console.error('WebSocket not found in either ws or window.ws');
            showCaptchaError('Connection not established. Please refresh and try again.');
            return;
        }

        if (activeWs.readyState !== WebSocket.OPEN) {
            console.error('WebSocket exists but not in OPEN state. State:', activeWs.readyState);
            showCaptchaError('Connection error. Please wait a moment and try again.');
            return;
        }

        console.log('Sending captcha token via WebSocket');
        activeWs.send(JSON.stringify({
            type: 'submit_captcha',
            data: {
                hcaptcha_token: token
            }
        }));
    } catch (error) {
        console.error('Error submitting captcha:', error, error.stack);
        showCaptchaError('Error submitting captcha. Please try again.');
    }
}

/**
 * Display an error message in the captcha modal
 */
function showCaptchaError(message) {
    const errorDiv = document.getElementById('captchaError');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
}

/**
 * Handle successful captcha validation
 */
function handleCaptchaValidated() {
    // Generate and store validation token
    const token = 'captcha_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    captchaValidationToken = token;
    localStorage.setItem('captchaToken', token);
    
    // Reset hCaptcha widget
    if (typeof hcaptcha !== 'undefined') {
        hcaptcha.reset();
    }
    
    // Hide modal
    hideCaptchaModal();
    updateCaptchaStatusUi('ok');
    
    // Clear any error messages
    const errorDiv = document.getElementById('captchaError');
    if (errorDiv) {
        errorDiv.style.display = 'none';
    }
}

/**
 * Clear captcha validation (logout/reset)
 */
function clearCaptchaValidation() {
    captchaValidationToken = null;
    localStorage.removeItem('captchaToken');
    
    // Reset hCaptcha widget
    if (typeof hcaptcha !== 'undefined') {
        hcaptcha.reset();
    }
    updateCaptchaStatusUi('required');
    
    showCaptchaModal();
}
