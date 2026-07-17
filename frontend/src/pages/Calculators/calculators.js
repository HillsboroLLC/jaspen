import { Building2, BriefcaseBusiness, Home } from 'lucide-react';

export const CALCULATORS = [
  {
    title: 'True Cost of Home Ownership Calculator',
    description: 'Understand the monthly, upfront, and multi-year cost of owning a home beyond principal and interest.',
    audience: 'Personal',
    topic: 'Housing',
    route: '/tools/mortgage-calculator',
    status: 'New',
    icon: Home,
  },
  {
    title: 'Cost of Employee Turnover Calculator',
    description: 'Estimate recruiting, vacancy, ramp-up, and the knowledge and context costs that leave with an employee.',
    audience: 'Work',
    topic: 'People and operations',
    route: '/tools/cost-of-turnover',
    icon: BriefcaseBusiness,
  },
  {
    title: 'True Cost of Renting Calculator',
    description: 'See the real cost of a lease after concessions, recurring fees, utilities, insurance, and move-in cash.',
    audience: 'Personal',
    topic: 'Housing',
    route: '/tools/rent-calculator',
    status: 'New',
    icon: Building2,
  },
];

export const AUDIENCE_FILTERS = ['All', 'Personal', 'Work'];

export const SEO = {
  title: 'Free Calculators for Personal and Work Decisions',
  description: 'Explore Jaspen’s free calculators for understanding the true cost of home ownership, renting, and employee turnover. Transparent estimates with no sign-up required.',
  canonicalPath: '/calculators',
};

export function calculatorsJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: 'Jaspen Free Calculators',
    numberOfItems: CALCULATORS.length,
    itemListElement: CALCULATORS.map((calculator, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: calculator.title,
      url: `https://jaspen.ai${calculator.route}`,
    })),
  };
}
