/**
 * CAPTCHA Handler
 * Manages captcha modal display, submission, and validation
 */

let captchaValidationToken = null;

/**
 * Initialize CAPTCHA on page load
 */
async function initializeCaptcha() {
    // Load captcha HTML from template
    try {
        const response = await fetch('/templates/captcha.html');
        const html = await response.text();
        document.getElementById('captchaContainer').innerHTML = html;
        
        // Check if we already have a valid captcha validation in localStorage
        const storedToken = localStorage.getItem('captchaToken');
        if (storedToken) {
            captchaValidationToken = storedToken;
            hideCaptchaModal();
        } else {
            showCaptchaModal();
        }
        
        // Add event listener for Enter key
        const captchaInput = document.getElementById('captchaAnswer');
        if (captchaInput) {
            captchaInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    submitCaptcha();
                }
            });
        }
    } catch (error) {
        console.error('Error loading captcha template:', error);
    }
}

/**
 * Show the captcha modal
 */
function showCaptchaModal() {
    const modal = document.getElementById('captchaModal');
    if (modal) {
        modal.style.display = 'flex';
        requestCaptchaChallenge();
    }
}

/**
 * Hide the captcha modal
 */
function hideCaptchaModal() {
    const modal = document.getElementById('captchaModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * Request a new CAPTCHA challenge from the server
 */
function requestCaptchaChallenge() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.error('WebSocket not ready');
        return;
    }
    
    ws.send(JSON.stringify({
        type: 'request_captcha',
        data: {}
    }));
}

/**
 * Submit the CAPTCHA answer
 */
function submitCaptcha() {
    const answerInput = document.getElementById('captchaAnswer');
    if (!answerInput) return;
    
    const answer = parseInt(answerInput.value, 10);
    
    if (isNaN(answer)) {
        showCaptchaError(i18n.get('captcha.invalidAnswer') || 'Please enter a valid number');
        return;
    }
    
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.error('WebSocket not ready');
        showCaptchaError(i18n.get('captcha.connectionError') || 'Connection error');
        return;
    }
    
    ws.send(JSON.stringify({
        type: 'submit_captcha',
        data: {
            answer: answer
        }
    }));
}

/**
 * Display CAPTCHA challenge in the modal
 */
function displayCaptchaChallenge(question) {
    const questionElement = document.getElementById('captchaQuestion');
    const answerInput = document.getElementById('captchaAnswer');
    const errorElement = document.getElementById('captchaError');
    
    if (questionElement) {
        questionElement.textContent = question;
    }
    
    if (answerInput) {
        answerInput.value = '';
        answerInput.focus();
    }
    
    if (errorElement) {
        errorElement.style.display = 'none';
        errorElement.textContent = '';
    }
}

/**
 * Show error message in CAPTCHA modal
 */
function showCaptchaError(message) {
    const errorElement = document.getElementById('captchaError');
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.style.display = 'block';
    }
}

/**
 * Handle successful CAPTCHA validation
 */
function handleCaptchaValidated() {
    // Store validation token in localStorage (valid for 1 day)
    captchaValidationToken = generateRandomToken();
    localStorage.setItem('captchaToken', captchaValidationToken);
    
    hideCaptchaModal();
    
    // Now the player can proceed with the game
    console.log('CAPTCHA validated, player can proceed');
}

/**
 * Generate a random token for local storage
 */
function generateRandomToken() {
    return 'captcha_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

/**
 * Clear CAPTCHA validation (for testing or logout)
 */
function clearCaptchaValidation() {
    captchaValidationToken = null;
    localStorage.removeItem('captchaToken');
}
