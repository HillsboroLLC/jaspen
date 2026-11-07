import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { DecisionIntelligenceOverview } from './Insights';

jest.mock('../Workspace/JaspenAiDrawer', () => () => null);
jest.mock('../Workspace/JaspenClient', () => ({ Jaspen: {} }));

const ROW = {
  id: 'record-1:vendor-a', record_id: 'record-1', thread_id: 'thread-1',
  decision_title: 'Choose a vendor', decision_kind: 'Vendor selection',
  owner: { id: 'u1', name: 'Ava' }, option_key: 'vendor-a', option_name: 'Vendor A',
  state: 'pursued', state_source: 'conversation', state_since: '2026-10-02T12:00:00',
  first_scored_at: '2026-10-01T12:00:00', first_plan_at: '2026-10-01T13:00:00',
  score: 82, score_band: 'Strong', evidence_backed_pct: 60,
  history: [{ disposition: 'pursue', source: 'conversation', quote: 'Use Vendor A', time: '2026-10-02T12:00:00' }],
  gaps: [{ key: 'security', label: 'Security', task_created: true, task_completed: false, resolved: false }],
  required_checks: [{ key: 'security', label: 'Security approval', status: 'failed' }],
  triggers: [{ kind: 'failed_required_check_without_task', evidence: { gate_key: 'security', gate_label: 'Security approval', status: 'failed' }, next_step_ref: { type: 'gate', id: 'security' }, available: true }],
  plan: { tasks_total: 3, tasks_completed: 1 }, outcomes: [], lessons: [],
};

const metric = (value, extra = {}) => ({ value, numerator: value, denominator: 1, coverage: 1, unavailable_reason: null, ...extra });
const BASE = {
  schema_version: 3,
  organization: { id: 'org-1', name: 'Acme' },
  scope: 'mine', requested_scope: 'organization', can_manage: false,
  can_view_organization: false, show_scope_control: false,
  summary: [{ kind: 'exception', count: 1, option_id: ROW.id, trigger_kind: 'failed_required_check_without_task' }],
  activity: {
    total_scored: metric(4), pursued: metric(1), not_pursued: metric(1), open: metric(1), archived: metric(1),
    reconciles: true, needs_attention: [ROW],
    average_time_to_plan_hours: metric(1, { within_one_hour: 1 }),
    flow: [{ date: '2026-09-28', scored: 1, decided: 0 }, { date: '2026-10-05', scored: 1, decided: 1 }],
    by_kind: [{ kind: 'Vendor selection', scored: 1, pursued: 1, not_pursued: 0, open: 0 }], plans: [ROW],
  },
  effectiveness: {
    acting_on: [{ state: 'pursued', total: 1, bands: { Strong: 1 }, mostly_assumed: 0 }],
    gap_follow_through: { identified: 1, task_created: 1, task_completed: 0, resolved: 0, result: 0 },
    evidence_at_commitment: metric(null, { unavailable_reason: 'insufficient_months', points: [{ month: '2026-10', evidence_backed_pct: 60, n: 1 }] }),
    recurring_gaps: [{ kind: 'Vendor selection', key: 'security', label: 'Security', decisions_affected: 1, decisions_total: 1, resolved_later: 0 }],
    outcomes: { pursued: 1, success_measure_captured: 0, implementation_complete: 0, awaiting_measurement: 0, outcomes_recorded: 0, measured: 0, met_expectation: 0, lessons: 0 },
  },
  register: { rows: [ROW], total: 1, page: 1, per_page: 25, pages: 1 },
  facets: { states: ['pursued', 'not_pursued', 'open', 'archived'], kinds: ['Vendor selection'], members: [] },
};

const response = (payload = BASE, ok = true) => ({ ok, json: async () => payload });

beforeEach(() => { window.localStorage.clear(); global.fetch = jest.fn().mockResolvedValue(response()); });
afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); });

