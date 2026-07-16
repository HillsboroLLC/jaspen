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

// Structured data: a WebApplication for the tool + an FAQ built around the
// natural search language this page targets.
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
      mainEntity: [
        {
          '@type': 'Question',
          name: 'How do you calculate the cost of employee turnover?',
          acceptedAnswer: {
            '@type': 'Answer',
            text: 'We sum recruiting and sourcing, vacancy capacity loss, onboarding and training, and ramp-up productivity loss using published benchmarks (SHRM, BLS, Gallup), then add the knowledge and context costs traditional calculators omit — knowledge transfer, time to rebuild context, institutional-memory reconstruction, and project disruption — using documented research-based estimates. Every assumption is visible and editable.',
          },
        },
        {
          '@type': 'Question',
          name: 'What is the true cost of losing an employee?',
          acceptedAnswer: {
            '@type': 'Answer',
            text: 'Beyond recruiting and vacancy, a departure removes institutional and tribal knowledge. Research finds about 42% of a role’s institutional knowledge is unique to the person who holds it, so the true cost includes the time and labor spent rebuilding lost context and history.',
          },
        },
        {
          '@type': 'Question',
          name: 'Is this attrition cost calculator free?',
          acceptedAnswer: {
            '@type': 'Answer',
            text: 'Yes. The full results, category breakdown, assumptions, and methodology are available with no account and no email required.',
          },
        },
      ],
    },
  ];
}
