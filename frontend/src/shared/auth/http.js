import { API_BASE } from '../../config/apiBase';

const SESSION_EXPIRED_EVENT = 'jas:session-expired';
const SERVER_ERROR_EVENT = 'jas:server-error';
const CREDITS_EXHAUSTED_EVENT = 'jas:thinking-power-exhausted';

let lastSessionExpiredNoticeAt = 0;
let lastServerErrorNoticeAt = 0;
let lastCreditsExhaustedNoticeAt = 0;

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
  const request = fetch(url, {
    ...options,
    method,
    credentials: 'include',
    headers: buildAuthHeaders(options.headers || {}, method),
  });

  return request.then((response) => {
    const lowerUrl = String(url || '').toLowerCase();
    const skipUnauthorizedNotice = [
      '/api/v1/auth/login',
      '/api/v1/auth/signup',
      '/api/v1/auth/forgot-password',
      '/api/v1/auth/reset-password',
      '/api/v1/auth/mfa/setup',
      '/api/v1/auth/mfa/verify',
      '/api/v1/auth/mfa/challenge',
      '/api/v1/auth/google/start',
      '/api/v1/auth/google/callback',
    ].some((segment) => lowerUrl.includes(segment));

    const now = Date.now();
    if (response.status === 401 && !skipUnauthorizedNotice && now - lastSessionExpiredNoticeAt > 2000) {
      lastSessionExpiredNoticeAt = now;
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, {
        detail: { status: 401, url },
      }));
    }

    if (response.status >= 500 && response.status <= 599 && now - lastServerErrorNoticeAt > 2000) {
      lastServerErrorNoticeAt = now;
      window.dispatchEvent(new CustomEvent(SERVER_ERROR_EVENT, {
        detail: { status: response.status, url },
      }));
    }
    if (response.status === 402 && now - lastCreditsExhaustedNoticeAt > 1500) {
      response.clone().json().then((data) => {
        const code = String(data?.code || '').trim().toLowerCase();
        if (
          code === 'credits_exhausted'
          || code === 'insufficient_credits'
          || code === 'thinking_power_exhausted'
        ) {
          lastCreditsExhaustedNoticeAt = Date.now();
          window.dispatchEvent(new CustomEvent(CREDITS_EXHAUSTED_EVENT, {
            detail: {
              status: 402,
              url,
              code,
              message: data?.error || "You've reached your monthly thinking power.",
              upgradeUrl: data?.upgrade_url || '/account?tab=billing',
            },
          }));
        }
      }).catch(() => {});
    }

    return response;
  });
}

export const AUTH_EVENTS = {
  SESSION_EXPIRED_EVENT,
  SERVER_ERROR_EVENT,
  CREDITS_EXHAUSTED_EVENT,
};
