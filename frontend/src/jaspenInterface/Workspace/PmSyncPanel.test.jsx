import React, { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import PmSyncPanel from './PmSyncPanel';
import { Jaspen } from './JaspenClient';

jest.mock('./JaspenClient', () => ({ Jaspen: {
  listPmSyncBindings: jest.fn(), listJiraProjects: jest.fn(), previewPmSync: jest.fn(),
  createPmSyncBinding: jest.fn(), syncPmBinding: jest.fn(), updatePmSyncBinding: jest.fn(),
  getPmSyncBinding: jest.fn(), testJiraConnection: jest.fn(), connectJira: jest.fn(), createJiraProject: jest.fn(),
} }));

beforeEach(() => {
  jest.clearAllMocks();
  Jaspen.listPmSyncBindings.mockResolvedValue({ bindings: [] });
  Jaspen.listJiraProjects.mockResolvedValue({
    projects: [{ key: 'JST', name: 'Jaspen Test' }],
    connection: { base_url:'https://example.atlassian.net', email:'user@example.com', has_api_token:true },
  });
  Jaspen.previewPmSync.mockResolvedValue({ preview: {
    epics: 1, issues: 4, dependencies: 3, unmapped_owners: 1, tasks_without_start_date: 2,
    structure: "Creates epic 'Denver Water Pump Station — RFP Pursuit and Submission WBS' with 4 tasks, 3 'Blocks' links.",
  } });
  Jaspen.syncPmBinding.mockResolvedValue({ result: { binding: { id:'bind-1', status:'active', mode:'two_way' } }, logs:[] });
  Jaspen.updatePmSyncBinding.mockResolvedValue({ binding: { id:'bind-1', status:'active', mode:'two_way' } });
  Jaspen.getPmSyncBinding.mockResolvedValue({ logs:[] });
});

it('defaults to two-way and most-recent-wins after an explicit Jira destination', async () => {
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /Sync execution plan/i }));
  expect(await screen.findByRole('dialog', { name: /set up execution plan sync/i })).toBeInTheDocument();
  expect(Jaspen.listJiraProjects).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: /Smartsheet/i })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: /Jira/i }));
  expect(await screen.findByText(/Creates epic 'Denver Water Pump Station — RFP Pursuit and Submission WBS' with 4 tasks, 3 'Blocks' links/)).toBeInTheDocument();
  expect(screen.getByText(/2 tasks have no start date and won't appear on Jira's timeline/)).toBeInTheDocument();
  const send = screen.getByRole('button', { name: /Link project/i });
  expect(send).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Destination project'), { target: { value: 'JST' } });
  expect(screen.getByRole('checkbox', { name: /Two-way sync/i })).toBeChecked();
  expect(send).toBeEnabled();
});

it('sends the explicit choices and shows durable synced controls', async () => {
  Jaspen.createPmSyncBinding.mockResolvedValue({
    binding: { id: 'bind-1', status: 'active', external_container_url: 'https://example.atlassian.net/browse/JST' },
    result: { success: true, errors: [] },
  });
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /Sync execution plan/i }));
  fireEvent.click(screen.getByRole('button', { name: /Jira/i }));
  await screen.findByRole('option', { name: /JST · Jaspen Test/ });
  fireEvent.change(screen.getByLabelText('Destination project'), { target: { value: 'JST' } });
  expect(screen.getByRole('checkbox', { name: /Two-way sync/i })).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: /Jaspen wins/i }));
  fireEvent.click(screen.getByRole('button', { name: /Link project/i }));
  await waitFor(() => expect(Jaspen.createPmSyncBinding).toHaveBeenCalledWith(expect.objectContaining({
    thread_id: 'thread-1', plan_key: 'score-1', external_container_id: 'JST',
    mode: 'two_way', conflict_policy: 'prefer_jaspen',
  })));
  expect(await screen.findByText(/Synced with Jira/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Sync now/i })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /View in Jira/i })).toHaveAttribute('href', 'https://example.atlassian.net/browse/JST');
});

