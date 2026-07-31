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
    expect(essentialCard).toHaveTextContent('When the decision has real consequences, Essential is built for you.');
    expect(essentialCard).not.toHaveTextContent(/preserve the reasoning behind decisions that matter/i);
    expect(planNote).toHaveClass('pvb-plan-note');
    expect(screen.queryByText(/For people making real decisions regularly/i)).not.toBeInTheDocument();

    await user.click(within(essentialCard).getByRole('button', { name: /start free/i }));

    expect(onOpenModal).toHaveBeenCalledWith('signup', 'free');
  });

  it('does not use em dashes in the new Essential copy', () => {
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    const essentialCard = screen.getByText('Essential').closest('.pvb-card');
    expect(essentialCard).toHaveTextContent(/When the decision has real consequences/);
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
