export const SEO = {
  title: 'Rework Cost Calculator | Estimate the Cost of Redoing Work',
  description: 'Estimate the annual labor, coordination, material, and delay cost of redoing completed work. Free, transparent, and no sign-up required.',
  canonicalPath: '/tools/rework-cost-calculator',
};

export function seoJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebApplication',
    name: 'Jaspen Rework Cost Calculator',
    applicationCategory: 'BusinessApplication',
    operatingSystem: 'Any',
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    url: 'https://jaspen.ai/tools/rework-cost-calculator',
  };
}

