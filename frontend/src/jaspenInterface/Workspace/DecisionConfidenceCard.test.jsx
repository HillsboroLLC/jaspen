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

  it('says what the ratio measures so it is not read as certainty', () => {
    render(<DecisionConfidenceCard profile={profile()} />);
    expect(
      screen.getByText('Evidence-backed share of the weighted decision'),
    ).toBeInTheDocument();
  });

  describe('hierarchy', () => {
    it('promotes the most severe claim and demotes the rest', () => {
      const withBoth = profile({
        claims: [
          { kind: 'reversing', text: '1 assumption could change which option leads' },
          { kind: 'resolvable', text: '2 gaps can be resolved before you commit' },
        ],
      });
      const { container } = render(<DecisionConfidenceCard profile={withBoth} />);

      // The severe one carries the finding treatment.
      expect(container.querySelector('.dcc-finding-text').textContent).toBe(
        '1 assumption could change which option leads',
      );
      // The rest are context, not competing findings.
      expect(container.querySelector('.dcc-secondary-claims').textContent).toContain(
        '2 gaps can be resolved before you commit',
      );
    });

    it('lifts the highest-leverage resolution out of the register', () => {
      const { container } = render(<DecisionConfidenceCard profile={profile()} />);
      const action = container.querySelector('.dcc-action-text');
      expect(action.textContent).toContain('Financial viability');
      expect(action.textContent).toContain('Connect NetSuite or upload the model');
    });

    it('offers no action when nothing resolvable moves the score', () => {
      const settled = profile({
        criteria: [criterion({ swing: 0, severity: 'none', resolvable: false, resolution: null })],
        claims: [],
      });
      const { container } = render(<DecisionConfidenceCard profile={settled} />);
      expect(container.querySelector('.dcc-action')).toBeNull();
      expect(container.querySelector('.dcc-finding')).toBeNull();
    });
  });

  it('states each resolution once, never twice', () => {
    // The top exposure's resolution is promoted into the action block, so
    // repeating it in its own register row reads as two instructions.
    render(<DecisionConfidenceCard profile={profile()} />);
    expect(
      screen.getAllByText(/Connect NetSuite or upload the model/),
    ).toHaveLength(1);
    expect(screen.queryByText('Evidence needed')).not.toBeInTheDocument();
  });

  it('keeps the register resolution for assumptions that were not promoted', () => {
    const two = profile({
      criteria: [
        criterion(),
        criterion({
          key: 'ops',
          label: 'Execution readiness',
          swing: 6,
          resolution: 'Attach the staffing plan',
        }),
      ],
    });
    render(<DecisionConfidenceCard profile={two} />);
    expect(screen.getByText('Evidence needed')).toBeInTheDocument();
    expect(screen.getByText(/Attach the staffing plan/)).toBeInTheDocument();
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
