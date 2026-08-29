/**
 * Authentication form handlers for login and signup
 * - Handles form submission with CSRF tokens
 * - Redirects to dashboard on success
 * - Shows error messages on failure
 */

document.addEventListener('DOMContentLoaded', function() {
  const loginForm = document.getElementById('loginPageForm');
  const signupForm = document.getElementById('signupPageForm');

  if (loginForm) {
    loginForm.addEventListener('submit', handleLoginSubmit);
  }

  if (signupForm) {
    signupForm.addEventListener('submit', handleSignupSubmit);
  }
});

/**
 * Handle login form submission
 */
async function handleLoginSubmit(event) {
  event.preventDefault();
  
  const openId = document.getElementById('loginOpenId')?.value?.trim() || 
                 document.getElementById('openId')?.value?.trim();
  const errorDiv = document.getElementById('authError');

  if (!openId) {
    if (errorDiv) {
      errorDiv.textContent = 'Please enter your user ID';
      errorDiv.style.display = 'block';
    }
    return;
  }

  try {
    const response = await API.login(openId);
    
    if (response.error) {
      if (errorDiv) {
        errorDiv.textContent = response.error;
        errorDiv.style.display = 'block';
      }
      return;
    }

    // Success - redirect to dashboard
    window.location.href = '/';
  } catch (error) {
    if (errorDiv) {
      errorDiv.textContent = error.message || 'Login failed. Please try again.';
      errorDiv.style.display = 'block';
    }
    console.error('Login error:', error);
  }
}

/**
 * Handle signup form submission
 */
async function handleSignupSubmit(event) {
  event.preventDefault();

  const name = document.getElementById('signupName')?.value?.trim() || 
               document.getElementById('pName')?.value?.trim();
  const email = document.getElementById('signupEmail')?.value?.trim() || 
                document.getElementById('email')?.value?.trim();
  const errorDiv = document.getElementById('authError');

  if (!name || !email) {
    if (errorDiv) {
      errorDiv.textContent = 'Please fill in all fields';
      errorDiv.style.display = 'block';
    }
    return;
  }

  // Basic email validation
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(email)) {
    if (errorDiv) {
      errorDiv.textContent = 'Please enter a valid email address';
      errorDiv.style.display = 'block';
    }
    return;
  }

  try {
    const response = await API.signup(name, email);

    if (response.error) {
      if (errorDiv) {
        errorDiv.textContent = response.error;
        errorDiv.style.display = 'block';
      }
      return;
    }

    // Success - redirect to dashboard
    window.location.href = '/';
  } catch (error) {
    if (errorDiv) {
      errorDiv.textContent = error.message || 'Signup failed. Please try again.';
      errorDiv.style.display = 'block';
    }
    console.error('Signup error:', error);
  }
}

/**
 * Navigate to login page
 */
function goToLogin() {
  window.location.href = '/login';
}

/**
 * Navigate to signup page
 */
function goToSignup() {
  window.location.href = '/signup';
}
