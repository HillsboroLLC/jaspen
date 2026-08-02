import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FounderCampaignPage from './FounderCampaignPage';
import {
  FOUNDER_CAMPAIGNS,
  SHARED_FAQ,
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
    expect(screen.getAllByText('Limited-time offer').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole('heading', { level: 2, name: '300,000 AI-Powered Usage Credits' })).toBeInTheDocument();
    expect(screen.getByText('$999 once. No subscription. Credits never expire.')).toBeInTheDocument();
    expect(screen.getAllByText(/\$999 once\. No subscription required\./).length).toBeGreaterThanOrEqual(2);
    expect(
      screen.getAllByRole('button', { name: `${campaign.primaryCta} · $999` }).length
    ).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/300,000 AI-Powered Usage Credits/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Approximately ~750–1,200 typical project evaluations/).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/Compare up to 30 projects in one focused session/).length
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/downloadable decision assets/i).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'What Jaspen becomes' })).toBeInTheDocument();
    expect(screen.getByText('What the company learned')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: FOUNDER_TECHNICAL_GUARANTEE })).toBeInTheDocument();
    const faqItems = [...campaign.faq, ...SHARED_FAQ];
    expect(document.querySelectorAll('.fc-faq-item')).toHaveLength(faqItems.length);
    expect(document.querySelector('.fc-faq-item')).toHaveAttribute('open');
    expect(screen.getByText(faqItems[0].q).closest('summary')).toBeInTheDocument();
    expect(screen.getByTestId('seo')).toHaveAttribute('data-title', campaign.seo.title);
    expect(screen.getByTestId('seo')).toHaveAttribute('data-description', campaign.seo.description);
    expect(screen.getByTestId('seo')).toHaveAttribute('data-canonical', campaign.path);
    expect(mockTrack).toHaveBeenCalledWith('advantage_campaign_viewed', {
      campaign_id: campaign.id,
      route: campaign.path,
    });
  });

  it('sends its primary CTA to the shared Advantage checkout with campaign attribution', () => {
    render(
      <MemoryRouter initialEntries={[campaign.path]}>
        <FounderCampaignPage campaignKey={campaign.key} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getAllByRole('button', { name: new RegExp(campaign.primaryCta) })[0]);
    expect(screen.getByRole('dialog')).toHaveAttribute('data-return-path', campaign.path);
    expect(mockTrack).toHaveBeenCalledWith('advantage_primary_cta_clicked', {
      campaign_id: campaign.id,
      route: campaign.path,
    });
    expect(mockTrack).toHaveBeenCalledWith('advantage_checkout_started', {
      campaign_id: campaign.id,
      resumed: false,
    });

  });
});
