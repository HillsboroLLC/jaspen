import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import OnePagerReport from './OnePagerReport';
import { closestReadableShade } from './reportModel';

const snapshot = {
  scorecard: {
    project_name: 'Denver Bike Lane Package',
    jaspen_score: 47,
    decision_kit: 'rfp_bid',
    recommendation: { label: 'No-Bid' },
    executive_summary: 'The case rests mostly on assumptions. Second sentence.',
  },
};

const renderEditor = (onSavePresentation, reportSnapshot = snapshot) => render(
  <OnePagerReport
    artifactType="scorecard"
    snapshot={reportSnapshot}
    title="Denver Bike Lane Package"
    canEdit
    editing
    onSavePresentation={onSavePresentation}
  />,
);

test('a color too light for white text is flagged before saving, with the nearest readable shade', async () => {
  const onSave = jest.fn().mockResolvedValue(undefined);
  renderEditor(onSave);

  fireEvent.change(screen.getByLabelText('Accent'), { target: { value: '#e8472c' } });

  const shade = closestReadableShade('#E8472C');
  expect(screen.getByText(`Too light to read on white. Saving will use ${shade}.`)).toBeInTheDocument();
  const save = screen.getByRole('button', { name: 'Save' });
  expect(save).toBeEnabled();

  await userEvent.click(save);
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  const { accent } = onSave.mock.calls[0][0].colors;
  expect(accent).toBe(shade);
});

test('a wording-only edit saves when the report already has unreadable colors', async () => {
  const onSave = jest.fn().mockResolvedValue(undefined);
  const savedSnapshot = {
    ...snapshot,
    presentation: {
      colors: { accent: '#E8472C', ink: '#AAAAAA', tint: '#F7F7F7' },
    },
  };
  renderEditor(onSave, savedSnapshot);

  const save = screen.getByRole('button', { name: 'Save' });
  expect(save).toBeEnabled();
  fireEvent.change(screen.getByLabelText('Headline'), { target: { value: 'A clearer headline' } });
  await userEvent.click(save);

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  expect(onSave.mock.calls[0][0]).toEqual(expect.objectContaining({
    colors: {
      accent: closestReadableShade('#E8472C'),
      ink: closestReadableShade('#AAAAAA'),
      tint: '#F7F7F7',
    },
    text: expect.objectContaining({ headline: 'A clearer headline' }),
  }));
});

test('readable colors are sent unchanged', async () => {
  const onSave = jest.fn().mockResolvedValue(undefined);
  const colors = { accent: '#A0036C', ink: '#1B2342', tint: '#EEF5F7' };
  renderEditor(onSave, { ...snapshot, presentation: { colors } });

  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  expect(onSave.mock.calls[0][0].colors).toEqual(colors);
});

test('a refused save is explained inside the editor in plain words', async () => {
  const onSave = jest.fn().mockRejectedValue(
    new Error('That color is too light to read on white. Choose a darker shade.'),
  );
  renderEditor(onSave);

  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  expect(await screen.findByText('That color is too light to read on white. Choose a darker shade.')).toBeInTheDocument();
  expect(screen.queryByText(/api\/v1/)).not.toBeInTheDocument();
});

const detailedCard = {
  id: 'detail-card',
  project_name: 'Solar retrofit',
  jaspen_score: 68,
  component_scores: { financial_health: 71 },
  component_rationale: { financial_health: 'Savings cover the investment over time.' },
  dimensions: {
    strategic_fit: { label: 'Strategic fit', score: 76, confidence: 'medium', rationale: 'Supports the approved carbon target.' },
  },
  scoring_rubric: { criteria: [{ key: 'strategic_fit', label: 'Strategic fit', weight: 1 }] },
  evidence_profile: {
    evidence_backed_pct: 60,
    assumption_dependent_pct: 40,
    criteria: [{
      key: 'strategic_fit', label: 'Strategic fit', source: 'conversation',
      evidence_references: [{ kind: 'attachment', excerpt: 'Target approved for 2030', locator: { filename: 'Plan.pdf', location: { page: 4 } } }],
    }],
  },
  facts: { target: { label: 'Carbon target', value: 2030, source: 'user' } },
  assumptions: ['Energy prices remain near the forecast.', { statement: 'Roof life exceeds ten years.' }],
  top_risks: [{ risk: 'Installation could disrupt operations.', mitigation: 'Phase work by building.' }],
  financial_impact: { annual_savings: 240000 },
  metrics: { payback: { label: 'Payback', value: 4.2, unit: 'years' } },
};

