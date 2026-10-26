// Third-party analytics and advertising load only where they belong:
//   - Google Analytics on public marketing pages;
//   - Google AdSense on public article pages only.
// Signed-in workspaces, shared decision reports (/s/...) and every other
// route get neither, so customer projects, files, reports and decisions are
// never seen by an ad or marketing tracker. The list is an allowlist: a new
// route stays tracker-free unless it is added here.

export const GA_MEASUREMENT_ID = 'G-7BXZ1NCBS5';
export const ADSENSE_CLIENT = 'ca-pub-7765897544369826';
const GA_SRC = `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`;
const ADSENSE_SRC = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`;

const PUBLIC_EXACT = new Set(['/', '/pricing', '/login', '/calculators', '/articles', '/thinking-power']);
const PUBLIC_PREFIXES = ['/pages/', '/articles/', '/tools/', '/free-calculators/', '/limited-time/', '/thinking-power/'];

export function trackingPolicy(pathname) {
  const path = String(pathname || '/').replace(/\/+$/, '') || '/';
  const isPublic = PUBLIC_EXACT.has(path) || PUBLIC_PREFIXES.some((prefix) => path.startsWith(prefix));
  const isArticle = path === '/articles' || path.startsWith('/articles/');
  return { analytics: isPublic, ads: isArticle };
}

function hasScript(doc, fragment) {
  return Boolean(doc.querySelector(`script[src*="${fragment}"]`));
}

function addScript(doc, src, attrs = {}) {
  const script = doc.createElement('script');
  script.async = true;
  script.src = src;
  Object.entries(attrs).forEach(([key, value]) => script.setAttribute(key, value));
  doc.head.appendChild(script);
}

export function applyTrackingPolicy(pathname, { win = window, doc = document } = {}) {
  // The build's pre-render step must never bake trackers into static pages.
  if (win.__JASPEN_PRERENDER__) return 'skipped';
  const policy = trackingPolicy(pathname);
  const analyticsLoaded = hasScript(doc, 'googletagmanager.com/gtag/js');
  const adsLoaded = hasScript(doc, 'pagead2.googlesyndication.com');

  if ((analyticsLoaded && !policy.analytics) || (adsLoaded && !policy.ads)) {
    // A tracker loaded on a public page keeps running after an in-app
    // navigation. Stop analytics immediately and start this page clean.
    win[`ga-disable-${GA_MEASUREMENT_ID}`] = true;
    win.location.reload();
    return 'reloaded';
  }
  if (policy.analytics && !analyticsLoaded) {
    win.dataLayer = win.dataLayer || [];
    win.gtag = function gtag() { win.dataLayer.push(arguments); }; // eslint-disable-line prefer-rest-params
    win.gtag('js', new Date());
    win.gtag('config', GA_MEASUREMENT_ID);
    addScript(doc, GA_SRC);
  }
  if (policy.ads && !adsLoaded) {
    addScript(doc, ADSENSE_SRC, { crossorigin: 'anonymous' });
  }
  return 'applied';
}
