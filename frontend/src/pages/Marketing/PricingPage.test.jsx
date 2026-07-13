import React from 'react';
import { render, screen } from '@testing-library/react';
import PricingPage from './PricingPage';

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: null, loading: false }),
}));

jest.mock('./MarketingPageLayout', () => function MockMarketingPageLayout({ children }) {
  return <div>{children}</div>;
});

jest.mock('../../shared/components/Seo', () => function MockSeo() {
  return null;
});

describe('PricingPage', () => {
  beforeEach(() => {
    jest.spyOn(global, 'fetch').mockRejectedValue(new Error('catalog unavailable'));
  });

  afterEach(() => {
    jest.restoreAllMocks();
    window.history.pushState({}, '', '/');
  });

  it('clarifies Essential without changing plan pricing', async () => {
    render(<PricingPage />);

    expect((await screen.findAllByText('Essential')).length).toBeGreaterThan(0);
    expect(screen.getByText('$39 / month')).toBeInTheDocument();
    expect(screen.getByText('When the decision has real consequences, Essential is built for you.')).toBeInTheDocument();
    expect(screen.getByText(/pressure test assumptions, compare tradeoffs/i)).toBeInTheDocument();
    expect(screen.queryByText(/For people making real decisions regularly/i)).not.toBeInTheDocument();
  });
});
