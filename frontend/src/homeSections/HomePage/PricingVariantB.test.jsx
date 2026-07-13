import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PricingVariantB from './PricingVariantB';

describe('PricingVariantB', () => {
  it('positions Essential for consequential decisions and routes its CTA with Essential intent', async () => {
    const user = userEvent.setup();
    const onOpenModal = jest.fn();

    render(<PricingVariantB onOpenModal={onOpenModal} />);

    expect(screen.getByText('When the decision has real consequences, Essential is built for you.')).toBeInTheDocument();
    expect(screen.getByText(/preserve the reasoning behind decisions that matter/i)).toBeInTheDocument();
    expect(screen.queryByText(/For people making real decisions regularly/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /start with essential/i }));

    expect(onOpenModal).toHaveBeenCalledWith('signup', 'essential');
  });

  it('does not use em dashes in the new Essential copy', () => {
    render(<PricingVariantB onOpenModal={jest.fn()} />);

    const essentialCard = screen.getByText('Essential').closest('.pvb-card');
    expect(essentialCard).toHaveTextContent(/When the decision has real consequences/);
    expect(essentialCard.textContent).not.toContain('—');
  });
});
