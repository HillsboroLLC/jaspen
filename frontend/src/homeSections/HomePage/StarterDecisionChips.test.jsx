import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import StarterDecisionChips, { STARTER_DECISIONS } from './StarterDecisionChips';

describe('Starter decision chips', () => {
  it('offers the eight leadership decisions', () => {
    render(<StarterDecisionChips onSelect={jest.fn()} />);

    // Order is deliberate: it splits the row of chips evenly at desktop width.
    expect(screen.getAllByRole('button').map(b => b.textContent)).toEqual([
      'Prioritize Growth Investments',
      'Sequence Transformation Initiatives',
      'Compare Acquisition Targets',
      'Allocate Capital Across Business Units',
      'Reallocate Midyear Funding',
      "Prioritize Next Quarter's Investments",
      'Compare Strategic Initiatives',
      'Prioritize Technology Investments',
    ]);
  });

  it('tells the visitor the example is theirs to change', () => {
    // The prompt lands in the composer, so this line is what a first-time
    // visitor reads before sending anything.
    STARTER_DECISIONS.forEach(decision => {
      expect(decision.prompt.startsWith('Fictional example. Edit anything.')).toBe(true);
    });
  });

  it('passes the whole decision through on click', async () => {
    const user = userEvent.setup();
    const onSelect = jest.fn();
    render(<StarterDecisionChips onSelect={onSelect} />);

    await user.click(screen.getByRole('button', { name: 'Prioritize Growth Investments' }));

    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'growth-investments' })
    );
    expect(onSelect.mock.calls[0][0].prompt).toContain('Expand into the Canadian market');
  });

  it('asks for an ordered answer and stated assumptions, not just a ranking', () => {
    // What separates Jaspen's output from a sorted list. Most examples ask
    // for a sequence or roadmap; the acquisition example picks a single
    // target, so it asks for a primary and a backup instead.
    STARTER_DECISIONS.forEach(decision => {
      expect(decision.prompt).toMatch(/sequence|roadmap|backup/i);
      expect(decision.prompt).toMatch(/reasoning|rationale|assumptions/i);
      expect(decision.prompt).toMatch(/highest-value/i);
    });
  });

  it('gives every example real figures and timelines to adjust', () => {
    // A visitor is meant to edit a plausible scenario, not fill in blanks.
    // Abstract initiative names alone give Jaspen nothing to weigh.
    STARTER_DECISIONS.forEach(decision => {
      const dollars = decision.prompt.match(/\$[\d,.]+ ?(million|thousand)?/g) || [];
      expect(dollars.length).toBeGreaterThanOrEqual(6);
      expect(decision.prompt).toMatch(/month|year|quarter/i);
    });
  });

  it('keeps every id unique so React keys stay stable', () => {
    const ids = STARTER_DECISIONS.map(d => d.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
