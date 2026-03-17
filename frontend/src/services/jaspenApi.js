/* eslint-disable no-console */

// Import apiBase in a way that works whether it uses named exports or default export.
import * as apiBaseModule from '../config/apiBase';
import { authFetch, buildAuthHeaders } from '../shared/auth/http';

// Resolve base URL from whichever export exists.
// Add keys here if your apiBase uses different names.
const PM_API_BASE =
  apiBaseModule.PM_API_BASE ||
  apiBaseModule.API_BASE ||
  apiBaseModule.API_URL ||
  apiBaseModule.BASE_URL ||
  apiBaseModule.default;

if (!PM_API_BASE) {
  // Fail fast with a clear error instead of silent wrong URLs.
  throw new Error(
    'API base URL not found. Update ../config/apiBase to export one of: PM_API_BASE, API_BASE, API_URL, BASE_URL, or a default export.'
  );
}

function getAuthHeaders() {
  return buildAuthHeaders();
}

async function httpJson(path, { method = 'GET', body } = {}) {
  const url = `${PM_API_BASE}${path}`;
  const headers = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
  };

  const res = await authFetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text || null;
  }

  if (!res.ok) {
    const msg =
      (data && data.error) ||
      (data && data.detail) ||
      res.statusText ||
      'Request failed';
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }

  return data;
}

export const jasApi = {
  // Bundle = source of truth
  getThreadBundle(threadId, { msgLimit = 50, scnLimit = 50 } = {}) {
    return httpJson(
      `/api/v1/strategy/threads/${encodeURIComponent(
        threadId
      )}/bundle?msg_limit=${msgLimit}&scn_limit=${scnLimit}`
    );
  },

  // Messages
  createMessage(threadId, { role = 'user', text }) {
    return httpJson(
      `/api/v1/strategy/threads/${encodeURIComponent(threadId)}/messages`,
      {
        method: 'POST',
        body: { role, content: { text } },
      }
    );
  },

  // Analyze
  analyze(payload) {
    return httpJson(`/api/v1/strategy/analyze`, {
      method: 'POST',
      body: payload,
    });
  },

  // Scenarios
  createScenario(threadId, { deltas, label, session_id }) {
    return httpJson(
      `/api/v1/strategy/threads/${encodeURIComponent(threadId)}/scenarios`,
      {
        method: 'POST',
        body: { deltas, label, session_id },
      }
    );
  },

  updateScenario(threadId, scenarioId, { deltas, label }) {
    return httpJson(
      `/api/v1/strategy/scenarios/${encodeURIComponent(
        scenarioId
      )}?thread_id=${encodeURIComponent(threadId)}`,
      {
        method: 'PATCH',
        body: {
          ...(deltas !== undefined ? { deltas } : {}),
          ...(label !== undefined ? { label } : {}),
        },
      }
    );
  },
};
