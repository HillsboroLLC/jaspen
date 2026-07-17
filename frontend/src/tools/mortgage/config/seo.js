const SITE_URL = 'https://jaspen.ai';
export const CANONICAL_PATH = '/tools/mortgage-calculator';

export const SEO = {
  title: 'True Cost of Home Ownership Calculator',
  description:
    'Estimate the true monthly, upfront, and multi-year cost of a mortgage — not just principal and interest. See required payment vs. true carrying cost, cash to close, PMI, maintenance, equity built, and payment-change exposure. Free, transparent, no sign-up.',
  canonicalPath: CANONICAL_PATH,
};

export function seoJsonLd() {
  const url = `${SITE_URL}${CANONICAL_PATH}`;
  return [
    {
      '@context': 'https://schema.org',
      '@type': 'WebApplication',
      name: 'True Cost of Home Ownership Mortgage Calculator',
      url,
      applicationCategory: 'FinanceApplication',
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
          name: 'What is the true cost of owning a home vs. the mortgage payment?',
          acceptedAnswer: {
            '@type': 'Answer',
            text: 'The required lender payment covers principal, interest, property taxes, homeowners insurance, and PMI (PITI), plus any HOA. The true carrying cost adds a maintenance reserve and optional utilities — the full monthly cost of owning, which is higher than the mortgage payment alone.',
          },
        },
        {
          '@type': 'Question',
          name: 'How much cash do I need to close on a house?',
          acceptedAnswer: {
            '@type': 'Answer',
            text: 'Cash to close is your down payment plus closing costs (a planning default of about 3% of the purchase price) plus any points or prepaids, minus lender credits. Your lender Loan Estimate controls the actual figure.',
          },
        },
        {
          '@type': 'Question',
          name: 'Is this mortgage calculator free?',
          acceptedAnswer: {
            '@type': 'Answer',
            text: 'Yes. The full results, cost breakdown, multi-year cost, equity, sensitivity, and methodology are available with no account and no email required.',
          },
        },
      ],
    },
  ];
}
