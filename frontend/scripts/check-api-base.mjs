// Fails a non-production Vercel build that has no REACT_APP_API_BASE, so a
// preview/staging build can never silently fall back to the production API.
// Production builds and builds outside Vercel are unchanged.
import { pathToFileURL } from 'url';

export function checkApiBase(env = process.env) {
  const vercelEnv = String(env.VERCEL_ENV || env.REACT_APP_VERCEL_ENV || '').trim().toLowerCase();
  const apiBase = String(env.REACT_APP_API_BASE || '').trim();
  if (vercelEnv && vercelEnv !== 'production' && !apiBase) {
    return {
      ok: false,
      message: `[api-base] REACT_APP_API_BASE is not set for this ${vercelEnv} build. `
        + 'Set it in Vercel for this environment; non-production builds never fall back to the production API.',
    };
  }
  return { ok: true, message: `[api-base] ok (${vercelEnv || 'local'})` };
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const result = checkApiBase();
  if (!result.ok) {
    console.error(result.message);
    process.exit(1);
  }
  console.log(result.message);
}
