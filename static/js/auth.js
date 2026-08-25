async function submitAuth(path, payload) {
    const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || 'تعذر إكمال العملية');
    window.location.href = '/';
}

document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginPageForm');
    const signupForm = document.getElementById('signupPageForm');
    const error = document.getElementById('authError');

    loginForm?.addEventListener('submit', async event => {
        event.preventDefault();
        error.textContent = '';
        try {
            await submitAuth('/api/auth/login', { openId: document.getElementById('loginIdentity').value.trim() });
        } catch (exception) { error.textContent = exception.message; }
    });

    signupForm?.addEventListener('submit', async event => {
        event.preventDefault();
        error.textContent = '';
        try {
            await submitAuth('/api/auth/signup', {
                name: document.getElementById('signupName').value.trim(),
                email: document.getElementById('signupEmail').value.trim()
            });
        } catch (exception) { error.textContent = exception.message; }
    });
});
