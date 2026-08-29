import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PricingVariantB from './PricingVariantB';

describe('PricingVariantB', () => {
  it('keeps Essential featured while routing its CTA to free signup', async () => {
    const user = userEvent.setup();
    const onOpenModal = jest.fn();

    render(<PricingVariantB onOpenModal={onOpenModal} />);

    const essentialCard = screen.getByText('Essential').closest('.pvb-card');
    const planNote = screen.getByText(/preserve the reasoning behind decisions that matter/i);

    expect(essentialCard).toHaveClass('is-featured');
    expect(essentialCard).toHaveTextContent('For consequential decisions where confidence needs to be grounded in evidence.');
    expect(essentialCard).not.toHaveTextContent(/preserve the reasoning behind decisions that matter/i);
    expect(planNote).toHaveClass('pvb-plan-note');
    expect(screen.queryByText(/For people making real decisions regularly/i)).not.toBeInTheDocument();

    await user.click(within(essentialCard).getByRole('button', { name: /start free/i }));

    expect(onOpenModal).toHaveBeenCalledWith('signup', 'free');
  });

  it('does not use em dashes in the new Essential copy', () => {
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    const essentialCard = screen.getByText('Essential').closest('.pvb-card');
    expect(essentialCard).toHaveTextContent(/For consequential decisions/);
    expect(essentialCard.textContent).not.toContain('—');
  });

  it('shows credits and approximate project value on every pricing card', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    expect(screen.getByText('300 credits/month')).toBeInTheDocument();
    expect(screen.getByText('~1 focused evaluation with complete inputs')).toBeInTheDocument();
    expect(screen.getByText('1,000 credits/month')).toBeInTheDocument();
    expect(screen.getByText('~3–4 typical project evaluations')).toBeInTheDocument();
    expect(screen.getByText('7,000 credits/month')).toBeInTheDocument();
    expect(screen.getByText('~17–29 typical project evaluations')).toBeInTheDocument();
    expect(screen.getByText('29,000 shared credits/month')).toBeInTheDocument();
    expect(screen.getByText('~57–96 typical project evaluations across the shared allowance')).toBeInTheDocument();
    expect(screen.getByText(/Estimates are approximate, not guaranteed/)).toHaveTextContent(/attachments, analysis depth, revisions, and follow-up/);

    await user.click(screen.getByRole('tab', { name: /business & enterprise/i }));
    expect(screen.getByText('80,000 shared credits/month')).toBeInTheDocument();
    expect(screen.getByText('~133–222 typical project evaluations across the shared allowance')).toBeInTheDocument();
  });

  it('includes approximate project value in the plan comparison', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    await user.click(screen.getByRole('button', { name: /compare plans/i }));
    const comparisonRow = screen.getByText('Approximate project evaluations').closest('tr');
    expect(comparisonRow).toHaveTextContent('~1 focused evaluation with complete inputs');
    expect(comparisonRow).toHaveTextContent('~3–4 typical project evaluations');
    expect(comparisonRow).toHaveTextContent('~17–29 typical project evaluations');
    expect(comparisonRow).toHaveTextContent('~57–96 typical project evaluations across the shared allowance');
  });
});

