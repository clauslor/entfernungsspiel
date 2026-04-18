/**
 * hCaptcha Handler
 * Manages hCaptcha integration and validation
 */

let captchaValidationToken = null;

/**
 * Initialize hCaptcha on page load
 */
function initializeCaptcha() {
    // Check if we already have a valid captcha validation in localStorage
    const storedToken = localStorage.getItem('captchaToken');
    if (storedToken) {
        captchaValidationToken = storedToken;
        hideCaptchaModal();
    } else {
        showCaptchaModal();
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
        const activeWs = (typeof ws !== 'undefined' && ws) ? ws : window.ws;
        
        // Debug logging to help troubleshoot
        console.log('WebSocket check:', {
            ws_defined: typeof ws !== 'undefined',
            window_ws_defined: typeof window.ws !== 'undefined',
            activeWs_exists: !!activeWs,
            readyState: activeWs ? activeWs.readyState : null
        });
        
        if (!activeWs || activeWs.readyState !== WebSocket.OPEN) {
            console.error('WebSocket not ready for captcha submission');
            showCaptchaError('Connection error. Try again later.');
            return;
        }

        activeWs.send(JSON.stringify({
            type: 'submit_captcha',
            data: {
                hcaptcha_token: token
            }
        }));
    } catch (error) {
        console.error('Error submitting captcha:', error);
        showCaptchaError('Connection error. Try again later.');
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
    
    showCaptchaModal();
}
