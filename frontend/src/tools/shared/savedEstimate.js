// =====================================================
// Shared saved-estimate persistence for Jaspen utilities.
// Authenticated users can save to their account (POST /api/v1/tools/estimates);
// if the endpoint is not deployed, it degrades to a local snapshot. Anonymous
// activity stays in-session only and never creates a server record.
//
// Saved scenarios are stored as labeled records and are meant to be COMPARED,
// not summed — unlike metrics across utilities are not additive.
// =====================================================

import { API_BASE } from '../../config/apiBase';

const ESTIMATES_PATH = '/api/v1/tools/estimates';

export function localKey(utilityType) {
  return `jaspen_${utilityType}_estimate_v1`;
}

export function saveLocal(utilityType, snapshot) {
  try {
    window.localStorage.setItem(
      localKey(utilityType),
      JSON.stringify({ ...snapshot, created_date: snapshot.created_date || snapshot.updated_date })
    );
    return true;
  } catch {
    return false;
  }
}

export function loadLocal(utilityType) {
  try {
    const raw = window.localStorage.getItem(localKey(utilityType));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Persist an estimate snapshot. Always keeps a local copy as a safety net.
 * @returns {Promise<{mode:'account'|'local', ok:boolean, id?:string}>}
 */
export async function saveEstimate({ authFetch, isAuthenticated, utilityType, snapshot }) {
  saveLocal(utilityType, snapshot);
  if (isAuthenticated && typeof authFetch === 'function') {
    try {
      const res = await authFetch(ESTIMATES_PATH, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(snapshot),
      });
      if (res && res.ok) {
        let data = {};
        try {
          data = await res.json();
        } catch {
          /* ignore body parse */
        }
        return { mode: 'account', ok: true, id: data.id };
      }
    } catch {
      /* fall through to local-only */
    }
  }
  return { mode: 'local', ok: true };
}

export const ESTIMATES_ENDPOINT = `${API_BASE}${ESTIMATES_PATH}`;
