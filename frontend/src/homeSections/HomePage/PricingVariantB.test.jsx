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
});
