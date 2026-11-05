import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { DecisionIntelligenceOverview } from './Insights';

jest.mock('../Workspace/JaspenAiDrawer', () => () => null);
jest.mock('../Workspace/JaspenClient', () => ({ Jaspen: {} }));

function response(payload, ok = true) {
  return { ok, json: async () => payload };
}

const EMPTY = {
  organization: { id: 'org-1', name: 'Acme' },
  scope: 'mine', requested_scope: 'organization', can_manage: false,
  calculation_label: 'Calculated insights',
  metrics: { decision_records: 0, decisions_made: 0, in_progress: 0, needs_attention: 0, lessons_recorded: 0, outcomes_recorded: 0, plans_in_execution: 0 },
  decisions: [], open_items: [], learning: { lessons: [], outcomes: [] },
  progress: { monthly: [], plans_in_execution: [] }, activity_by_member: [],
};

afterEach(() => {
  jest.restoreAllMocks();
});

it('shows the organization switch only to managers and reloads my activity', async () => {
  const organization = {
    ...EMPTY, scope: 'organization', requested_scope: 'organization', can_manage: true,
    metrics: { ...EMPTY.metrics, decision_records: 1, decisions_made: 1 },
    decisions: [{ record_id: 'r1', thread_id: 't1', title: 'Choose vendor', chosen_option: 'Vendor A', decided_at: '2026-11-01T12:00:00' }],
  };
  const mine = { ...organization, scope: 'mine', requested_scope: 'mine', decisions: [], metrics: { ...organization.metrics, decisions_made: 0 } };
  global.fetch = jest.fn()
    .mockResolvedValueOnce(response(organization))
    .mockResolvedValueOnce(response(mine));

  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  expect(await screen.findByRole('button', { name: 'Organization' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'My activity' })).toBeVisible();
  expect(await screen.findByText('Vendor A')).toBeVisible();
  expect(screen.getByText('Nov 1, 2026')).toBeVisible();
  expect(screen.queryByText(/12:00:00/)).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole('button', { name: 'My activity' }));
  await waitFor(() => expect(global.fetch).toHaveBeenLastCalledWith(
    expect.stringContaining('scope=mine'), expect.any(Object),
  ));
});

it('does not show a scope switch to non-managers and provides empty-state next steps', async () => {
  const navigate = jest.fn();
  global.fetch = jest.fn().mockResolvedValue(response(EMPTY));
  render(<DecisionIntelligenceOverview navigate={navigate} />);

  expect(await screen.findByText('No decision records yet')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Organization' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Start a decision' }));
  expect(navigate).toHaveBeenCalledWith('/new');
  expect(screen.queryByRole('button', { name: 'Record a decision' })).not.toBeInTheDocument();
});

it('orders the top three attention items and keeps the remainder collapsed', async () => {
  const overview = {
    ...EMPTY,
    metrics: { ...EMPTY.metrics, decision_records: 1, in_progress: 1, needs_attention: 1 },
    open_items: [{
      record_id: 'r1', thread_id: 't1', title: 'Choose vendor', status: 'recorded',
      unresolved: {
        gates: [
          { option: 'Choose vendor', label: 'Legal approval', status: 'fail' },
          { option: 'Vendor B', label: 'Security review', status: 'failed' },
          { option: 'Vendor B', label: 'Finance review', status: 'unknown' },
        ],
        assumptions: [
          { option: 'Vendor B', label: 'Adoption remains steady', status: 'open' },
          { option: 'Vendor B', label: 'Hiring stays on plan', status: 'open' },
        ],
        missing_evidence: [{ option: 'Vendor B', label: 'Reference evidence', confidence: 'assumed' }],
      },
    }],
  };
  global.fetch = jest.fn().mockResolvedValue(response(overview));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);

  expect(await screen.findByText('2 failed gates · 1 not yet assessed · 2 assumptions · 1 evidence gap')).toBeVisible();
  const gapList = screen.getByText('Legal approval').closest('ul');
  expect(within(gapList).getAllByRole('listitem').map((node) => node.textContent)).toEqual([
    'Failed gateLegal approval',
    'Failed gateVendor B: Security review',
    'AssumptionVendor B: Adoption remains steady',
  ]);
  expect(screen.queryByText('Finance review')).not.toBeInTheDocument();
  expect(screen.queryByText('Hiring stays on plan')).not.toBeInTheDocument();
  expect(screen.queryByText('Reference evidence')).not.toBeInTheDocument();
  expect(screen.queryByText(/Choose vendor: Legal approval/)).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole('button', { name: 'Show all attention items for Choose vendor' }));
  expect(screen.getByText((_, node) => node?.parentElement?.classList.contains('di-gap-list') && node.textContent.includes('Hiring stays on plan'))).toBeVisible();
  expect(screen.getByText((_, node) => node?.parentElement?.classList.contains('di-gap-list') && node.textContent.includes('Reference evidence'))).toBeVisible();
  expect(screen.queryByText('Finance review')).not.toBeInTheDocument();
});

it('shows five recent decisions before the list is expanded and formats month labels', async () => {
  const decisions = Array.from({ length: 6 }, (_, index) => ({
    id: `d${index}`, record_id: `r${index}`, thread_id: `t${index}`,
    title: `Decision ${index + 1}`, chosen_option: `Choice ${index + 1}`,
    decided_at: `2026-10-${String(20 - index).padStart(2, '0')}T12:34:56`,
  }));
  const overview = {
    ...EMPTY,
    metrics: { ...EMPTY.metrics, decision_records: 6, decisions_made: 6 },
    decisions,
    progress: { monthly: [{ month: '2026-10', records_created: 6, decisions_made: 6 }], plans_in_execution: [] },
  };
  global.fetch = jest.fn().mockResolvedValue(response(overview));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);

  expect(await screen.findByText('Choice 5')).toBeVisible();
  expect(screen.queryByText('Choice 6')).not.toBeInTheDocument();
  expect(screen.getByText('Oct 2026')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Show all decisions' }));
  expect(screen.getByText('Choice 6')).toBeVisible();
});
