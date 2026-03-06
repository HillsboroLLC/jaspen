// =====================================================
// File: src/services/api.js
// Purpose: Shared API wrapper (auth + billing)
// Notes: Uses API_BASE so local/staging/prod all work.
// =====================================================

import { API_BASE } from '../config/apiBase';

async function jsonOrThrow(res) {
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }

  if (!res.ok) {
    const msg = data?.error || data?.detail || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

const API = {
  login: (creds) =>
    fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(creds),
      credentials: 'include',
      cache: 'no-store',
    }).then(jsonOrThrow),

  signup: (creds) =>
    fetch(`${API_BASE}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(creds),
      credentials: 'include',
      cache: 'no-store',
    }).then(jsonOrThrow),

  createPaymentIntent: (amount) =>
    fetch(`${API_BASE}/api/billing/create-payment-intent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount }),
      credentials: 'include',
      cache: 'no-store',
    }).then(jsonOrThrow),
};

export default API;
export { API_BASE };