test('the scoring accordion uses one-pager detail styles and includes the complete synthetic scorecard', async () => {
  const { container } = render(
    <OnePagerReport artifactType="scorecard" snapshot={{ scorecard: detailedCard }} title="Solar retrofit" showActions={false} />,
  );
  const toggle = screen.getByRole('button', { name: /See how this was scored/ });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await userEvent.click(toggle);

  expect(screen.getByRole('heading', { name: 'Category scores' })).toBeVisible();
  expect(screen.getByText('Savings cover the investment over time.')).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Criterion scores and rationale' })).toBeVisible();
  const details = container.querySelector('.op-details__body');
  expect(details).toHaveTextContent('Supports the approved carbon target.');
  expect(details).toHaveTextContent('60% stated facts');
  expect(details).toHaveTextContent('Plan.pdf · 4');
  expect(details).toHaveTextContent('Energy prices remain near the forecast.');
  expect(details).toHaveTextContent('Roof life exceeds ten years.');
  expect(details).toHaveTextContent('Installation could disrupt operations.');
  expect(details).toHaveTextContent('Annual Savings');
  expect(details).toHaveTextContent('Payback');
  expect(container.querySelector('[class*="score-dashboard"]')).toBeNull();
});

test('financials, metrics, facts and evidence quotes appear only when present in the disclosed snapshot', async () => {
  const { container, rerender } = render(
    <OnePagerReport artifactType="scorecard" snapshot={{ scorecard: detailedCard }} title="Solar retrofit" showActions={false} />,
  );
  await userEvent.click(screen.getByRole('button', { name: /See how this was scored/ }));
  expect(container.querySelector('.op-details__body')).toHaveTextContent('Carbon target');
  expect(container.querySelector('.op-details__body')).toHaveTextContent('Target approved for 2030');
  expect(container.querySelector('.op-details__body')).toHaveTextContent('Annual Savings');
  expect(container.querySelector('.op-details__body')).toHaveTextContent('Payback');

  const disclosedCard = Object.fromEntries(
    Object.entries(detailedCard).filter(([key]) => !['facts', 'metrics', 'financial_impact'].includes(key)),
  );
  const withoutEvidence = {
    ...disclosedCard,
    evidence_profile: {
      ...disclosedCard.evidence_profile,
      criteria: disclosedCard.evidence_profile.criteria.map(({ evidence_references: references, ...criterion }) => criterion),
    },
  };
  rerender(<OnePagerReport artifactType="scorecard" snapshot={{ scorecard: withoutEvidence }} title="Solar retrofit" showActions={false} />);
  expect(container.querySelector('.op-details__body')).not.toHaveTextContent('Carbon target');
  expect(container.querySelector('.op-details__body')).not.toHaveTextContent('Target approved for 2030');
  expect(container.querySelector('.op-details__body')).not.toHaveTextContent('Annual Savings');
  expect(container.querySelector('.op-details__body')).not.toHaveTextContent('Payback');
});

test('the report body markup is identical across workspace, preview and public action variants', () => {
  const reportSnapshot = {
    scorecard: detailedCard,
    presentation: {
      colors: { accent: '#0F6E77', ink: '#1B2342', tint: '#EEF5F7' },
      text: { brand_name: 'ACME', company_name: 'Acme Energy', headline: 'Should Acme fund the retrofit?' },
    },
  };
  const markup = (props) => {
    const view = render(<OnePagerReport artifactType="scorecard" snapshot={reportSnapshot} title="Solar retrofit" {...props} />);
    const report = view.container.querySelector('.op-report').cloneNode(true);
    report.querySelector('.op-actions')?.remove();
    const html = report.innerHTML;
    view.unmount();
    return html;
  };
  const workspace = markup({ showActions: false });
  const preview = markup({ canEdit: false, showActions: false });
  const publicPage = markup({ actions: <button type="button">Download PDF</button> });
  expect(preview).toBe(workspace);
  expect(publicPage).toBe(workspace);
  cleanup();
});