describe('Advisory Partnerships tab', () => {
  const openAdvisory = async (user) => {
    await user.click(screen.getByRole('tab', { name: /advisory partnerships/i }));
  };

  it('offers three primary audience tabs', () => {
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    const tabs = screen.getAllByRole('tab');
    expect(tabs.map(tab => tab.textContent)).toEqual([
      'Individuals & Teams',
      'Business & Enterprise',
      'Advisory Partnerships',
    ]);
  });

  it('shows both advisory prices rather than hiding them behind a sales form', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    await openAdvisory(user);

    expect(screen.getByText('$25,000')).toBeInTheDocument();
    expect(screen.getByText('$100,000')).toBeInTheDocument();
    expect(screen.getAllByText('Flat fee')).toHaveLength(2);
    // Transparent pricing is the whole positioning decision.
    expect(screen.queryByText(/^Contact Sales$/i)).not.toBeInTheDocument();
  });

  it('opens the request form with the clicked engagement pre-selected, never checkout', async () => {
    const user = userEvent.setup();
    const onOpenModal = jest.fn();

    render(<PricingVariantB onOpenModal={onOpenModal} />);
    await openAdvisory(user);

    const ctas = screen.getAllByRole('button', { name: /request a consultation/i });
    expect(ctas).toHaveLength(2);

    await user.click(ctas[0]);
    const dialog = screen.getByRole('dialog', { name: /executive partnership request/i });
    expect(within(dialog).getByRole('radio', { name: /Executive Decision Intensive \(\$25,000\)/ })).toBeChecked();

    await user.click(within(dialog).getByRole('button', { name: /close request form/i }));

    await user.click(screen.getAllByRole('button', { name: /request a consultation/i })[1]);
    const secondDialog = screen.getByRole('dialog', { name: /executive partnership request/i });
    expect(within(secondDialog).getByRole('radio', { name: /Strategic Advisor Partnership \(\$100,000\)/ })).toBeChecked();

    // Advisory must never open the signup/checkout modal.
    expect(onOpenModal).not.toHaveBeenCalled();
  });

  it('states how advisory is delivered without calling it consulting', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    await openAdvisory(user);

    expect(screen.getByRole('heading', { name: /Strategic decisions deserve more than software alone/i })).toBeInTheDocument();
    expect(screen.getByText(/delivered through structured virtual working sessions/i)).toBeInTheDocument();
    expect(screen.getByText(/In-person facilitation may be considered when appropriate/i)).toBeInTheDocument();

    const panel = screen.getByRole('tabpanel');
    expect(panel.textContent).not.toMatch(/consulting/i);
    // No outcome promises.
    expect(panel.textContent).not.toMatch(/guarantee[ds]?\s+(revenue|savings|EBITDA)/i);
  });

  it('describes included Jaspen access and AI capacity without fixed credits on advisory cards', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);
    await openAdvisory(user);

    expect(
      screen.getAllByText(/Jaspen access and AI capacity are included throughout the engagement/),
    ).toHaveLength(2);
    expect(screen.getAllByText('You receive')).toHaveLength(2);
    expect(
      screen.getByText('Everything in the Intensive, applied across the cycle, plus:'),
    ).toBeInTheDocument();

    // The comparison table still carries the existing planning context.
    expect(screen.getByText(/approximate planning estimates, not guaranteed quantities/i)).toBeInTheDocument();
    expect(screen.getByText(/Actual usage varies based on model selection/i)).toBeInTheDocument();
  });

  it('never invites a reader to divide the fee by the hours', async () => {
    // The point of the repositioning. A comparison row counting sessions or
    // naming a duration teaches the reader to price a calendar, which is the
    // one comparison neither engagement should invite. Logistics belong on the
    // cards, below the deliverables, not in a table built for scanning.
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);
    await openAdvisory(user);
    await user.click(screen.getByRole('button', { name: /compare advisory engagements/i }));

    const table = screen.getByRole('table');
    const rowLabels = [...table.querySelectorAll('tbody th, tbody td:first-child')]
      .map(cell => cell.textContent);

    expect(rowLabels).not.toContain('Session duration');
    expect(rowLabels).not.toContain('Executive Decision Intensives');
    expect(table.textContent).not.toMatch(/90 minutes/);
  });

  it('leads each engagement with its function, not its fee', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);
    await openAdvisory(user);

    expect(
      screen.getByText('Decision assurance before a consequential commitment.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Decision assurance across a planning or capital cycle.'),
    ).toBeInTheDocument();
  });

  it('frames the impact bands as guidance rather than eligibility', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);
    await openAdvisory(user);

    // "Best suited for" leaves room to accept a smaller decision carrying
    // unusual complexity. A requirement would not.
    expect(screen.getByText(/Best suited for decisions carrying roughly \$10M or more/)).toBeInTheDocument();
    expect(screen.getByText(/roughly \$50M or more in aggregate consequence/)).toBeInTheDocument();
    expect(screen.queryByText(/minimum|required|must have/i)).not.toBeInTheDocument();
  });

  it('distinguishes the partnership by cross-decision work, not by volume', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);
    await openAdvisory(user);

    expect(screen.getByText(/Five reviews is not the product/)).toBeInTheDocument();
    expect(
      screen.getByText(/Shared assumptions traced across initiatives/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/whether your organization.s confidence is running ahead of its evidence/i),
    ).toBeInTheDocument();
  });

  it('hides the billing toggle and the enterprise calculator on advisory', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    await openAdvisory(user);

    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.queryByText(/Enterprise Investment Calculator/i)).not.toBeInTheDocument();
  });

  it('keeps the enterprise calculator on the business tab', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    await user.click(screen.getByRole('tab', { name: /business & enterprise/i }));
    expect(screen.getByText(/Enterprise Investment Calculator/i)).toBeInTheDocument();
  });

  it('expands and collapses the advisory comparison', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);
    await openAdvisory(user);

    const toggle = screen.getByRole('button', { name: /compare advisory engagements/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    // The comparison columns must name the engagements exactly as the cards
    // do. Readers are already on jaspen.ai, so nothing here is brand-prefixed.
    const headers = [...screen.getByRole('table').querySelectorAll('thead th')].map(th => th.textContent);
    expect(headers).toEqual([
      'Engagement',
      'Executive Decision Intensive',
      'Strategic Advisor Partnership',
    ]);

    const investmentRow = screen.getByText('Investment').closest('tr');
    expect(investmentRow).toHaveTextContent('$25,000 flat fee');
    expect(investmentRow).toHaveTextContent('$100,000 flat fee');
    const scopeRow = screen.getByText('Decision scope').closest('tr');
    expect(scopeRow).toHaveTextContent('One decision and the options under it');
    expect(scopeRow).toHaveTextContent('Every decision in the cycle, and the relationships between them');

    await user.click(toggle);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('moves between all three tabs with the arrow keys, wrapping at the ends', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    const individuals = screen.getByRole('tab', { name: /individuals & teams/i });
    individuals.focus();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: /business & enterprise/i })).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: /advisory partnerships/i })).toHaveAttribute('aria-selected', 'true');

    // Wraps forward past the last tab.
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: /individuals & teams/i })).toHaveAttribute('aria-selected', 'true');

    // And backward past the first.
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('tab', { name: /advisory partnerships/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('keeps the selected tab the only one in the tab order', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);
    await openAdvisory(user);

    expect(screen.getByRole('tab', { name: /advisory partnerships/i })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tab', { name: /individuals & teams/i })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'pricing-tab-advisory');
  });

  it('leaves the existing plan prices untouched', async () => {
    const user = userEvent.setup();
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    // Guards the scope boundary: advisory must not perturb plan pricing.
    expect(screen.getByText('Free', { selector: '.pvb-price-num' })).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('39')).toBeInTheDocument();
    expect(screen.getByText('129')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: /business & enterprise/i }));
    expect(screen.getByText('299')).toBeInTheDocument();
  });
});
