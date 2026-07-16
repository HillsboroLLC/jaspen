// =====================================================
// Cost of Turnover — Saved-estimate persistence
// A minimal, extensible saved-estimate client. For authenticated users it POSTs
// to the tools estimates endpoint; if that endpoint is not yet deployed (or the
// request fails) it degrades gracefully to a local snapshot so the user never
// loses their work. Anonymous activity is only ever kept in this browser
// session — it never creates a server record without an account.
//
// The snapshot shape matches the backend SavedEstimate model:
//   utility_type, calculator_version, benchmark_version, user_inputs,
//   defaults_used, result_breakdown, total_low/mid/high, built_using, timestamps.
// =====================================================

import { API_BASE } from '../../../config/apiBase';
import { CALC_VERSION } from '../engine/version';
import { BENCHMARK_VERSION } from '../data/benchmarks';
import { UTILITY_SOURCE } from './analytics';

const LOCAL_KEY = 'jaspen_cot_estimate_v1';
const ESTIMATES_ENDPOINT = `${API_BASE}/api/v1/tools/estimates`;

export const UTILITY_TYPE = 'cost_of_turnover';

// Build the persistable snapshot from engine result + raw inputs/overrides.
export function buildSnapshot({ inputs, overrides, defaults, result, builtUsing }) {
  return {
    utility_type: UTILITY_TYPE,
    source: UTILITY_SOURCE,
    calculator_version: CALC_VERSION,
    benchmark_version: BENCHMARK_VERSION,
    user_inputs: inputs,
    overrides: overrides || {},
    defaults_used: defaults || {},
    result_breakdown: (result.components || []).map((c) => ({
      key: c.key,
      label: c.label,
      category: c.category,
      low: Math.round(c.low),
      mid: Math.round(c.mid),
      high: Math.round(c.high),
      pctOfTotal: Number(c.pctOfTotal?.toFixed(1)),
    })),
    total_low: Math.round(result.total.low),
    total_mid: Math.round(result.total.mid),
    total_high: Math.round(result.total.high),
    built_using: builtUsing,
    updated_date: new Date().toISOString(),
  };
}

export function saveLocal(snapshot) {
  try {
    window.localStorage.setItem(LOCAL_KEY, JSON.stringify({ ...snapshot, created_date: snapshot.created_date || snapshot.updated_date }));
    return true;
  } catch {
    return false;
  }
}

export function loadLocal() {
  try {
    const raw = window.localStorage.getItem(LOCAL_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearLocal() {
  try {
    window.localStorage.removeItem(LOCAL_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Persist an estimate. For authenticated users, tries the account endpoint and
 * associates the estimate with the existing account (server reads the session).
 * Always keeps a local copy as a safety net.
 *
 * @param {{ authFetch?: Function, isAuthenticated?: boolean, snapshot: object }} args
 * @returns {Promise<{ mode: 'account'|'local', id?: string, ok: boolean }>}
 */
export async function saveEstimate({ authFetch, isAuthenticated, snapshot }) {
  saveLocal(snapshot);
  if (isAuthenticated && typeof authFetch === 'function') {
    try {
      const res = await authFetch('/api/v1/tools/estimates', {
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

export { ESTIMATES_ENDPOINT };
