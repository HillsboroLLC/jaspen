import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { DecisionIntelligenceOverview } from './Insights';

jest.mock('../Workspace/JaspenAiDrawer', () => () => null);
jest.mock('../Workspace/JaspenClient', () => ({ Jaspen: {} }));
jest.mock('react-chartjs-2', () => {
  const ReactModule = require('react');
  function Chart({ data, options }) {
    return ReactModule.createElement('div', { 'data-testid': 'chart' },
      (data.labels || []).map((label, index) => ReactModule.createElement('button', {
        type: 'button', key: `${label}:${index}`, onClick: () => options?.onClick?.({}, [{ index }]),
      }, `Chart: ${label}`)));
  }
  return { Bar: Chart, Line: Chart, Pie: Chart };
});

function response(payload, ok = true) { return { ok, json: async () => payload }; }

const ROWS = [
  {
    id: 'r1', thread_id: 't1', title: 'Choose vendor', owner: { id: 'u1', name: 'Ava' }, status: 'recorded',
    decision_type: 'vendor', decision_kit: null, created_at: '2026-10-01T12:00:00', decided_at: null,
    days_to_decide: null, chosen_options: [], top_option_score: 78, tags: ['procurement'],
    gaps: { failed_gates: 1, not_assessed_gates: 0, open_assumptions: 1, missing_evidence: 0, items: {
      failed_gates: [{ label: 'Security approval' }], not_assessed_gates: [],
      open_assumptions: [{ label: 'Adoption holds' }], missing_evidence: [],
    } }, plan: { tasks_total: 0, tasks_completed: 0 }, lesson_count: 0, outcome_count: 0, lessons: [], outcomes: [],
  },
  {
    id: 'r2', thread_id: 't2', title: 'Open new region', owner: { id: 'u2', name: 'Ben' }, status: 'decided',
    decision_type: null, decision_kit: 'general', created_at: '2026-09-01T12:00:00', decided_at: '2026-09-11T12:00:00',
    days_to_decide: 10, chosen_options: ['Northeast'], top_option_score: 91, tags: ['growth'],
    gaps: { failed_gates: 0, not_assessed_gates: 0, open_assumptions: 0, missing_evidence: 0, items: {
      failed_gates: [], not_assessed_gates: [], open_assumptions: [], missing_evidence: [],
    } }, plan: { tasks_total: 10, tasks_completed: 4 }, lesson_count: 1, outcome_count: 1,
    lessons: [{ text: 'Sequence hiring first.' }], outcomes: [{ text: 'Launch approved.' }],
  },
];

const BASE = {
  organization: { id: 'org-1', name: 'Acme' }, scope: 'mine', requested_scope: 'organization', can_manage: false,
  can_view_organization: false, calculation_label: 'Calculated insights', rows: ROWS,
  facets: { statuses: ['decided', 'recorded'], types_kits: ['general', 'vendor'], members: [{ id: 'u1', name: 'Ava' }, { id: 'u2', name: 'Ben' }], tags: ['growth', 'procurement'] },
};

beforeEach(() => window.localStorage.clear());
afterEach(() => jest.restoreAllMocks());

async function advanceRefreshTimer() {
  await act(async () => {
    jest.advanceTimersByTime(60000);
    await Promise.resolve();
  });
}

it('hides the organization switch for a single-user account', async () => {
  global.fetch = jest.fn().mockResolvedValue(response({ ...BASE, rows: [], facets: { statuses: [] } }));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  expect(await screen.findByText('No decision records yet')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Organization' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'My activity' })).not.toBeInTheDocument();
});

it('shows the scope switch only when the server allows organization viewing', async () => {
  global.fetch = jest.fn()
    .mockResolvedValueOnce(response({ ...BASE, scope: 'organization', can_manage: true, can_view_organization: true }))
    .mockResolvedValue(response({ ...BASE, scope: 'mine', can_manage: true, can_view_organization: true }));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  expect(await screen.findByRole('button', { name: 'Organization' })).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'My activity' }));
  await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('scope=mine'), expect.any(Object)));
});

it('filters every dashboard surface and chart clicks apply a filter', async () => {
  global.fetch = jest.fn().mockResolvedValue(response(BASE));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  expect(await screen.findByRole('button', { name: /Decisions\s*2/ })).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText('Status'), ['decided']);
  expect(screen.getByRole('button', { name: /Decisions\s*1/ })).toBeVisible();
  expect(screen.queryByText('Choose vendor')).not.toBeInTheDocument();
  expect(screen.getByText('Open new region')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  await userEvent.click(screen.getAllByRole('button', { name: 'Chart: recorded' })[0]);
  expect(screen.getByRole('button', { name: /Decisions\s*1/ })).toBeVisible();
  expect(screen.getByText('Choose vendor')).toBeVisible();
});

