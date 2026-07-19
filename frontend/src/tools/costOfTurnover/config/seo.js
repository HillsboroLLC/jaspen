// SEO configuration for the Cost of Turnover utility. Canonical route is
// /tools/cost-of-turnover; aliases redirect here rather than duplicating.

const SITE_URL = 'https://jaspen.ai';
export const CANONICAL_PATH = '/tools/cost-of-turnover';

export const SEO = {
  title: 'Cost of Employee Turnover Calculator',
  description:
    'Estimate the true cost of employee turnover — recruiting, vacancy, ramp-up, plus the institutional knowledge and context that leave with a departing employee. Free, evidence-based, no sign-up required.',
  canonicalPath: CANONICAL_PATH,
};

// Single source of truth for the on-page FAQ and the FAQPage structured data.
// Claims are limited to what the methodology actually uses (SHRM, BLS, APQC);
// no unsourced statistics.
export const FAQS = [
  {
    q: 'How do you calculate the cost of employee turnover?',
    a: 'You sum recruiting and sourcing, vacancy capacity loss, onboarding and training, and ramp-up productivity loss using published benchmarks (SHRM cost-per-hire and time-to-fill, BLS employer compensation), then add the knowledge and context costs most calculators omit — knowledge transfer, time to rebuild historical context, institutional-memory reconstruction, and documented project disruption. Every assumption is visible and editable.',
  },
  {
    q: 'What is the true cost of losing an employee?',
    a: 'Beyond recruiting and vacancy, a departure takes institutional and tribal knowledge with it — the context, history, and working relationships the person carried. The true cost includes the labor spent transferring that knowledge and rebuilding the context that was never documented, which is why a flat salary multiple usually understates it.',
  },
  {
    q: 'Is this attrition cost calculator free?',
    a: 'Yes. The full results, category breakdown, assumptions, and methodology are available with no account and no email required.',
  },
];

export function seoJsonLd() {
  const url = `${SITE_URL}${CANONICAL_PATH}`;
  return [
    {
      '@context': 'https://schema.org',
      '@type': 'WebApplication',
      name: 'Cost of Employee Turnover Calculator',
      url,
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Web',
      offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
      description: SEO.description,
      provider: { '@type': 'Organization', name: 'Jaspen', url: SITE_URL },
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