it('renders the v3 activity, effectiveness, reconciliation, and grouped register', async () => {
  const { container } = render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await screen.findByText('Updated live · last refresh just now');
  expect(screen.getByRole('heading', { name: 'Summary' })).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Activity' })).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Effectiveness' })).toBeVisible();
  expect(screen.getByText('Pursued 1 · Not pursued 1 · Open 1 · Archived 1 = 4 scored')).toBeVisible();
  expect(container.querySelector('.di3-kpi-indicator.is-pursued')).toBeInTheDocument();
  expect(container.querySelector('.di3-kpi-indicator.is-not-pursued')).toBeInTheDocument();
  expect(container.querySelector('.di3-kpi-indicator.is-open')).toBeInTheDocument();
  expect(container.querySelector('.di3-kpi-indicator.is-archived')).toBeInTheDocument();
  expect(screen.getByText(/Choose a vendor · Vendor selection/)).toBeVisible();
  expect(screen.getAllByText('Vendor A').length).toBeGreaterThan(0);
});

it('shows no organization scope control for a solo organization', async () => {
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await screen.findByText('Your decision work');
  expect(screen.queryByRole('button', { name: 'Organization' })).not.toBeInTheDocument();
});

it('shows and uses the organization scope control only when the server permits it', async () => {
  global.fetch
    .mockResolvedValueOnce(response({ ...BASE, scope: 'organization', can_view_organization: true, show_scope_control: true }))
    .mockResolvedValue(response(BASE));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await userEvent.click(await screen.findByRole('button', { name: 'My activity' }));
  await waitFor(() => expect(global.fetch).toHaveBeenLastCalledWith(expect.stringContaining('scope=mine'), expect.any(Object)));
});

it('sends KPI, select, and search filters to the server and renders removable chips', async () => {
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await userEvent.click(await screen.findByRole('button', { name: /^1\s*Pursued/ }));
  await waitFor(() => expect(global.fetch).toHaveBeenLastCalledWith(expect.stringContaining('state=pursued'), expect.any(Object)));
  expect(screen.getByRole('button', { name: 'Remove filter Pursued' })).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText('Kind of decision'), 'Vendor selection');
  await waitFor(() => expect(global.fetch).toHaveBeenLastCalledWith(expect.stringContaining('kind=Vendor+selection'), expect.any(Object)));
  fireEvent.change(screen.getByLabelText('Search options and decisions'), { target: { value: 'Vendor A' } });
  await waitFor(() => expect(global.fetch).toHaveBeenLastCalledWith(expect.stringContaining('search=Vendor+A'), expect.any(Object)));
  await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(screen.getByLabelText('Search options and decisions')).toHaveValue('');
});

it('opens a register drill-down and navigates back to the stored project', async () => {
  const navigate = jest.fn();
  const { container } = render(<DecisionIntelligenceOverview navigate={navigate} />);
  await screen.findByText('Updated live · last refresh just now');
  const row = container.querySelector('.di3-row');
  await userEvent.click(row);
  expect(screen.getByText(/Use Vendor A/)).toBeVisible();
  expect(screen.getByText(/Security approval: failed/)).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Open project' }));
  expect(navigate).toHaveBeenCalledWith('/new?session_id=thread-1');
});

it('renders intended placeholders and unavailable reasons without sample data', async () => {
  const empty = {
    ...BASE, summary: [],
    activity: { ...BASE.activity, total_scored: metric(0), pursued: metric(0), not_pursued: metric(0), open: metric(0), archived: metric(0), needs_attention: [], plans: [], flow: [], by_kind: [], average_time_to_plan_hours: metric(null, { unavailable_reason: 'no_plans' }) },
    effectiveness: { ...BASE.effectiveness, acting_on: [], recurring_gaps: [], gap_follow_through: {}, outcomes: {}, evidence_at_commitment: metric(null, { unavailable_reason: 'insufficient_months', points: [] }) },
    register: { ...BASE.register, rows: [], total: 0 }, facets: { ...BASE.facets, kinds: [] },
  };
  global.fetch.mockResolvedValue(response(empty));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await screen.findByText('Updated live · last refresh just now');
  expect(screen.getAllByText('No scored options match these filters.').length).toBeGreaterThan(0);
  expect(screen.getByText(/Once you build a plan/)).toBeVisible();
  expect(screen.getByText(/Options scored and options decided each week/)).toBeVisible();
});

