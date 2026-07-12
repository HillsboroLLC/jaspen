// Shared lead-capture client for the public homepage lead magnets.
//
// PRODUCTION PATH IS UNCHANGED: submitLead() POSTs to the real
// /api/v1/public/leads endpoint exactly as before. The only addition is a
// DEVELOPMENT-ONLY mock that lets us exercise the success and failure UI
// without writing to the real leads API.
//
// The mock is off by default and is hard-gated so it can never run in a
// production build:
//   1. process.env.NODE_ENV must NOT be 'production'  (always true for a
//      `react-scripts build` production bundle), AND
//   2. a mode of "success" or "fail" must be explicitly selected via one of:
//        - env:         REACT_APP_LEADS_MOCK=success | fail        (build/start)
//        - URL param:   ?leadsMock=success | fail | off            (live toggle)
//        - localStorage: jaspen_leads_mock = success | fail | off  (persisted)
//
// Precedence (dev only): URL param → localStorage → env var. A URL param is
// also written to localStorage so it survives reloads. "off" (or anything
// unrecognized) forces the REAL endpoint, so you can flip back to live without
// restarting. When no override and no env var are set, behavior is identical to
// production: the real API.
//
// See isLeadsMockEnabled()/leadsMockMode() for the UI banner that makes it
// obvious when the mock is active.

import { API_BASE } from '../../config/apiBase';

export const LEADS_ENDPOINT = `${API_BASE}/api/v1/public/leads`;
const OVERRIDE_KEY = 'jaspen_leads_mock';
const VALID = new Set(['success', 'fail']);

function isProd() {
  return process.env.NODE_ENV === 'production';
}

// Read (and persist) a dev override from the URL or localStorage. Never throws.
function readOverride() {
  if (typeof window === 'undefined') return '';
  try {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = (params.get('leadsMock') || '').trim().toLowerCase();
    if (fromUrl) {
      try {
        window.localStorage.setItem(OVERRIDE_KEY, fromUrl);
      } catch {
        /* ignore storage failures */
      }
      return fromUrl;
    }
    return (window.localStorage.getItem(OVERRIDE_KEY) || '').trim().toLowerCase();
  } catch {
    return '';
  }
}

// Returns 'success' | 'fail' | null. null means "use the real API".
export function leadsMockMode() {
  if (isProd()) return null;
  const override = readOverride();
  if (override) {
    // An explicit override always wins in dev. "off"/unknown => real API.
    return VALID.has(override) ? override : null;
  }
  const fromEnv = (process.env.REACT_APP_LEADS_MOCK || '').trim().toLowerCase();
  return VALID.has(fromEnv) ? fromEnv : null;
}

export function isLeadsMockEnabled() {
  return leadsMockMode() !== null;
}

/**
 * Submit a lead. Returns a fetch-like Response (with `.ok`) on the real path,
 * or a `{ ok, status, mocked }` object in mock-success mode. Throws in
 * mock-fail mode (to exercise network-failure handling) and on real network
 * errors, exactly like fetch.
 *
 * @param {{ email: string, source: string, marketingOptIn?: boolean, assessmentAnswers?: object, decisionStyle?: string }} lead
 */
export async function submitLead({
  email,
  source,
  marketingOptIn = false,
  assessmentAnswers,
  decisionStyle,
}) {
  const mode = leadsMockMode();
  if (mode) {
    // Simulate a little latency so the sending/disabled states are visible.
    await new Promise((resolve) => setTimeout(resolve, 450));
    if (mode === 'fail') {
      throw new Error('[dev leads mock] simulated submission failure — no data was sent');
    }
    // eslint-disable-next-line no-console
    console.info(`[dev leads mock] pretended to save lead { source: "${source}" } — nothing sent to the API`);
    return { ok: true, status: 201, mocked: true };
  }

  const payload = { email, source, marketing_opt_in: Boolean(marketingOptIn) };
  if (assessmentAnswers && typeof assessmentAnswers === 'object') {
    payload.assessment_answers = assessmentAnswers;
  }
  if (decisionStyle) {
    payload.decision_style = decisionStyle;
  }

  return fetch(LEADS_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
