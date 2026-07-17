import React, { useEffect } from 'react';
import { Helmet } from 'react-helmet-async';

const SITE_NAME = 'Jaspen';
const SITE_URL = 'https://jaspen.ai';
const DEFAULT_IMAGE = `${SITE_URL}/android-chrome-512x512.png`;

function buildCanonicalUrl(canonicalPath = '/') {
  const normalized = String(canonicalPath || '/').trim();
  const withLeadingSlash = normalized.startsWith('/') ? normalized : `/${normalized}`;
  return `${SITE_URL}${withLeadingSlash}`;
}

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
  // Optional structured data. Accepts a single object or an array of objects.
  const structuredData = jsonLd
    ? (Array.isArray(jsonLd) ? jsonLd : [jsonLd]).filter(Boolean)
    : [];

  // index.html supplies the homepage canonical before React loads. Update that
  // single element for routed public pages instead of adding a duplicate link.
  useEffect(() => {
    const canonicalLink = document.getElementById('jaspen-canonical');
    if (canonicalLink) canonicalLink.setAttribute('href', canonical);
  }, [canonical]);

  return (
    <Helmet>
      <title>{fullTitle}</title>
      {noindex ? <meta name="robots" content="noindex, nofollow" /> : null}

      {metaDescription && <meta name="description" content={metaDescription} />}

      <meta property="og:title" content={fullTitle} />
      {metaDescription && <meta property="og:description" content={metaDescription} />}
      <meta property="og:type" content={type} />
      <meta property="og:url" content={canonical} />
      <meta property="og:image" content={image} />

      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={fullTitle} />
      {metaDescription && <meta name="twitter:description" content={metaDescription} />}
      <meta name="twitter:image" content={image} />

      {structuredData.map((entry, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <script key={`ld-${i}`} type="application/ld+json">
          {JSON.stringify(entry)}
        </script>
      ))}
    </Helmet>
  );
}
