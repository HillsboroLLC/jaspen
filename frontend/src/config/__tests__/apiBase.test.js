import { spawnSync } from 'child_process';
import path from 'path';
import { resolveApiBase, PRODUCTION_API_BASE } from '../apiBase';

describe('resolveApiBase', () => {
  it('keeps the production default for production builds', () => {
    expect(resolveApiBase({ REACT_APP_VERCEL_ENV: 'production' })).toBe(PRODUCTION_API_BASE);
  });

  it('keeps the production default outside Vercel (unchanged behavior)', () => {
    expect(resolveApiBase({})).toBe(PRODUCTION_API_BASE);
  });

  it.each(['preview', 'development', 'Preview'])('never returns the production API for a %s build with no API set', (env) => {
    const base = resolveApiBase({ REACT_APP_VERCEL_ENV: env });
    expect(base).toBe('');
    expect(base).not.toContain('api.jaspen.ai');
  });

  it('uses the configured API whenever one is set', () => {
    expect(resolveApiBase({ REACT_APP_VERCEL_ENV: 'preview', REACT_APP_API_BASE: 'https://api-staging.jaspen.ai' }))
      .toBe('https://api-staging.jaspen.ai');
    expect(resolveApiBase({ REACT_APP_API_BASE: 'http://localhost:8000' })).toBe('http://localhost:8000');
  });
});

describe('scripts/check-api-base.mjs (prebuild)', () => {
  const script = path.resolve(__dirname, '../../../scripts/check-api-base.mjs');
  const run = (env) => spawnSync(process.execPath, [script], {
    env: { PATH: process.env.PATH, ...env },
    encoding: 'utf8',
  });

  it('fails a preview build with no REACT_APP_API_BASE', () => {
    const result = run({ VERCEL_ENV: 'preview' });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain('REACT_APP_API_BASE is not set');
  });

  it('fails when only the exposed REACT_APP_VERCEL_ENV says preview', () => {
    expect(run({ REACT_APP_VERCEL_ENV: 'preview' }).status).toBe(1);
  });

  it('passes a preview build with the staging API set', () => {
    expect(run({ VERCEL_ENV: 'preview', REACT_APP_API_BASE: 'https://api-staging.jaspen.ai' }).status).toBe(0);
  });

  it('passes production and local builds without REACT_APP_API_BASE (unchanged)', () => {
    expect(run({ VERCEL_ENV: 'production' }).status).toBe(0);
    expect(run({}).status).toBe(0);
  });
});
