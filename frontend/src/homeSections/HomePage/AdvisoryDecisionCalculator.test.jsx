import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdvisoryDecisionCalculator, { calculateDecisionInvestment } from './AdvisoryDecisionCalculator';

describe('calculateDecisionInvestment', () => {
  it('calculates one decision deterministically', () => {
    expect(calculateDecisionInvestment(25000, [10000000])).toEqual({
      total: 10000000, fee: 25000, percentage: 0.25,
      remainderPercentage: 99.75, decisionCount: 1,
    });
  });

  it('sums a portfolio before calculating the partnership percentage', () => {
    expect(calculateDecisionInvestment(100000, [10000000, 15000000, 25000000])).toMatchObject({
      total: 50000000, percentage: 0.2, decisionCount: 3,
    });
  });

  it('returns no result without a positive commitment value', () => {
    expect(calculateDecisionInvestment(25000, ['', 0, 'not a number'])).toBeNull();
  });
});

describe('AdvisoryDecisionCalculator', () => {
  it('shows the intensive comparison without making an outcome claim', () => {
    render(<AdvisoryDecisionCalculator />);
    expect(screen.getByText('0.25%', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByText(/does not predict or guarantee any financial outcome/i)).toBeInTheDocument();
  });

  it('supports several portfolio decisions', async () => {
    const user = userEvent.setup();
    render(<AdvisoryDecisionCalculator />);
    await user.click(screen.getByRole('radio', { name: /Strategic Advisor Partnership/i }));
    expect(screen.getByText('0.20%', { selector: 'strong' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add another decision' }));
    expect(screen.getByLabelText('Decision 3 value')).toBeInTheDocument();
  });

  it('does not describe a negative remainder when the entered value is below the fee', async () => {
    const user = userEvent.setup();
    render(<AdvisoryDecisionCalculator />);
    const value = screen.getByLabelText('Decision value');
    await user.clear(value);
    await user.type(value, '10000');
    expect(screen.getByText('250.00%', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByText(/verify the amount before relying on this comparison/i)).toBeInTheDocument();
    expect(screen.queryByText(/remaining -/i)).not.toBeInTheDocument();
  });
});
