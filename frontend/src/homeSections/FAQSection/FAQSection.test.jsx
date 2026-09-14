import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FAQSection from './FAQSection';

describe('FAQSection Thinking Power copy', () => {
  it('explains plan ranges, shared allowances, and variability', async () => {
    const user = userEvent.setup();
    render(<FAQSection />);

    await user.click(screen.getByRole('button', { name: /what is a credit/i }));
    expect(screen.getByText(/Free 300 supports ~1 focused evaluation with complete inputs/)).toBeInTheDocument();
    expect(screen.getByText(/Team 29,000 shared supports ~57–96 typical evaluations across the shared allowance/)).toBeInTheDocument();
    expect(screen.getByText(/Business 80,000 shared supports ~133–222 typical evaluations across the shared allowance/)).toBeInTheDocument();
    expect(screen.getByText(/These ranges are approximate, not guaranteed/)).toHaveTextContent(/attachments, analysis depth, revisions, and follow-up/);
  });

  it('does not promise that Free supports a typical or heavy evaluation', async () => {
    const user = userEvent.setup();
    render(<FAQSection />);

    await user.click(screen.getByRole('button', { name: /free plan just a trial/i }));
    expect(screen.getByText(/not a promise of a complete typical or heavy evaluation/i)).toBeInTheDocument();
  });

  it('explains automatic routing without asking customers to choose horsepower', async () => {
    const user = userEvent.setup();
    render(<FAQSection />);

    await user.click(screen.getByRole('button', { name: /how does jaspen choose the right ai model/i }));
    expect(screen.getByText(/you do not need to choose one/i)).toBeInTheDocument();
    expect(screen.getByText(/automatically selects the appropriate reasoning depth/i)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/Pluto|Orbit|Titan/);
  });
});
