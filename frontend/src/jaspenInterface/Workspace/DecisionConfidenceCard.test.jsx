import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import DecisionConfidenceCard from './DecisionConfidenceCard';

function criterion(overrides = {}) {
  return {
    key: 'fin',
    label: 'Financial viability',
    weight: 0.25,
    confidence: 'assumed',
    raw_score: 80,
    score: 45,
    swing: 8.75,
    severity: 'material',
    evidenced: false,
    resolvable: true,
    resolution: 'Connect NetSuite or upload the model',
    ...overrides,
  };
}

function profile(overrides = {}) {
  return {
    evidence_backed_pct: 57,
    assumption_dependent_pct: 43,
    score: 68,
    criteria: [criterion()],
    counts: {},
    claims: [{ kind: 'material', text: '1 assumption could materially change the score' }],
    ...overrides,
  };
}

describe('DecisionConfidenceCard', () => {
  it('leads with the evidence split rather than the score', () => {
    render(<DecisionConfidenceCard profile={profile()} />);
    expect(screen.getByText('57%')).toBeInTheDocument();
    expect(screen.getByText('43%')).toBeInTheDocument();
    expect(screen.getByText(/evidence-backed/)).toBeInTheDocument();
    expect(screen.getByText(/assumption-dependent/)).toBeInTheDocument();
  });

  it('renders only server-computed claims', () => {
    render(<DecisionConfidenceCard profile={profile()} />);
    expect(
      screen.getByText('1 assumption could materially change the score'),
    ).toBeInTheDocument();
  });

  it('shows the resolution path for a resolvable assumption', () => {
    render(<DecisionConfidenceCard profile={profile()} />);
    expect(screen.getByText('Evidence needed')).toBeInTheDocument();
    expect(
      screen.getByText(/Connect NetSuite or upload the model/),
    ).toBeInTheDocument();
  });

  it('groups exposure in plain language, never by tier name', () => {
    render(<DecisionConfidenceCard profile={profile()} />);
    expect(screen.getByText('Could materially change the score')).toBeInTheDocument();
    // The engineering taxonomy must not reach the screen.
    expect(screen.queryByText('material')).not.toBeInTheDocument();
    expect(screen.queryByText('reversing')).not.toBeInTheDocument();
  });

  describe('the distinctions that must not collapse', () => {
    it('keeps criteria with no score exposure out of the register', () => {
      const settled = criterion({
        key: 'ev',
        label: 'Evidence quality',
        confidence: 'low',
        raw_score: 60,
        score: 60,
        swing: 0,
        severity: 'none',
        resolvable: true,
        resolution: 'Attach the customer research',
      });
      render(<DecisionConfidenceCard profile={profile({ criteria: [settled] })} />);

      expect(screen.queryByText('Assumption exposure')).not.toBeInTheDocument();
      expect(screen.getByText(/1 criteria not moving the score/)).toBeInTheDocument();
    });

    it('never presents no score exposure as strong evidence', () => {
      const settled = criterion({
        key: 'ev',
        label: 'Evidence quality',
        confidence: 'low',
        swing: 0,
        severity: 'none',
      });
      render(<DecisionConfidenceCard profile={profile({ criteria: [settled] })} />);

      fireEvent.click(screen.getByText(/criteria not moving the score/));
      // The weak grade stays visible, and the note says the score is what is
      // unaffected, not the evidence that is fine.
      expect(screen.getByText('Thin evidence')).toBeInTheDocument();
      expect(
        screen.getByText(/it can still be worth strengthening/),
      ).toBeInTheDocument();
    });

    it('only claims reversal from a server-computed challenger', () => {
      const { rerender } = render(<DecisionConfidenceCard profile={profile()} />);
      expect(screen.queryByText(/could put it ahead/)).not.toBeInTheDocument();

      rerender(
        <DecisionConfidenceCard
          profile={profile()}
          optionName="Option A"
          exposure={{
            leader: { name: 'Option A', score: 80 },
            challengers: [{
              name: 'Option B',
              score: 72,
              gap: 8,
              assumptions: [criterion({ severity: 'reversing' })],
            }],
          }}
        />,
      );
      expect(screen.getByText(/trails Option A by 8 points/)).toBeInTheDocument();
      expect(screen.getByText(/could put it ahead/)).toBeInTheDocument();
    });

    it('never names an option as overtaking itself', () => {
      // Viewing the challenger. Naming the currently-open card as the thing to
      // be overtaken produced "could put it ahead of [itself]" on screen.
      render(
        <DecisionConfidenceCard
          profile={profile()}
          optionName="Option B"
          exposure={{
            leader: { name: 'Option A', score: 80 },
            challengers: [{
              name: 'Option B',
              score: 68,
              gap: 12,
              assumptions: [criterion({ severity: 'reversing' })],
            }],
          }}
        />,
      );
      expect(screen.getByText(/This option trails Option A by 12 points/)).toBeInTheDocument();
      expect(screen.queryByText(/ahead of Option B/)).not.toBeInTheDocument();
    });
  });

  it('renders nothing without a profile', () => {
    const { container } = render(<DecisionConfidenceCard profile={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
