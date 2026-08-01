import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FounderCampaignPage from './FounderCampaignPage';
import {
  FOUNDER_CAMPAIGNS,
  FOUNDER_TECHNICAL_GUARANTEE,
} from './founderCampaigns';

const mockTrack = jest.fn();

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: null }),
}));

jest.mock('../../tools/shared/createAnalytics', () => ({
  createAnalytics: () => ({ track: mockTrack }),
}));

jest.mock('../../shared/components/Seo', () => function MockSeo({ title, description, canonicalPath }) {
  return <div data-testid="seo" data-title={title} data-description={description} data-canonical={canonicalPath} />;
});

jest.mock('./ThinkingPowerCheckout', () => function MockCheckout({ returnPath, onClose, onSuccess }) {
  return (
    <div role="dialog" data-testid="checkout" data-return-path={returnPath}>
      <button type="button" onClick={onClose}>Close checkout</button>
      <button type="button" onClick={onSuccess}>Complete purchase</button>
    </div>
  );
});

describe.each(Object.values(FOUNDER_CAMPAIGNS))('$id campaign page', (campaign) => {
  beforeEach(() => mockTrack.mockClear());

  it('renders one persona-specific heading with accessible navigation and shared disclosures', () => {
    render(
      <MemoryRouter initialEntries={[campaign.path]}>
        <FounderCampaignPage campaignKey={campaign.key} />
      </MemoryRouter>,
    );

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(campaign.heroTitle);
    expect(screen.getByRole('navigation', { name: 'Campaign navigation' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: '300,000 Thinking Power credits' })).toBeInTheDocument();
    expect(screen.getByText('$599 one-time Founder price')).toBeInTheDocument();
    expect(screen.getAllByText(/300,000 Thinking Power credits/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Approximately ~750–1,200 typical project evaluations/).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/Compare up to 30 projects in one focused session/).length
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/downloadable decision assets/i).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'What Jaspen becomes' })).toBeInTheDocument();
    expect(screen.getByText('What the company learned')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: FOUNDER_TECHNICAL_GUARANTEE })).toBeInTheDocument();
    expect(screen.getByTestId('seo')).toHaveAttribute('data-title', campaign.seo.title);
    expect(screen.getByTestId('seo')).toHaveAttribute('data-description', campaign.seo.description);
    expect(screen.getByTestId('seo')).toHaveAttribute('data-canonical', campaign.path);
    expect(mockTrack).toHaveBeenCalledWith('founder_campaign_viewed', {
      campaign_id: campaign.id,
      route: campaign.path,
    });
  });

  it('sends its primary CTA to the shared Founder checkout with campaign attribution', () => {
    render(
      <MemoryRouter initialEntries={[campaign.path]}>
        <FounderCampaignPage campaignKey={campaign.key} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getAllByRole('button', { name: new RegExp(campaign.primaryCta) })[0]);
    expect(screen.getByRole('dialog')).toHaveAttribute('data-return-path', campaign.path);
    expect(mockTrack).toHaveBeenCalledWith('founder_primary_cta_clicked', {
      campaign_id: campaign.id,
      route: campaign.path,
    });
    expect(mockTrack).toHaveBeenCalledWith('founder_checkout_started', {
      campaign_id: campaign.id,
      resumed: false,
    });

    fireEvent.click(screen.getByRole('button', { name: 'Complete purchase' }));
    expect(mockTrack).toHaveBeenCalledWith('founder_purchase_completed', { campaign_id: campaign.id });
  });
});
