import { getCsrfToken, buildAuthHeaders } from './http';

function setCookies(pairs) {
  document.cookie.split(';').forEach((part) => {
    const name = part.split('=')[0].trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });
  Object.entries(pairs).forEach(([k, v]) => { document.cookie = `${k}=${v}; path=/`; });
}

describe('CSRF cookie selection', () => {
  test('production (no configured name) keeps reading csrf_access_token', () => {
    setCookies({ csrf_access_token: 'prod-token' });
    expect(getCsrfToken('')).toBe('prod-token');
    expect(buildAuthHeaders({}, 'POST')['X-CSRF-TOKEN']).toBe('prod-token');
  });

  test('production ignores a staging-named cookie', () => {
    setCookies({ staging_csrf_access_token: 'staging-token' });
    expect(getCsrfToken('')).toBe('');
  });

  test('staging reads only its own cookie, never production\'s', () => {
    setCookies({ csrf_access_token: 'prod-token', staging_csrf_access_token: 'staging-token' });
    expect(getCsrfToken('staging_csrf_access_token')).toBe('staging-token');
  });

  test('staging sends no token rather than falling back to production\'s', () => {
    setCookies({ csrf_access_token: 'prod-token' });
    expect(getCsrfToken('staging_csrf_access_token')).toBe('');
  });
});
