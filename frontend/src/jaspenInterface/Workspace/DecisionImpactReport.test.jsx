import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import DecisionImpactReport from './DecisionImpactReport';
import { jasApi } from '../../services/jaspenApi';

jest.mock('../../services/jaspenApi', () => ({
  jasApi: { getDecisionImpactReport: jest.fn() },
}));

beforeAll(() => {
  window.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
});

function report() {
  return {
    report: {
      baseline: {
        sealed_at: '2026-09-01T12:00:00Z',
        sealed_by: 'user_confirmed',
        submission_ref: { turn_count: 2, attachment_count: 1 },
        measures: { A1: { value: 1 } },
      },
      current: { leading_option: 'Phased migration', measures: { A1: { value: 3 } } },
      impact: {
        verified_comparison: true,
        verdict: 'material',
        moved: [{ id: 'A1', label: 'Alternatives evaluated', from: 1, to: 3 }],
        unmoved: [{ id: 'B1', label: 'Decision owner', from: 'COO', to: 'COO' }],
        excluded_unconfirmed: [],
        not_applicable: [],
        interventions: [],
        thresholds: { STRONG_PP: 20 },
        methodology_version: 'v1',
      },
      activity: { available: true, counts_by_type: { evidence_requested: 2 } },
      narrative: { what_changed: 'The team compared more alternatives and retained the same owner.' },
      measure_catalog: {
        A1: { label: 'Alternatives evaluated', class: 'state' },
      },
      provenance_note: 'Compared from the sealed intake record.',
    },
  };
}

it('leads with a flat decision story and keeps the before/challenge/after detail in a drill-down', async () => {
  jasApi.getDecisionImpactReport.mockResolvedValue(report());
  const { container } = render(<DecisionImpactReport threadId="thread-1" />);

  await waitFor(() => expect(screen.getByText('Material change')).toBeInTheDocument());
  const executive = container.querySelector('.dir-executive');
  expect(executive).toHaveTextContent('The team compared more alternatives');
  expect(executive).toHaveTextContent('The decision story so far');

  const audit = container.querySelector('.dir-audit');
  expect(audit).not.toHaveAttribute('open');
  expect(screen.getByText('What you brought to the decision')).toBeInTheDocument();
  expect(screen.getByText('1 · Before analysis')).toBeInTheDocument();
  expect(screen.getByText("2 · Jaspen's challenge")).toBeInTheDocument();
  expect(screen.getByText('requests for supporting evidence').closest('li'))
    .toHaveTextContent('2 requests for supporting evidence');
  expect(screen.getByText('3 · After analysis')).toBeInTheDocument();
  fireEvent.click(screen.getByText('See the before, challenge, and after'));
  expect(audit).toHaveAttribute('open');
  expect(screen.getByText('What did not move')).toBeInTheDocument();
  expect(screen.getByText(/STRONG_PP 20/)).toBeInTheDocument();
});
