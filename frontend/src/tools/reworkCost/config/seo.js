const SITE_URL = 'https://jaspen.ai';
export const CANONICAL_PATH = '/tools/rework-cost-calculator';

export const SEO = {
  title: 'Rework Cost Calculator | Estimate the Cost of Redoing Work',
  description: 'Estimate the annual labor, coordination, material, and delay cost of redoing completed work. Free, transparent, and no sign-up required.',
  canonicalPath: CANONICAL_PATH,
};

// Single source of truth for the on-page FAQ and the FAQPage structured data.
export const FAQS = [
  {
    q: 'How do you calculate the cost of rework?',
    a: 'Estimate the hours your team spends redoing completed work (headcount × paid hours per week × working weeks × the share that is rework), value them at your fully loaded hourly cost, then add manager coordination, known material or vendor costs, and any documented delay cost. That gives a gross annual rework cost you can break down and challenge.',
  },
  {
    q: 'What counts as rework?',
    a: 'Rework is time or resources spent correcting, revising, rebuilding, reprocessing, or repeating work that was already considered finished or ready to move forward. It excludes ordinary first-pass work and healthy iteration such as drafts and planned reviews.',
  },
  {
    q: 'Is this rework cost calculator free?',
    a: 'Yes. The full breakdown, the addressable-cost estimate, the uncertainty range, and the methodology are available with no account and no email required.',
  },
];

export function seoJsonLd() {
  return [
    {
      '@context': 'https://schema.org',
      '@type': 'WebApplication',
      name: 'Jaspen Rework Cost Calculator',
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Any',
      offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
      url: `${SITE_URL}${CANONICAL_PATH}`,
    },
    {
      '@context': 'https://schema.org',
      '@type': 'FAQPage',
      mainEntity: FAQS.map((item) => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: { '@type': 'Answer', text: item.a },
      })),
    },
  ];
}
