import {
  ADSENSE_CLIENT, GA_MEASUREMENT_ID, STAGING_HOST_PATTERN, applyTrackingPolicy, isStagingHost, trackingPolicy,
} from './thirdPartyTracking';

function fakeEnv() {
  document.head.innerHTML = '';
  const win = { location: { reload: jest.fn() } };
  return { win, doc: document };
}

const scripts = () => Array.from(document.head.querySelectorAll('script')).map((s) => s.src);

test.each([
  ['/', true, false],
  ['/pricing', true, false],
  ['/pages/jaspen', true, false],
  ['/articles', true, true],
  ['/articles/how-to-decide', true, true],
  ['/tools/rent-calculator', true, false],
  ['/dashboard', false, false],
  ['/workspace/thread_1/card_1', false, false],
  ['/projects', false, false],
  ['/team', false, false],
  ['/account', false, false],
  ['/s/sharetoken123', false, false],
  ['/review/articles/draft', false, false],
  ['/some-new-route', false, false],
])('%s → analytics %s, ads %s', (path, analytics, ads) => {
  expect(trackingPolicy(path)).toEqual({ analytics, ads });
});

test('an article page loads analytics and AdSense', () => {
  const { win, doc } = fakeEnv();
  applyTrackingPolicy('/articles/example', { win, doc });
  expect(scripts()).toEqual([
    `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`,
    `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`,
  ]);
});

test('the signed-in app loads nothing', () => {
  const { win, doc } = fakeEnv();
  applyTrackingPolicy('/workspace/thread_1/card_1', { win, doc });
  expect(scripts()).toEqual([]);
  expect(win.location.reload).not.toHaveBeenCalled();
});

test('entering the app after a public page stops analytics and starts clean', () => {
  const { win, doc } = fakeEnv();
  applyTrackingPolicy('/pricing', { win, doc });
  applyTrackingPolicy('/dashboard', { win, doc });
  expect(win[`ga-disable-${GA_MEASUREMENT_ID}`]).toBe(true);
  expect(win.location.reload).toHaveBeenCalledTimes(1);
});

test('leaving articles for another public page drops AdSense', () => {
  const { win, doc } = fakeEnv();
  applyTrackingPolicy('/articles/example', { win, doc });
  applyTrackingPolicy('/pricing', { win, doc });
  expect(win.location.reload).toHaveBeenCalledTimes(1);
});

test('the build pre-render never injects trackers', () => {
  const { win, doc } = fakeEnv();
  win.__JASPEN_PRERENDER__ = true;
  expect(applyTrackingPolicy('/articles/example', { win, doc })).toBe('skipped');
  expect(scripts()).toEqual([]);
});

test('index.html no longer loads trackers on every route', () => {
  const fs = require('fs');
  const path = require('path');
  const html = fs.readFileSync(path.join(process.cwd(), 'public', 'index.html'), 'utf8');
  expect(html).not.toMatch(/<script[^>]+googletagmanager/);
  expect(html).not.toMatch(/<script[^>]+adsbygoogle/);
  expect(html).not.toMatch(/gtag\('config'/);
});

describe('staging loads no analytics or ads', () => {
  const stagingWin = (hostname) => ({ location: { hostname, reload: jest.fn() } });

  test.each([
    'staging.jaspen.ai',
    'jaspen-git-staging-bailey-builds-projects.vercel.app',
  ])('%s: a public article page loads nothing', (hostname) => {
    document.head.innerHTML = '';
    const win = stagingWin(hostname);
    expect(applyTrackingPolicy('/articles/example', { win, doc: document })).toBe('staging');
    expect(scripts()).toEqual([]);
    expect(win.gtag).toBeUndefined();
    expect(win.dataLayer).toBeUndefined();
  });

  test.each([
    'jaspen.ai',
    'www.jaspen.ai',
    'jaspen-git-develop-bailey-builds-projects.vercel.app',
    'staging.jaspen.ai.evil.example',
    'xstaging.jaspen.ai',
  ])('%s keeps the production behavior', (hostname) => {
    expect(isStagingHost(hostname)).toBe(false);
    document.head.innerHTML = '';
    applyTrackingPolicy('/articles/example', { win: stagingWin(hostname), doc: document });
    expect(scripts()).toHaveLength(2);
  });

  test('matches the staging host rule in vercel.json', () => {
    const vercelConfig = require('../vercel.json');
    const stagingRule = vercelConfig.headers.find((rule) => rule.has);
    expect(STAGING_HOST_PATTERN.source).toBe(stagingRule.has[0].value);
  });
});
