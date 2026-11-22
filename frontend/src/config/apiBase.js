// frontend/src/config/apiBase.js
//
// The production API is used only by production builds (and, as before, by
// builds that run outside Vercel with no API configured). Any other Vercel
// build (preview/staging, development) must name its API explicitly: with no
// REACT_APP_API_BASE it resolves to '' so requests stay relative to the page
// and can never reach production. scripts/check-api-base.mjs fails those
// builds before they start.
export const PRODUCTION_API_BASE = 'https://api.jaspen.ai';

export function resolveApiBase(env = {}) {
  const configured = String(env.REACT_APP_API_BASE || '').trim();
  if (configured) return configured;
  const vercelEnv = String(env.REACT_APP_VERCEL_ENV || '').trim().toLowerCase();
  if (vercelEnv && vercelEnv !== 'production') return '';
  return PRODUCTION_API_BASE;
}

export const API_BASE = resolveApiBase({
  REACT_APP_API_BASE: process.env.REACT_APP_API_BASE,
  REACT_APP_VERCEL_ENV: process.env.REACT_APP_VERCEL_ENV,
});

// Aliases (so ANY consumer name works, and Webpack stops erroring)
export const PM_API_BASE = API_BASE;
export const API_URL = API_BASE;
export const BASE_URL = API_BASE;

export default API_BASE;
