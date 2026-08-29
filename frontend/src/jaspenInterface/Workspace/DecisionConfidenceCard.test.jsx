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

function summary(overrides = {}) {
  return {
    verdict: 'Scores 66 of 100, rated Good.',
    standing: 'Trails Consolidate the Reno hub by 8 points, a gap the assumptions below could close.',
    confidence: '55% of the weighted decision rests on evidence. The remaining 45% depends on assumptions.',
    concentration: 'Most of that exposure sits in one criterion, Financial viability, which carries 20% of the decision.',
    sensitivity: 'Resolving the assumptions below could materially change the score, though not the ranking on current evidence.',
    next_step: 'Financial viability: Connect NetSuite or upload the model',
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

    it('reads as a briefing rather than a label and value list', () => {
      const { container } = render(
        <DecisionConfidenceCard profile={profile()} summary={summary()} />,
      );
      const briefing = container.querySelector('.dcc-briefing');
      expect(briefing).toBeInTheDocument();
      // Continuous prose, so it can be quoted straight into a room.
      expect(briefing.textContent).toContain('Scores 66 of 100, rated Good.');
      expect(briefing.textContent).toContain('Trails Consolidate the Reno hub by 8 points');
      expect(briefing.textContent).toContain('55% of the weighted decision rests on evidence');
      expect(briefing.textContent).toContain('Most of that exposure sits in one criterion');
    });

    it('surfaces exactly one instruction', () => {
      render(<DecisionConfidenceCard profile={profile()} summary={summary()} />);
      expect(screen.getByText('Do this next')).toBeInTheDocument();
      expect(
        screen.getByText(/Financial viability: Connect NetSuite/),
      ).toBeInTheDocument();
    });

    it('renders no briefing when the server composed none', () => {
      const { container } = render(<DecisionConfidenceCard profile={profile()} />);
      expect(container.querySelector('.dcc-briefing')).toBeNull();
      // The detail still stands on its own.
      expect(container.querySelector('.dcc-criteria')).toBeInTheDocument();
    });

    it('omits the action line when there is nothing to do', () => {
      render(
        <DecisionConfidenceCard
          profile={profile()}
          summary={summary({ next_step: undefined })}
        />,
      );
      expect(screen.queryByText('Do this next')).not.toBeInTheDocument();
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
      expect(screen.getByText("Jaspen's assessment")).toBeInTheDocument();
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
        screen.getByText(/nothing here should be read as a source citation or an audit trail/),
      ).toBeInTheDocument();
    });

    it('never states connector provenance as fact', () => {
      // "From connected data" read as "Jaspen retrieved this from a system you
      // connected", which is an assertion about system state that `source`
      // cannot support. It is the model's own claim, and nothing verifies it.
      render(<DecisionConfidenceCard profile={profile({
        criteria: [criterion({ source: 'connector' })],
      })} />);
      expect(screen.queryByText('From connected data')).not.toBeInTheDocument();
      expect(screen.getByText('Jaspen reports drawing on connected data')).toBeInTheDocument();
    });

    it('calls the narrative an assessment rather than a basis', () => {
      render(<DecisionConfidenceCard profile={profile()} />);
      expect(screen.getByText("Jaspen's assessment")).toBeInTheDocument();
      expect(screen.queryByText('What Jaspen based this on')).not.toBeInTheDocument();
    });

    it('says nothing was recorded rather than inventing reasoning', () => {
      render(<DecisionConfidenceCard profile={profile({
        criteria: [criterion({ rationale: null, source: null })],
      })} />);
      expect(
        screen.getByText('No assessment was recorded for this criterion.'),
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

    it('states the affirmative finding and why, without overclaiming', () => {
      const clearSummary = summary({
        sensitivity: 'No assumption currently carries enough weight to change the '
          + 'score materially. Closing the remaining gaps would strengthen the '
          + 'record rather than move the answer.',
        next_step: undefined,
        concentration: undefined,
      });
      render(<DecisionConfidenceCard profile={clear} summary={clearSummary} />);

      const line = screen.getByText(/No assumption currently carries enough weight/);
      expect(line).toBeInTheDocument();
      expect(line.textContent).toMatch(/strengthen the record rather than move the answer/);
      expect(line.textContent).not.toMatch(/sound|complete|no risk/i);
    });
  });

  it('renders nothing without a profile', () => {
    const { container } = render(<DecisionConfidenceCard profile={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