it('refreshes after 60 seconds while preserving filters and the expanded row', async () => {
  jest.useFakeTimers();
  const { container } = render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await screen.findByText('Updated live · last refresh just now');
  const initialCalls = global.fetch.mock.calls.length;
  fireEvent.change(screen.getByLabelText('Search options and decisions'), { target: { value: 'Vendor' } });
  await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(initialCalls + 1));
  fireEvent.click(container.querySelector('.di3-row'));
  await act(async () => { jest.advanceTimersByTime(60000); await Promise.resolve(); });
  expect(global.fetch).toHaveBeenCalledTimes(initialCalls + 2);
  expect(screen.getByLabelText('Search options and decisions')).toHaveValue('Vendor');
  expect(container.querySelector('.di3-row')).toHaveAttribute('aria-expanded', 'true');
});

it('does not claim a background refresh succeeded when it failed', async () => {
  global.fetch
    .mockResolvedValueOnce(response({ ...BASE, scope: 'organization' }))
    .mockRejectedValueOnce(new Error('network unavailable'));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  await screen.findByText('Updated live · last refresh just now');
  fireEvent.focus(window);
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load Insights.');
  expect(screen.queryByText('Updated live · last refresh just now')).not.toBeInTheDocument();
});


it('composes trigger labels from stored facts and shows condition and recommendation markers', async () => {
  const row = {
    ...ROW,
    conditions: [{ signal_id: 's1', content: 'Bonding secured', status: 'open', due_by: '2026-12-01' }],
    against_recommendation: { override_of: 'decline', jaspen_recommendation: 'No-Bid', failed_check_labels: [] },
    triggers: [{ kind: 'condition_past_due', evidence: { signal_id: 's1', condition: 'Bonding secured', due_by: '2026-12-01' }, next_step_ref: { type: 'signal', id: 's1' }, available: true }],
  };
  global.fetch.mockResolvedValue(response({ ...BASE, activity: { ...BASE.activity, needs_attention: [row] }, register: { ...BASE.register, rows: [row] } }));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  expect(await screen.findByText(/Condition past due: The condition “Bonding secured” was due Dec 1, 2026 and is still open\./)).toBeVisible();
  expect(screen.getByText('Conditional · 1 open')).toBeVisible();
  expect(screen.getByText('Against Jaspen’s No-Bid')).toBeVisible();
  await userEvent.click(screen.getByText('Conditional · 1 open').closest('tr'));
  expect(screen.getByRole('heading', { name: 'Conditions and recommendation' })).toBeVisible();
  expect(screen.getByText(/Jaspen recommended No-Bid; the decision to pursue is yours/)).toBeVisible();
});

it('renders outcome stages as numbers and the latest lesson', async () => {
  const outcomes = { pursued: 2, success_measure_captured: 1, implementation_complete: 1, awaiting_measurement: 1, measured: 1,
    outcomes_recorded: 2, measured_by_status: { achieved: 1 }, met_expectation: 1, lessons: 1,
    latest_lesson: { option_id: ROW.id, option_name: 'Vendor A', lesson: 'Start security review earlier', recorded_at: '2026-10-09' } };
  global.fetch.mockResolvedValue(response({ ...BASE, effectiveness: { ...BASE.effectiveness, outcomes } }));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  expect(await screen.findByText('Awaiting measurement')).toBeVisible();
  expect(screen.getByText('Outcomes recorded')).toBeVisible();
  expect(screen.getByText(/Latest lesson \(Vendor A\): Start security review earlier/)).toBeVisible();
  expect(document.body.textContent).not.toMatch(/NaN/);
});

it('ranks recurring gap and improvement findings with deterministic wording', async () => {
  const summary = [
    { kind: 'pattern', pattern: 'recurring_gap', gap_key: 'security', label: 'Security', decision_kind: 'Vendor selection', decisions_affected: 2, decisions_total: 3 },
    { kind: 'improvement', metric: 'evidence_at_commitment', from_month: '2026-08', from_pct: 40, to_month: '2026-10', to_pct: 60 },
  ];
  global.fetch.mockResolvedValue(response({ ...BASE, summary }));
  render(<DecisionIntelligenceOverview navigate={jest.fn()} />);
  expect(await screen.findByText(/was a gap in 2 of 3 Vendor selection decisions/)).toBeVisible();
  expect(screen.getByText(/Evidence at commitment moved from/)).toBeVisible();
});
