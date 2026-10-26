const REDACTED = '[REDACTED]';
const SHARE_PATH = /(\/(?:s|api\/v1\/shares\/(?:public|manage))\/)[^/?#\s]+/gi;
const CREDENTIAL_PATTERNS = [
  /\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi,
  /\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b/g,
  /\b(?:gh[pousr]_|sk-(?:proj-)?|sk-ant-|(?:sk|rk)_live_|whsec_|xox[baprs]-)[A-Za-z0-9_-]{12,}\b/g,
];

export function redactSentryText(value) {
  let text = String(value || '').replace(SHARE_PATH, `$1${REDACTED}`);
  CREDENTIAL_PATTERNS.forEach((pattern) => {
    text = text.replace(pattern, REDACTED);
  });
  return text;
}

function safeRequest(request = {}) {
  const headers = request.headers || {};
  const allowedHeaders = {};
  Object.entries(headers).forEach(([name, value]) => {
    if (['content-type', 'user-agent'].includes(String(name).toLowerCase())) {
      allowedHeaders[name] = redactSentryText(value);
    }
  });
  return {
    ...(request.method ? { method: request.method } : {}),
    ...(request.url ? { url: redactSentryText(request.url) } : {}),
    ...(Object.keys(allowedHeaders).length ? { headers: allowedHeaders } : {}),
  };
}

export function scrubSentryEvent(event = {}) {
  const sanitized = { ...event };
  if (event.request) sanitized.request = safeRequest(event.request);
  if (event.user) sanitized.user = event.user.id == null ? {} : { id: event.user.id };
  if (event.transaction) sanitized.transaction = redactSentryText(event.transaction);
  if (event.exception?.values) {
    sanitized.exception = {
      ...event.exception,
      values: event.exception.values.map((item) => ({
        ...item,
        value: 'Exception details suppressed',
      })),
    };
  }
  if (event.message) sanitized.message = 'Application error captured';
  delete sanitized.extra;
  delete sanitized.breadcrumbs;
  return sanitized;
}

export function scrubSentryBreadcrumb(breadcrumb) {
  if (!breadcrumb) return breadcrumb;
  const category = String(breadcrumb.category || '').toLowerCase();
  const type = String(breadcrumb.type || '').toLowerCase();
  if (category === 'console') {
    return { ...breadcrumb, message: 'Console details suppressed', data: undefined };
  }
  if (category.includes('fetch') || category.includes('xhr') || type === 'http') {
    const data = breadcrumb.data || {};
    return {
      ...breadcrumb,
      message: undefined,
      data: {
        ...(data.method ? { method: data.method } : {}),
        ...(data.status_code != null ? { status_code: data.status_code } : {}),
        ...(data.url ? { url: redactSentryText(data.url) } : {}),
      },
    };
  }
  return {
    ...breadcrumb,
    message: undefined,
    data: breadcrumb.data?.url ? { url: redactSentryText(breadcrumb.data.url) } : undefined,
  };
}

export { REDACTED };
