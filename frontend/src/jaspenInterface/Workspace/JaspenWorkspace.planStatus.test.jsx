import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { Jaspen } from './JaspenClient';
import JaspenWorkspace from './JaspenWorkspace';

const mockGenerateExecutionPlan = jest.fn();
const mockOnePagerReport = jest.fn(() => null);
let mockExecutionPlanFailure = null;

jest.mock('react-router-dom', () => ({
  Link: ({ children }) => <span>{children}</span>,
  useNavigate: () => jest.fn(),
  useParams: () => ({ threadId: 'thread-1', scorecardId: 'scorecard-1' }),
  useSearchParams: () => [new URLSearchParams()],
}));

jest.mock('react-grid-layout', () => {
  const Grid = ({ children }) => <div>{children}</div>;
  return { __esModule: true, default: Grid, WidthProvider: () => Grid };
});

jest.mock('react-markdown', () => ({ children }) => <>{children}</>);
jest.mock('remark-gfm', () => () => null);

jest.mock('./JaspenClient', () => ({
  Jaspen: {
    fetchBundle: jest.fn(),
    getScorecardForWorkspace: jest.fn(),
    getWorkspaceChat: jest.fn(),
    getAcceptedExposures: jest.fn(),
    getThreadWbs: jest.fn(),
    saveWorkspaceChat: jest.fn(),
    patchScorecardOverrides: jest.fn(),
    acceptExposure: jest.fn(),
    chat: jest.fn(),
    downloadWbsXlsx: jest.fn(),
  },
}));

jest.mock('./useExecutionPlanBuild', () => ({
  ExecutionPlanBuildFailure: ({ message, onRetry, busy }) => message ? (
    <div role="alert">
      <span>{message}</span>
      <button type="button" onClick={onRetry} disabled={busy}>
        {busy ? 'Building plan…' : 'Retry'}
      </button>
    </div>
  ) : null,
  useExecutionPlanBuild: () => ({
    generateExecutionPlan: mockGenerateExecutionPlan,
    executionPlanDecisionDialog: null,
    executionPlanFailure: mockExecutionPlanFailure,
  }),
}));

jest.mock('./TradeoffView', () => () => null);
jest.mock('./DecisionConfidenceCard', () => () => null);
jest.mock('./DecisionImpactReport', () => () => null);
jest.mock('./RiskRegister', () => () => null);
jest.mock('./JaspenExecutionCanvas', () => () => null);
jest.mock('./scorecardPdf', () => ({ downloadRenderedWorkspacePdf: jest.fn() }));
jest.mock('./EmailResultsButton', () => {
  const MockReact = require('react');
  return MockReact.forwardRef(() => null);
});
jest.mock('../Sharing/ShareButton', () => () => null);
jest.mock('../Sharing/OnePagerReport', () => (props) => mockOnePagerReport(props));
jest.mock('./PmSyncPanel', () => () => null);

const scorecard = {
  id: 'scorecard-1',
  name: 'Launch Alpha',
  project_name: 'Launch Alpha',
  dimensions: [],
  top_risks: [],
  evidence_profile: [],
};

function storedChat() {
  return JSON.parse(localStorage.getItem('jw-chat-thread-1-scorecard-1'));
}

async function requestPlan() {
  const composer = await screen.findByPlaceholderText('Describe a change…');
  fireEvent.change(composer, {
    target: { value: 'Build an execution plan' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
}

beforeEach(() => {
  localStorage.clear();
  mockExecutionPlanFailure = null;
  jest.clearAllMocks();
  Jaspen.fetchBundle.mockResolvedValue({
    thread: { id: 'thread-1', name: 'Launch Alpha' },
    current_scorecard: scorecard,
    scorecard_snapshots: [scorecard],
  });
  Jaspen.getScorecardForWorkspace.mockResolvedValue({ scorecard, display_overrides: {} });
  Jaspen.getWorkspaceChat.mockResolvedValue({ messages: [] });
  Jaspen.getAcceptedExposures.mockResolvedValue({ accepted_exposures: [] });
  Jaspen.getThreadWbs.mockResolvedValue({ project_wbs: null });
  Jaspen.saveWorkspaceChat.mockResolvedValue({});
  Jaspen.patchScorecardOverrides.mockResolvedValue({});
});

it('shows the failure band with Retry without adding a sidebar chat message', async () => {
  mockExecutionPlanFailure = "Jaspen couldn't finish building this plan — try again. Your existing plan was not changed.";
  mockGenerateExecutionPlan.mockRejectedValue(new Error('provider secret detail'));
  render(<JaspenWorkspace />);

  await requestPlan();

  expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.queryByText(/provider secret detail/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/couldn't build the execution plan/i)).not.toBeInTheDocument();
  expect(storedChat()).toEqual([{ role: 'user', text: 'Build an execution plan' }]);
});

it('opens the plan-exists dialog without adding a sidebar chat message', async () => {
  mockGenerateExecutionPlan.mockResolvedValue({
    plan_exists: true,
    scorecard_id: 'scorecard-1',
    scorecard_name: 'Launch Alpha',
    task_count: 12,
  });
  render(<JaspenWorkspace />);

  await requestPlan();

  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  expect(screen.getByText('Execution plan already exists')).toBeInTheDocument();
  expect(storedChat()).toEqual([{ role: 'user', text: 'Build an execution plan' }]);
});

it('adds only the data-backed plan card after a successful sidebar build', async () => {
  mockGenerateExecutionPlan.mockResolvedValue({
    project_wbs: {
      scorecard_id: 'scorecard-1',
      tasks: [{ title: 'Confirm launch owner' }, { title: 'Publish launch brief' }],
    },
  });
  render(<JaspenWorkspace />);

  await requestPlan();

  expect(await screen.findByText('Execution plan · 2 tasks')).toBeInTheDocument();
  expect(screen.queryByText(/here's a draft execution plan/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/I generated an execution plan/i)).not.toBeInTheDocument();
  await waitFor(() => expect(storedChat()).toEqual([
    { role: 'user', text: 'Build an execution plan' },
    expect.objectContaining({ role: 'ai', text: '', execPlan: expect.any(Object) }),
  ]));
});

it('passes saved data-source context into the Workspace report', async () => {
  Jaspen.fetchBundle.mockResolvedValue({
    thread: { id: 'thread-1', name: 'Launch Alpha' },
    current_scorecard: scorecard,
    scorecard_snapshots: [scorecard],
    report_data_sources: ['jira'],
  });
  render(<JaspenWorkspace />);

  await waitFor(() => expect(mockOnePagerReport).toHaveBeenCalled());
  const reportProps = mockOnePagerReport.mock.calls.find(([props]) => props.artifactType === 'scorecard')?.[0];
  expect(reportProps.snapshot.context.data_sources).toEqual(['jira']);
});

it('shows the failure band on the trade-off view as well as on a scorecard', () => {
  const source = require('fs').readFileSync(require('path').join(__dirname, 'JaspenWorkspace.jsx'), 'utf8');
  expect(source).toContain('{(isScorecard || isTradeoff) && failedPlanRequest && (');
});
