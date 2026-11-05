import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
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
  expect(screen.getByRole('button', { name: 'Record a decision' })).toBeVisible();
});
