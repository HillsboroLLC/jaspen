import vercelConfig from '../vercel.json';

const header = vercelConfig.headers
  .flatMap((entry) => entry.headers || [])
  .find((candidate) => candidate.key === 'Content-Security-Policy');

describe('production browser security policy', () => {
  test('is enforced and keeps executable script sources strict', () => {
    expect(header).toBeDefined();
    expect(header.value).toContain("script-src 'self'");
    expect(header.value).not.toContain("script-src 'self' 'unsafe-inline'");
    expect(header.value).not.toContain("script-src 'self' 'unsafe-eval'");
    expect(header.value).not.toContain('Content-Security-Policy-Report-Only');
  });

  test('needs no inline-script hashes because index.html runs no inline script', () => {
    // Trackers load from src/thirdPartyTracking.js, so a hash here would be stale.
    expect(header.value).not.toMatch(/'sha256-/);
    const fs = require('fs');
    const path = require('path');
    const html = fs.readFileSync(path.join(process.cwd(), 'public', 'index.html'), 'utf8');
    const executable = [...html.matchAll(/<script(?![^>]*\bsrc=)(?![^>]*ld\+json)[^>]*>/g)];
    expect(executable).toHaveLength(0);
  });

  test.each([
    'https://api.jaspen.ai',
    'https://js.stripe.com',
    'https://*.ingest.sentry.io',
    'https://fonts.googleapis.com',
    'https://fonts.gstatic.com',
    'https://www.googletagmanager.com',
    'https://*.googlesyndication.com',
    'https://adservice.google.com',
    'https://*.doubleclick.net',
    'https://*.analytics.google.com',
  ])('allows required production origin %s', (origin) => {
    expect(header.value).toContain(origin);
  });
});
