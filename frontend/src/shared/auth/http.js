import { API_BASE } from '../../config/apiBase';

function cookieMap() {
  return String(document.cookie || '')
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean)
    .reduce((acc, part) => {
      const index = part.indexOf('=');
      if (index <= 0) return acc;
      const key = part.slice(0, index);
      const value = part.slice(index + 1);
      acc[key] = value;
      return acc;
    }, {});
}

export function getCsrfToken() {
  const cookies = cookieMap();
  return (
    cookies.csrf_access_token ||
    cookies.csrf_token ||
    cookies['XSRF-TOKEN'] ||
    ''
  );
}

export function buildAuthHeaders(headers = {}, method = 'GET') {
  const next = { ...(headers || {}) };
  const upperMethod = String(method || 'GET').toUpperCase();

  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(upperMethod)) {
    const csrfToken = getCsrfToken();
    if (csrfToken && !next['X-CSRF-TOKEN']) {
      next['X-CSRF-TOKEN'] = decodeURIComponent(csrfToken);
    }
  }

  return next;
}

export function authFetch(pathOrUrl, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const url = String(pathOrUrl || '').startsWith('http')
    ? pathOrUrl
    : `${API_BASE}${pathOrUrl}`;

  return fetch(url, {
    ...options,
    method,
    credentials: 'include',
    headers: buildAuthHeaders(options.headers || {}, method),
  });
}
