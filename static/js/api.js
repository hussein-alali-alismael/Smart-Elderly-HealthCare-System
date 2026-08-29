/**
 * Centralized API client with automatic CSRF token handling
 * - Includes CSRF token in all POST/PUT/PATCH/DELETE requests
 * - Handles 401 responses by redirecting to login
 * - Provides convenience methods for common endpoints
 */

const API = {
  /**
   * Internal method to get CSRF token from meta tag or fetch from server
   */
  async _getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const tokenFromMeta = meta ? (meta.getAttribute('content') || '').trim() : '';
    const cookieMatch = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    const tokenFromCookie = cookieMatch ? decodeURIComponent(cookieMatch[1]).trim() : '';
    const token = tokenFromMeta || tokenFromCookie;

    if (token) {
      console.log('[API] CSRF token found:', `${token.substring(0, 20)}...`);
      return token;
    }

    console.log('[API] Fetching CSRF token from server...');
    try {
      const response = await fetch('/api/csrf-token', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) {
        console.error('[API] CSRF token request failed:', response.status);
        return '';
      }

      const data = await response.json();
      const csrfToken = (data.csrf_token || '').trim();
      if (csrfToken) {
        let metaTag = document.querySelector('meta[name="csrf-token"]');
        if (!metaTag) {
          metaTag = document.createElement('meta');
          metaTag.setAttribute('name', 'csrf-token');
          document.head.appendChild(metaTag);
        }
        metaTag.setAttribute('content', csrfToken);
      }
      console.log('[API] CSRF token from server:', csrfToken ? `${csrfToken.substring(0, 20)}...` : 'EMPTY');
      return csrfToken;
    } catch (error) {
      console.error('[API] Failed to get CSRF token from server:', error);
      return '';
    }
  },

  /**
   * Core request method with CSRF token injection and error handling
   */
  async request(path, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const isModifying = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);

    let defaultHeaders = {
      Accept: 'application/json',
    };

    if (options.body && !(options.headers && Object.keys(options.headers).some(header => header.toLowerCase() === 'content-type'))) {
      defaultHeaders['Content-Type'] = 'application/json';
    }

    if (isModifying) {
      const csrfToken = await this._getCSRFToken();
      console.log(`[API] ${method} ${path} - CSRF token: ${csrfToken ? csrfToken.substring(0, 20) + '...' : 'EMPTY'}`);
      if (csrfToken) {
        defaultHeaders['X-CSRFToken'] = csrfToken;
      }
    }

    const finalOptions = {
      credentials: 'same-origin',
      headers: { ...defaultHeaders, ...(options.headers || {}) },
      ...options,
    };

    const response = await fetch(path, finalOptions);
    const contentType = response.headers.get('content-type');
    let body = {};

    if (contentType && contentType.includes('application/json')) {
      body = await response.json().catch(() => ({}));
    }

    // Handle 401 by redirecting to login
    if (response.status === 401) {
      if (!window.location.pathname.startsWith('/login') && 
          !window.location.pathname.startsWith('/signup')) {
        window.location.href = '/login';
      }
      return { error: 'Authentication required' };
    }

    // Throw error for non-OK responses
    if (!response.ok) {
      const error = new Error(body.error || `Request failed (${response.status})`);
      error.status = response.status;
      error.response = body;
      throw error;
    }

    return body;
  },

  // Authentication endpoints
  login: (openId) => API.request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ openId }),
  }),

  signup: (name, email) => API.request('/api/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ name, email }),
  }),

  logout: () => API.request('/api/auth/logout', { method: 'POST' }),

  getCurrentUser: () => API.request('/api/auth/me'),

  // Resident endpoints
  residents: () => API.request('/api/residents'),

  createResident: (payload) => API.request('/api/patients', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),

  getResident: (id) => API.request(`/api/residents/${id}`),

  updateResident: (id, payload) => API.request(`/api/residents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }),

  deleteResident: (id) => API.request(`/api/residents/${id}`, { method: 'DELETE' }),

  // Medication endpoints
  medications: () => API.request('/api/medications'),

  createMedication: (payload) => API.request('/api/medications', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),

  getMedication: (id) => API.request(`/api/medications/${id}`),

  updateMedication: (id, payload) => API.request(`/api/medications/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }),

  deleteMedication: (id) => API.request(`/api/medications/${id}`, { method: 'DELETE' }),

  // Medication schedule endpoints
  getMedicationSchedules: (medicationId) => 
    API.request(`/api/medications/${medicationId}/schedules`),

  getScheduleTimes: (medicationId) => 
    API.request(`/api/medications/${medicationId}/schedule-times`),

  createScheduleTime: (medicationId, payload) => API.request(
    `/api/medications/${medicationId}/schedule-times`,
    { method: 'POST', body: JSON.stringify(payload) }
  ),

  updateScheduleTime: (medicationId, scheduleTimeId, payload) => API.request(
    `/api/medications/${medicationId}/schedule-times/${scheduleTimeId}`,
    { method: 'PUT', body: JSON.stringify(payload) }
  ),

  deleteScheduleTime: (medicationId, scheduleTimeId) => API.request(
    `/api/medications/${medicationId}/schedule-times/${scheduleTimeId}`,
    { method: 'DELETE' }
  ),

  // Notification endpoints
  notifications: () => API.request('/api/notifications'),

  getNotification: (id) => API.request(`/api/notifications/${id}`),

  markNotificationRead: (id) => API.request(`/api/notifications/${id}/read`, { method: 'POST' }),

  deleteNotification: (id) => API.request(`/api/notifications/${id}`, { method: 'DELETE' }),

  // Medication intakes
  getIntakes: () => API.request('/api/medication-intakes'),

  recordIntake: (payload) => API.request('/api/medication-intakes', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
};

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = API;
}