it('tests credentials before saving them', async () => {
  Jaspen.listJiraProjects.mockRejectedValueOnce(new Error('Jira is not connected'));
  Jaspen.testJiraConnection.mockResolvedValue({ ok: true });
  Jaspen.connectJira.mockResolvedValue({ success: true });
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /Sync execution plan/i }));
  expect(Jaspen.listJiraProjects).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Jira/i }));
  await screen.findByLabelText('Jira site URL');
  expect(screen.getByRole('status')).toHaveTextContent(/Connect Jira to choose or create a project/);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Jira site URL')).toHaveStyle({ borderRadius: '8px', padding: '10px 11px' });
  fireEvent.change(screen.getByLabelText('Jira site URL'), { target:{ value:'https://example.atlassian.net' } });
  fireEvent.change(screen.getByLabelText('Jira email'), { target:{ value:'user@example.com' } });
  fireEvent.change(screen.getByLabelText('Jira API token'), { target:{ value:'secret' } });
  fireEvent.click(screen.getByRole('button', { name:'Test connection' }));
  await waitFor(() => expect(Jaspen.testJiraConnection).toHaveBeenCalled());
  expect(Jaspen.connectJira).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole('button', { name:'Save and continue' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name:'Save and continue' }));
  await waitFor(() => expect(Jaspen.connectJira).toHaveBeenCalled());
});

it('shows the saved account and lets the user replace it', async () => {
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /Sync execution plan/i }));
  fireEvent.click(screen.getByRole('button', { name: /Jira Connect/i }));
  expect(await screen.findByText(/Using Jira: https:\/\/example.atlassian.net · user@example.com/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Use a different account/i }));
  expect(screen.getByLabelText('Jira site URL')).toHaveValue('https://example.atlassian.net');
  expect(screen.getByLabelText('Jira email')).toHaveValue('user@example.com');
  expect(screen.getByLabelText('Jira API token')).toHaveValue('');
});

it('turns a revoked saved token into an explained prefilled reconnect form', async () => {
  const error = Object.assign(new Error('raw provider failure'), {
    status: 401,
    data: {
      code: 'JIRA_RECONNECT_REQUIRED',
      error: 'Your saved Jira connection no longer works. Enter a new API token to continue.',
      connection: { base_url:'https://old.atlassian.net', email:'old@example.com', has_api_token:true },
    },
  });
  Jaspen.listJiraProjects.mockRejectedValueOnce(error);
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /Sync execution plan/i }));
  fireEvent.click(screen.getByRole('button', { name: /Jira Connect/i }));
  expect(await screen.findByRole('status')).toHaveTextContent('Your saved Jira connection no longer works');
  expect(screen.getByLabelText('Jira site URL')).toHaveValue('https://old.atlassian.net');
  expect(screen.getByLabelText('Jira email')).toHaveValue('old@example.com');
  expect(screen.queryByText(/raw provider failure/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Destination project')).not.toBeInTheDocument();
});

it('separates existing and new projects, suggests a key, and blocks token-shaped keys', async () => {
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /Sync execution plan/i }));
  fireEvent.click(screen.getByRole('button', { name: /Jira Connect/i }));
  await screen.findByRole('button', { name: /Create new/i });
  fireEvent.click(screen.getByRole('button', { name: /Create new/i }));
  expect(screen.getByRole('checkbox', { name: /Group tasks under epics/i })).not.toBeChecked();
  expect(screen.queryByLabelText('Destination project')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Project name'), { target:{ value:'Jaspen Production Test' } });
  expect(screen.getByLabelText('Project key (e.g. JPT)')).toHaveValue('JPT');
  expect(screen.getByText(/Short code used in issue IDs, e.g. JPT-12/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Project key (e.g. JPT)'), { target:{ value:'ATATT-secret-token' } });
  expect(screen.getByText(/That looks like an API token/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name:'Create project' })).toBeDisabled();
  expect(Jaspen.createJiraProject).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Choose existing/i }));
  expect(screen.getByRole('checkbox', { name: /Group tasks under epics/i })).toBeChecked();
});

