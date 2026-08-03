import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import HomePage from './HomePage';

const mockOpenAuthModal = jest.fn();

jest.mock('./usePublicAuthModal', () => () => ({
  openAuthModal: mockOpenAuthModal,
  AuthModalPortal: null,
}));

jest.mock('./JaspenNav', () => function MockJaspenNav() { return <nav>Nav</nav>; });
jest.mock('./WorkWithJaspenCanvas', () => function MockWorkWithJaspenCanvas() { return <section>Work canvas</section>; });
jest.mock('./InteractiveDecisionHero', () => function MockInteractiveDecisionHero() { return <section>Hero</section>; });
jest.mock('./PricingVariantB', () => function MockPricingVariantB() { return <section>Pricing</section>; });
jest.mock('./FlowIllustrated', () => function MockFlowIllustrated() { return <section>Flow</section>; });
jest.mock('./BeforeAfter', () => function MockBeforeAfter() { return <section>Before after</section>; });
jest.mock('./WhyJaspenBlock', () => function MockWhyJaspenBlock() { return <section>Why Jaspen</section>; });
jest.mock('./HowScoreWorks', () => function MockHowScoreWorks() { return <section>How score works</section>; });
jest.mock('./DecisionStyleAssessment/DecisionStyleAssessment', () => function MockDecisionStyleAssessment() { return <section>Assessment</section>; });
jest.mock('./DecisionPlanningToolkitLeadCapture', () => function MockDecisionPlanningToolkitLeadCapture() { return <section>Toolkit</section>; });
jest.mock('../FAQSection/FAQSection', () => function MockFAQSection() { return <section>FAQ</section>; });
// Reads auth and billing on mount; its own behaviour is covered in
// RankThemPromoModal.test.jsx.
jest.mock('./RankThemPromoModal', () => function MockRankThemPromoModal() { return null; });

describe('HomePage final CTA', () => {
  beforeEach(() => {
    mockOpenAuthModal.mockClear();
    window.IntersectionObserver = class {
      observe() {}
      disconnect() {}
    };
    window.ResizeObserver = class {
      observe() {}
      disconnect() {}
    };
  });

  it('supports Essential buyers and team conversations', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: /Ready to make better decisions with more room to think/i })).toBeInTheDocument();
    expect(screen.getByText(/Start with Essential for your own important decisions/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Start with Essential/i }));
    expect(mockOpenAuthModal).toHaveBeenCalledWith('signup', 'essential');

    expect(screen.getByRole('link', { name: /Talk to us about teams/i })).toHaveAttribute('href', 'mailto:hello@jaspen.ai');
  });
});