it('clicking a KPI tile applies its filter', async () => {
  global.fetch = jest.fn().mockResolvedValue(response(BASE));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await userEvent.click(await screen.findByRole('button', { name: /Needs attention\s*1/ }));
  expect(screen.getByText('Choose vendor')).toBeVisible();
  expect(screen.queryByText('Open new region')).not.toBeInTheDocument();
});

it('sorts and expands the decision table', async () => {
  global.fetch = jest.fn().mockResolvedValue(response(BASE));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  const table = (await screen.findByRole('heading', { name: 'Decisions' })).closest('section');
  await userEvent.click(within(table).getByRole('button', { name: 'Decision' }));
  const rowButtons = within(table).getAllByRole('button', { name: /Choose vendor|Open new region/ });
  expect(rowButtons[0]).toHaveTextContent('Choose vendor');
  await userEvent.click(within(table).getByRole('button', { name: 'Choose vendor' }));
  expect(within(table).getByText('Security approval')).toBeVisible();
  expect(within(table).getByRole('link', { name: /Open project/ })).toHaveAttribute('href', '/new?session_id=t1');
});

it('clear filters resets search and restores rows', async () => {
  global.fetch = jest.fn().mockResolvedValue(response(BASE));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  const search = await screen.findByLabelText('Search decisions');
  await userEvent.type(search, 'region');
  expect(screen.queryByText('Choose vendor')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(screen.getByText('Choose vendor')).toBeVisible();
  expect(search).toHaveValue('');
});

describe('live overview refresh', () => {
  const LIVE_BASE = { ...BASE, scope: 'organization', requested_scope: 'organization', can_view_organization: true };

  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('refreshes after 60 seconds without showing the initial loader again', async () => {
    global.fetch = jest.fn().mockResolvedValue(response(LIVE_BASE));
    render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
    expect(await screen.findByText('Updated just now')).toBeVisible();
    expect(global.fetch).toHaveBeenCalledTimes(1);

    await advanceRefreshTimer();

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(screen.queryByText('Loading your decision dashboard…')).not.toBeInTheDocument();
  });

  it('refreshes when the tab becomes visible again', async () => {
    let visibility = 'visible';
    jest.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
    global.fetch = jest.fn().mockResolvedValue(response(LIVE_BASE));
    render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
    expect(await screen.findByText('Updated just now')).toBeVisible();

    visibility = 'hidden';
    fireEvent(document, new Event('visibilitychange'));
    visibility = 'visible';
    fireEvent(document, new Event('visibilitychange'));
    await act(async () => { await Promise.resolve(); });

    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it('pauses the refresh timer while the tab is hidden', async () => {
    let visibility = 'visible';
    jest.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
    global.fetch = jest.fn().mockResolvedValue(response(LIVE_BASE));
    render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
    expect(await screen.findByText('Updated just now')).toBeVisible();

    visibility = 'hidden';
    fireEvent(document, new Event('visibilitychange'));
    await advanceRefreshTimer();

    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('preserves filters, sort order, page, and expanded rows across a refresh', async () => {
    const manyRows = Array.from({ length: 27 }, (_, index) => ({
      ...ROWS[0],
      id: `row-${index + 1}`,
      thread_id: `thread-${index + 1}`,
      title: `Decision ${String(index + 1).padStart(2, '0')}`,
    }));
    const payload = { ...LIVE_BASE, rows: manyRows };
    global.fetch = jest.fn().mockResolvedValue(response(payload));
    render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
    const search = await screen.findByLabelText('Search decisions');
    fireEvent.change(search, { target: { value: 'Decision' } });
    const table = screen.getByRole('heading', { name: 'Decisions' }).closest('section');
    fireEvent.click(within(table).getByRole('button', { name: 'Decision' }));
    fireEvent.click(within(table).getByRole('button', { name: 'Next' }));
    fireEvent.click(within(table).getByRole('button', { name: 'Decision 26' }));

    await advanceRefreshTimer();

    expect(search).toHaveValue('Decision');
    expect(screen.getByRole('button', { name: /Search: Decision/ })).toBeVisible();
    expect(within(table).getByRole('button', { name: 'Decision ↑' })).toBeVisible();
    expect(within(table).getByText('Page 2 of 2')).toBeVisible();
    expect(within(table).getByRole('button', { name: 'Decision 26' })).toHaveAttribute('aria-expanded', 'true');
    expect(within(table).getByText('Security approval')).toBeVisible();
  });

  it('keeps the last data when a background refresh fails', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce(response(LIVE_BASE))
      .mockResolvedValueOnce(response({ error: 'Temporary failure' }, false));
    render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
    expect(await screen.findByText('Choose vendor')).toBeVisible();

    await advanceRefreshTimer();

    expect(screen.getByText('Choose vendor')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Updated 1 min ago')).toBeVisible();
  });
});