it('shows reconnect Jira and persists the repaired binding after replacing credentials', async () => {
  Jaspen.listPmSyncBindings.mockResolvedValue({ bindings: [{
    id:'bind-1', status:'reconnect_required', mode:'two_way',
  }] });
  const error = Object.assign(new Error('HTTP 401'), {
    status:401,
    data:{ code:'JIRA_RECONNECT_REQUIRED', connection:{
      base_url:'https://old.atlassian.net', email:'old@example.com', has_api_token:true,
    } },
  });
  Jaspen.listJiraProjects.mockRejectedValueOnce(error);
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  const reconnect = await screen.findByRole('button', { name:'Reconnect Jira' });
  fireEvent.click(reconnect);
  expect(await screen.findByLabelText('Jira site URL')).toHaveValue('https://old.atlassian.net');
  expect(screen.getByLabelText('Jira email')).toHaveValue('old@example.com');
  expect(Jaspen.syncPmBinding).not.toHaveBeenCalled();
  Jaspen.testJiraConnection.mockResolvedValue({ ok:true });
  Jaspen.connectJira.mockResolvedValue({
    success:true, base_url:'https://old.atlassian.net', email:'old@example.com', has_api_token:true,
  });
  fireEvent.change(screen.getByLabelText('Jira API token'), { target:{ value:'replacement-token' } });
  fireEvent.click(screen.getByRole('button', { name:'Test connection' }));
  await waitFor(() => expect(screen.getByRole('button', { name:'Save and continue' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name:'Save and continue' }));
  await waitFor(() => expect(Jaspen.connectJira).toHaveBeenCalledWith(expect.objectContaining({
    jira_api_token:'replacement-token',
  })));
  await waitFor(() => expect(Jaspen.updatePmSyncBinding).toHaveBeenCalledWith('bind-1', { status:'active' }));
});

it('closing tool selection leaves sync off and never checks a connector', async () => {
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  const toggle = screen.getByRole('checkbox', { name: /Sync execution plan/i });
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);
  expect(await screen.findByText(/Choose where this plan should stay in sync/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(toggle).not.toBeChecked();
  expect(Jaspen.listJiraProjects).not.toHaveBeenCalled();
  expect(Jaspen.previewPmSync).not.toHaveBeenCalled();
});

it('refreshes the rendered plan after sync-on-open pulls Jira changes', async () => {
  Jaspen.listPmSyncBindings.mockResolvedValue({ bindings: [{
    id: 'bind-1', status: 'active', mode: 'two_way',
  }] });
  Jaspen.syncPmBinding.mockResolvedValue({
    result: {
      binding: { id: 'bind-1', status: 'active', mode: 'two_way' },
      pulled: 2, deleted: 0,
    },
    logs: [],
  });

  function Harness() {
    const [task, setTask] = useState({ status: 'To Do', due_date: '2026-11-20' });
    return <>
      <div>{task.status} · {task.due_date}</div>
      <PmSyncPanel
        threadId="thread-1"
        planKey="score-1"
        taskCount={1}
        onPlanUpdated={() => setTask({ status: 'Done', due_date: '2026-11-25' })}
      />
    </>;
  }

  render(<Harness />);
  expect(screen.getByText(/To Do · 2026-11-20/)).toBeInTheDocument();
  expect(await screen.findByText(/Done · 2026-11-25/)).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Updated from Jira: 2 changes');
});

it('shows the Jira default-assignee note once in sync history', async () => {
  Jaspen.listPmSyncBindings.mockResolvedValue({ bindings: [{
    id: 'bind-1', status: 'active', mode: 'two_way',
  }] });
  Jaspen.syncPmBinding.mockResolvedValue({
    result: { binding: { id: 'bind-1', status: 'active', mode: 'two_way' }, pulled: 0, deleted: 0 },
    logs: [{ id:'log-1', status:'success', items_synced:9, created_at:'2026-10-14T12:00:00Z', sync_metadata:{
      notes:['Jira assigns new issues to Lydia Bailey by default; Jaspen kept its own owners'],
    } }],
  });
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={9} />);
  fireEvent.click(await screen.findByText('Sync history'));
  expect(screen.getByText('Jira assigns new issues to Lydia Bailey by default; Jaspen kept its own owners')).toBeInTheDocument();
});

it('shows the personal sync owner directly under sync status', async () => {
  Jaspen.listPmSyncBindings.mockResolvedValue({ bindings: [{
    id:'bind-owner', status:'active', mode:'two_way',
    sync_owner:{ name:'Lydia Bailey', email:'lydia@example.com', available:true },
  }] });
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  expect(await screen.findByText('Synced by Lydia Bailey with their Jira account')).toBeInTheDocument();
});

it('shows the approved authorization and departed-owner warnings', async () => {
  Jaspen.listPmSyncBindings.mockResolvedValueOnce({ bindings: [{
    id:'bind-expired', status:'reconnect_required', mode:'two_way',
    sync_warning_code:'authorization_expired',
    sync_owner:{ name:'Avery', available:true },
  }] });
  const { unmount } = render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Jira needs to be reconnected by Avery before this plan can sync.'
  );
  unmount();

  Jaspen.listPmSyncBindings.mockResolvedValueOnce({ bindings: [{
    id:'bind-left', status:'paused', mode:'two_way',
    pause_reason:'sync_owner_left_organization',
    sync_owner:{ name:'Former teammate', available:true },
  }] });
  render(<PmSyncPanel threadId="thread-2" planKey="score-2" taskCount={3} />);
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Sync is paused because the person who connected Jira no longer has access.'
  );
});
