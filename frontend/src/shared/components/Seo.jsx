import { useEffect } from 'react';

const SITE_NAME = 'Jaspen';
// The apex host 307s to www, and some crawlers will not follow a redirect
// for og:image or treat a redirecting canonical as authoritative. Point at
// where the content actually lives.
const SITE_URL = 'https://www.jaspen.ai';
const DEFAULT_IMAGE = `${SITE_URL}/android-chrome-512x512.png`;

// Tracks how many Seo instances are mounted so the app shell can yield
// document.title control to the page-level Seo component instead of
// overwriting it. See AppShell's title effect.
let seoInstanceCount = 0;
export function isSeoManagingHead() {
  return seoInstanceCount > 0;
}

function buildCanonicalUrl(canonicalPath = '/') {
  const normalized = String(canonicalPath || '/').trim();
  const withLeadingSlash = normalized.startsWith('/') ? normalized : `/${normalized}`;
  return `${SITE_URL}${withLeadingSlash}`;
}

// Create or update a <meta> tag by attribute. An empty content removes the tag
// only if this component created it, so static index.html tags are left alone.
function upsertMeta(attr, key, content) {
  const head = document.head;
  const existing = head.querySelector(`meta[${attr}="${key}"]`);
  if (!content) {
    if (existing && existing.getAttribute('data-seo') === 'true') existing.remove();
    return;
  }
  let el = existing;
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    el.setAttribute('data-seo', 'true');
    head.appendChild(el);
  }
  el.setAttribute('content', content);
}

/**
 * Dependency-free document-head manager. Sets the title, canonical, meta
 * description, robots, Open Graph / Twitter tags, and JSON-LD structured data
 * for the current route. Replaces react-helmet-async, whose installed build was
 * a no-op against React 18 (no head tags were reaching the DOM).
 */
export default function Seo({
  title,
  description,
  canonicalPath = '/',
  image = DEFAULT_IMAGE,
  type = 'website',
  noindex = false,
  jsonLd = null,
}) {
  const fullTitle = title ? `${title} | ${SITE_NAME}` : SITE_NAME;
  const canonical = buildCanonicalUrl(canonicalPath);
  const metaDescription = String(description || '').trim();
  const structuredData = jsonLd
    ? (Array.isArray(jsonLd) ? jsonLd : [jsonLd]).filter(Boolean)
    : [];
  const structuredDataKey = JSON.stringify(structuredData);

  // Mark this page as Seo-managed for the component's lifetime so the app shell
  // does not overwrite the page-level title.
  useEffect(() => {
    seoInstanceCount += 1;
    return () => {
      seoInstanceCount -= 1;
    };
  }, []);

  useEffect(() => {
    document.title = fullTitle;

    const canonicalLink = document.getElementById('jaspen-canonical');
    if (canonicalLink) canonicalLink.setAttribute('href', canonical);

    upsertMeta('name', 'description', metaDescription);
    upsertMeta('name', 'robots', noindex ? 'noindex, nofollow' : '');

    upsertMeta('property', 'og:title', fullTitle);
    upsertMeta('property', 'og:description', metaDescription);
    upsertMeta('property', 'og:type', type);
    upsertMeta('property', 'og:url', canonical);
    upsertMeta('property', 'og:image', image);

    upsertMeta('name', 'twitter:card', 'summary_large_image');
    upsertMeta('name', 'twitter:title', fullTitle);
    upsertMeta('name', 'twitter:description', metaDescription);
    upsertMeta('name', 'twitter:image', image);

    // Replace any structured data previously injected by this component.
    document.head
      .querySelectorAll('script[data-seo-jsonld="true"]')
      .forEach((node) => node.remove());
    structuredData.forEach((entry) => {
      const script = document.createElement('script');
      script.type = 'application/ld+json';
      script.setAttribute('data-seo-jsonld', 'true');
      script.text = JSON.stringify(entry);
      document.head.appendChild(script);
    });

    return () => {
      // Remove leak-sensitive tags on unmount so they do not carry to a page
      // that has no Seo component (e.g. authenticated app pages).
      document.head
        .querySelectorAll('script[data-seo-jsonld="true"]')
        .forEach((node) => node.remove());
      const robots = document.head.querySelector('meta[name="robots"][data-seo="true"]');
      if (robots) robots.remove();
    };
    // structuredDataKey stands in for the structuredData array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullTitle, canonical, metaDescription, image, type, noindex, structuredDataKey]);

  return null;
}
