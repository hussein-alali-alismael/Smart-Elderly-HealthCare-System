const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

async function getCsrfToken(forceRefresh = false) {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const fromMeta = meta ? (meta.getAttribute('content') || '').trim() : '';
  if (fromMeta && !forceRefresh) return fromMeta;

  try {
    const response = await fetch('/api/csrf-token', {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });

    if (!response.ok) {
      return '';
    }

    const data = await response.json();
    const token = (data.csrf_token || '').trim();
    if (token) {
      let tag = document.querySelector('meta[name="csrf-token"]');
      if (!tag) {
        tag = document.createElement('meta');
        tag.setAttribute('name', 'csrf-token');
        document.head.appendChild(tag);
      }
      tag.setAttribute('content', token);
    }

    return token;
  } catch (error) {
    console.error('Failed to fetch CSRF token', error);
    return '';
  }
}

async function request(path, options = {}, csrfRetry = false) {
  const method = (options.method || 'GET').toUpperCase();
  const isModifying = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);

  const headers = {
    Accept: 'application/json',
    ...(options.headers || {}),
  };

  if (options.body && !Object.keys(headers).some((key) => key.toLowerCase() === 'content-type')) {
    headers['Content-Type'] = 'application/json';
  }

  if (isModifying) {
    const csrfToken = await getCsrfToken(csrfRetry);
    if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken;
    }
  }

  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...options,
    headers,
  });

  const contentType = response.headers.get('content-type') || '';
  let payload = {};
  if (contentType.includes('application/json')) {
    payload = await response.json().catch(() => ({}));
  }

  if (response.status === 401) {
    window.location.href = '/login';
    return { error: 'Authentication required' };
  }

  if (!response.ok) {
    if (
      response.status === 403 &&
      payload.error === 'CSRF token required.' &&
      isModifying &&
      !csrfRetry
    ) {
      return request(path, options, true);
    }
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.response = payload;
    throw error;
  }

  return payload;
}

export const API = {
  login: async (openId, password) => {
    const response = await request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ openId, password }),
    });
    await getCsrfToken(true);
    return response;
  },

  signup: async (name, email, password) => {
    const response = await request('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ name, email, password }),
    });
    await getCsrfToken(true);
    return response;
  },

  logout: () => request('/api/auth/logout', { method: 'POST' }),

  getCurrentUser: () => request('/api/auth/me'),

  getResidents: () => request('/api/residents'),
  createResident: (payload) => request('/api/residents', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  getResident: (id) => request(`/api/residents/${id}`),
  updateResident: (id, payload) => request(`/api/residents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }),
  deleteResident: (id) => request(`/api/residents/${id}`, { method: 'DELETE' }),

  getMedications: () => request('/api/medications'),
  createMedication: (payload) => request('/api/medications', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  updateMedication: (id, payload) => request(`/api/medications/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }),
  deleteMedication: (id) => request(`/api/medications/${id}`, { method: 'DELETE' }),

  getSchedules: () => request('/api/medication-schedules'),
  createSchedule: (payload) => request('/api/medication-schedules', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  updateSchedule: (id, payload) => request(`/api/medication-schedules/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }),
  deleteSchedule: (id) => request(`/api/medication-schedules/${id}`, { method: 'DELETE' }),

  getScheduleTimes: () => request('/api/medication-schedule-times'),
  createScheduleTime: (scheduleId, payload) => request(`/api/medication-schedules/${scheduleId}/times`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  updateScheduleTime: (id, payload) => request(`/api/medication-schedule-times/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  }),
  deleteScheduleTime: (id) => request(`/api/medication-schedule-times/${id}`, { method: 'DELETE' }),

  getNotifications: () => request('/api/notifications'),
  markNotificationRead: (id) => request(`/api/notifications/${id}/read`, { method: 'PATCH' }),

  getIntakes: () => request('/api/medication-intakes'),

  getFalls: () => request('/api/fall-incidents'),

  getCameraConfig: () => request('/api/camera-config'),
};

export default API;
