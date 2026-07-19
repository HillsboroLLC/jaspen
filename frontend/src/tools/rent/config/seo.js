const SITE_URL = 'https://jaspen.ai';
export const CANONICAL_PATH = '/tools/rent-calculator';

export const SEO = {
  title: 'True Cost of Renting Calculator',
  description:
    'Estimate the true cost of renting — not just the advertised rent. See effective rent after concessions, recurring fees, utilities, renter’s insurance, move-in cash, refundable vs. nonrefundable costs, renewal exposure, and multi-year cost. Free, transparent, no sign-up.',
  canonicalPath: CANONICAL_PATH,
};

// Single source of truth for the on-page FAQ and the FAQPage structured data.
export const FAQS = [
  {
    q: 'What is the true cost of renting vs. the advertised rent?',
    a: 'The advertised rent is only the base. The true monthly cost adds recurring fees (parking, pet rent, amenity/tech fees), tenant-paid utilities, and renter’s insurance, and nets any concession. The effective monthly cost also spreads one-time move-in costs across the lease.',
  },
  {
    q: 'How much cash do I need to move into an apartment?',
    a: 'Move-in cash is your first month’s rent (or $0 if a free month applies), plus any prepaid rent, refundable deposits, and nonrefundable fees and moving costs. Refundable deposits are cash held, not a cost.',
  },
  {
    q: 'Is this rent calculator free?',
    a: 'Yes. The full results, cost breakdown, move-in cash, multi-year cost, renewal exposure, and methodology are available with no account and no email required.',
  },
];

export function seoJsonLd() {
  const url = `${SITE_URL}${CANONICAL_PATH}`;
  return [
    {
      '@context': 'https://schema.org',
      '@type': 'WebApplication',
      name: 'True Cost of Renting Calculator',
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
      mainEntity: FAQS.map((item) => ({
        '@type': 'Question',
        name: item.q,
        acceptedAnswer: { '@type': 'Answer', text: item.a },
      })),
    },
  ];
}
