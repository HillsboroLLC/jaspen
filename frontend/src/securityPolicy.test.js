import vercelConfig from '../vercel.json';

const cspRules = vercelConfig.headers.filter((entry) => (entry.headers || [])
  .some((candidate) => candidate.key === 'Content-Security-Policy'));
const cspOf = (rule) => rule.headers.find((candidate) => candidate.key === 'Content-Security-Policy');
const productionRule = cspRules.find((rule) => rule.missing && !rule.has);
const stagingRule = cspRules.find((rule) => rule.has && !rule.missing);
const header = cspOf(productionRule);
const stagingHeader = cspOf(stagingRule);
const directive = (value, name) => value.split(';').map((part) => part.trim())
  .find((part) => part.startsWith(`${name} `));

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

  test('lets AdSense load its ad-quality frame on article pages', () => {
    const frameSrc = header.value.split(';').find((part) => part.trim().startsWith('frame-src'));
    expect(frameSrc).toContain('https://*.adtrafficquality.google');
  });
});

describe('staging browser security policy', () => {
  const hostPattern = new RegExp(stagingRule.has[0].value);

  test('production and staging policies are the only CSP rules and never both apply', () => {
    expect(cspRules).toHaveLength(2);
    expect(productionRule.source).toBe('/(.*)');
    expect(stagingRule.source).toBe('/(.*)');
    expect(productionRule.missing).toEqual(stagingRule.has);
    expect(stagingRule.has).toEqual([{ type: 'host', value: stagingRule.has[0].value }]);
  });

  test.each([
    'staging.jaspen.ai',
    'jaspen-git-staging-bailey-builds-projects.vercel.app',
  ])('applies the staging policy on %s', (host) => {
    expect(hostPattern.test(host)).toBe(true);
  });

  test.each([
    'jaspen.ai',
    'www.jaspen.ai',
    'api.jaspen.ai',
    'sekki-platform.vercel.app',
    'jaspen-git-develop-bailey-builds-projects.vercel.app',
    'jaspen-kbxxmvqob-bailey-builds-projects.vercel.app',
    'staging.jaspen.ai.evil.example',
    'xstaging.jaspen.ai',
  ])('keeps the production policy on %s', (host) => {
    expect(hostPattern.test(host)).toBe(false);
  });

  test('production connects only to the production API', () => {
    expect(directive(header.value, 'connect-src')).toContain('https://api.jaspen.ai');
    expect(header.value).not.toContain('api-staging');
  });

  test('staging connects only to the staging API', () => {
    const connectSrc = directive(stagingHeader.value, 'connect-src');
    expect(connectSrc).toContain('https://api-staging.jaspen.ai');
    expect(stagingHeader.value).not.toContain('https://api.jaspen.ai');
  });

  test('staging allows Stripe Elements and 3D Secure, with analytics and ads blocked', () => {
    expect(directive(stagingHeader.value, 'script-src'))
      .toBe("script-src 'self' https://js.stripe.com https://*.js.stripe.com");
    expect(directive(stagingHeader.value, 'frame-src'))
      .toBe('frame-src https://js.stripe.com https://*.js.stripe.com https://hooks.stripe.com');
    expect(directive(stagingHeader.value, 'connect-src'))
      .toBe("connect-src 'self' https://api-staging.jaspen.ai https://*.ingest.sentry.io https://api.stripe.com");
    [
      'googletagmanager', 'googlesyndication', 'adservice', 'adtrafficquality',
      'doubleclick', 'google-analytics', 'analytics.google', 'www.google.com', '*.google.com',
    ].forEach((origin) => expect(stagingHeader.value).not.toContain(origin));
  });

  test('staging keeps every other production directive unchanged', () => {
    const names = (value) => value.split(';').map((part) => part.trim().split(/\s+/)[0]).filter(Boolean);
    expect(names(stagingHeader.value)).toEqual(names(header.value));
    ['default-src', 'style-src', 'font-src', 'img-src', 'object-src', 'base-uri', 'frame-ancestors']
      .forEach((name) => expect(directive(stagingHeader.value, name)).toBe(directive(header.value, name)));
  });

  test('every staging source is covered by production origins or is the staging API', () => {
    const sources = (value) => new Set(value.split(';').flatMap((part) => part.trim().split(/\s+/).slice(1)));
    const production = sources(header.value);
    [...sources(stagingHeader.value)]
      .filter((source) => source !== "'none'" && source !== 'https://api-staging.jaspen.ai')
      .forEach((source) => expect(
        production.has(source) || (source.endsWith('.stripe.com') && production.has('https://*.stripe.com')),
      ).toBe(true));
  });

  test('every other security header still applies on every host', () => {
    const global = vercelConfig.headers.find((entry) => entry.source === '/(.*)' && !entry.has && !entry.missing);
    expect(global.headers.map((h) => h.key)).toEqual([
      'X-Frame-Options',
      'X-Content-Type-Options',
      'Referrer-Policy',
      'X-XSS-Protection',
      'Permissions-Policy',
      'Strict-Transport-Security',
    ]);
  });
});
