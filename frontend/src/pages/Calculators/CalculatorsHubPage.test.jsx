import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CalculatorsHubPage from './CalculatorsHubPage';
import { CALCULATORS, calculatorsJsonLd } from './calculators';

jest.mock('../Marketing/MarketingPageLayout', () => function MockLayout({ children }) { return <main>{children}</main>; });
jest.mock('../../shared/components/Seo', () => function MockSeo() { return null; });

describe('CalculatorsHubPage', () => {
  it('uses the three published canonical calculator routes', () => {
    expect(CALCULATORS.map((calculator) => calculator.route)).toEqual([
      '/tools/mortgage-calculator',
      '/tools/cost-of-turnover',
      '/tools/rent-calculator',
    ]);
    expect(calculatorsJsonLd().numberOfItems).toBe(3);
  });

  it('filters by audience and search, then clears an empty state', () => {
    render(<MemoryRouter><CalculatorsHubPage /></MemoryRouter>);
    expect(screen.getByText('3 calculators')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Work' }));
    expect(screen.getByText('1 calculator')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Cost of Employee Turnover Calculator/ })).toHaveAttribute('href', '/tools/cost-of-turnover');

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search calculators' }), { target: { value: 'mortgage' } });
    expect(screen.getByText('No calculators match that search.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getByText('3 calculators')).toBeInTheDocument();
  });
});
