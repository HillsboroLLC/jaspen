import React from 'react';
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
  Jaspen.listJiraProjects.mockResolvedValue({ projects: [{ key: 'JST', name: 'Jaspen Test' }] });
  Jaspen.previewPmSync.mockResolvedValue({ preview: { epics: 2, issues: 3, dependencies: 1, unmapped_owners: 1 } });
  Jaspen.syncPmBinding.mockResolvedValue({ result: { binding: { id:'bind-1', status:'active', mode:'two_way' } }, logs:[] });
  Jaspen.getPmSyncBinding.mockResolvedValue({ logs:[] });
});

it('defaults to two-way and most-recent-wins after an explicit Jira destination', async () => {
  render(<PmSyncPanel threadId="thread-1" planKey="score-1" taskCount={3} />);
  fireEvent.click(screen.getByRole('checkbox', { name: /Sync execution plan/i }));
  expect(await screen.findByRole('dialog', { name: /set up execution plan sync/i })).toBeInTheDocument();
  expect(Jaspen.listJiraProjects).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: /Smartsheet/i })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: /Jira/i }));
  expect(await screen.findByText(/Will create 2 epics, 3 issues, and 1 “Blocks” link/)).toBeInTheDocument();
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
