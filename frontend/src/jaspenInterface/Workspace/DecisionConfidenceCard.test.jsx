import React from 'react';
import { render, screen, within } from '@testing-library/react';
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
    source: 'conversation',
    rationale: 'The penalty figure was described but not traced to a system.',
    ...overrides,
  };
}

function profile(overrides = {}) {
  return {
    evidence_backed_pct: 55,
    assumption_dependent_pct: 45,
    score: 66,
    criteria: [criterion()],
    counts: { reversing: 0, material: 1, other: 0, resolvable: 1 },
    claims: [{ kind: 'material', text: '1 assumption could materially change the score' }],
    ...overrides,
  };
}

describe('DecisionConfidenceCard', () => {
  describe('the summary layer', () => {
    it('leads with the score and the evidence split', () => {
      render(<DecisionConfidenceCard profile={profile()} score={66} scoreCategory="Good" />);
      expect(screen.getByText('66')).toBeInTheDocument();
      expect(screen.getByText('Good')).toBeInTheDocument();
      expect(screen.getByText('55%')).toBeInTheDocument();
      expect(screen.getByText('45%')).toBeInTheDocument();
    });

    it('says what the ratio measures so it is not read as certainty', () => {
      render(<DecisionConfidenceCard profile={profile()} />);
      expect(
        screen.getByText('Evidence-backed share of the weighted decision'),
      ).toBeInTheDocument();
    });

    it('answers the decision questions without any expansion', () => {
      render(
        <DecisionConfidenceCard
          profile={profile()}
          optionName="Option B"
          exposure={{
            leader: { name: 'Option A', score: 74 },
            challengers: [{ name: 'Option B', gap: 8, assumptions: [criterion()] }],
          }}
        />,
      );
      expect(screen.getByText('Current standing')).toBeInTheDocument();
      expect(screen.getByText(/Trails Option A by 8 points/)).toBeInTheDocument();
      expect(screen.getByText('Key finding')).toBeInTheDocument();
      expect(screen.getByText('Highest-priority evidence')).toBeInTheDocument();
      expect(screen.getByText('What could change the answer')).toBeInTheDocument();
    });

    it('says the option leads when it is the leader', () => {
      render(
        <DecisionConfidenceCard
          profile={profile()}
          optionName="Option A"
          exposure={{ leader: { name: 'Option A', score: 74 }, challengers: [] }}
        />,
      );
      expect(screen.getByText(/Leads the options under consideration/)).toBeInTheDocument();
    });

    it('omits standing entirely when there are no other options', () => {
      render(<DecisionConfidenceCard profile={profile()} optionName="Only option" />);
      expect(screen.queryByText('Current standing')).not.toBeInTheDocument();
    });
  });

  describe('the detail layer', () => {
    it('shows every weighted criterion, none of it collapsed', () => {
      const many = profile({
        criteria: [
          criterion(),
          criterion({ key: 'ops', label: 'Execution readiness', severity: 'none', swing: 0, confidence: 'high', resolution: null }),
          criterion({ key: 'mkt', label: 'Market opportunity', severity: 'other', swing: 0.9, confidence: 'medium', resolution: null }),
        ],
      });
      const { container } = render(<DecisionConfidenceCard profile={many} />);

      // Every criterion is present in the detail layer without any disclosure
      // being opened. Scoped to the list because the highest-priority
      // criterion also, deliberately, appears in the summary above.
      const detail = within(container.querySelector('.dcc-criteria'));
      expect(detail.getByText('Financial viability')).toBeInTheDocument();
      expect(detail.getByText('Execution readiness')).toBeInTheDocument();
      expect(detail.getByText('Market opportunity')).toBeInTheDocument();
      // The old "Show N criteria" affordance is gone.
      expect(screen.queryByRole('button', { name: /show \d+ criteri/i })).not.toBeInTheDocument();
    });

    it('separates what Jaspen had from what is still needed', () => {
      render(<DecisionConfidenceCard profile={profile()} />);
      expect(screen.getByText('What Jaspen based this on')).toBeInTheDocument();
      expect(screen.getByText('Still unsupported')).toBeInTheDocument();
      expect(screen.getByText('Evidence needed')).toBeInTheDocument();
    });

    it('reports the weight, contribution and exposure for a criterion', () => {
      render(<DecisionConfidenceCard profile={profile()} />);
      expect(screen.getByText('25% of the decision')).toBeInTheDocument();
      expect(screen.getByText('contributes 45')).toBeInTheDocument();
      expect(screen.getByText('8.8 points of exposure')).toBeInTheDocument();
    });

    it('states the consequence of resolving each criterion', () => {
      render(<DecisionConfidenceCard profile={profile()} />);
      expect(
        screen.getByText('Resolving this could materially change the score.'),
      ).toBeInTheDocument();
    });

    it('never names a severity tier on screen', () => {
      render(<DecisionConfidenceCard profile={profile({
        criteria: [criterion({ severity: 'reversing' })],
      })} />);
      expect(screen.queryByText('reversing')).not.toBeInTheDocument();
      expect(screen.queryByText('material')).not.toBeInTheDocument();
    });
  });

  describe('the provenance limit', () => {
    it('labels the basis as reasoning, never as an evidence record', () => {
      render(<DecisionConfidenceCard profile={profile()} />);
      expect(
        screen.getByText(/It is not a record of which document or figure supported the score/),
      ).toBeInTheDocument();
    });

    it('describes the channel without claiming to know the input', () => {
      render(<DecisionConfidenceCard profile={profile({
        criteria: [criterion({ source: 'connector' })],
      })} />);
      expect(screen.getByText('From connected data')).toBeInTheDocument();
    });

    it('says nothing was recorded rather than inventing reasoning', () => {
      render(<DecisionConfidenceCard profile={profile({
        criteria: [criterion({ rationale: null, source: null })],
      })} />);
      expect(
        screen.getByText('No reasoning was recorded for this criterion.'),
      ).toBeInTheDocument();
    });
  });

  describe('the healthy case', () => {
    const clear = profile({
      evidence_backed_pct: 88,
      assumption_dependent_pct: 12,
      counts: { reversing: 0, material: 0, other: 1, resolvable: 0 },
      claims: [{
        kind: 'clear',
        text: 'No assumption currently carries enough weight to materially change the score.',
      }],
      criteria: [criterion({ severity: 'other', swing: 0.9, confidence: 'medium', resolution: null })],
    });

    it('states the affirmative finding', () => {
      render(<DecisionConfidenceCard profile={clear} />);
      expect(
        screen.getByText(/No assumption currently carries enough weight/),
      ).toBeInTheDocument();
    });

    it('explains why confidence is high and what would still strengthen it', () => {
      render(<DecisionConfidenceCard profile={clear} />);
      const answer = screen.getByText(/Most of the weighted decision rests on strong or moderate evidence/);
      expect(answer).toBeInTheDocument();
      // Completion without overclaiming: the gaps are named as still worth closing.
      expect(answer.textContent).toMatch(/closing them would strengthen the record/);
      expect(answer.textContent).not.toMatch(/sound|complete|no risk/i);
    });
  });

  it('renders nothing without a profile', () => {
    const { container } = render(<DecisionConfidenceCard profile={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
