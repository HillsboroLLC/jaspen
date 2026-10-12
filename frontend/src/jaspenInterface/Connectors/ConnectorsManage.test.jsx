import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ConnectorsManage from './ConnectorsManage';
import { authFetch } from '../../shared/auth/http';

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { subscription_plan: 'free' } }),
}));

jest.mock('../../shared/auth/http', () => ({
  authFetch: jest.fn(),
  buildAuthHeaders: jest.fn(() => ({})),
}));

jest.mock('../shared/AppMenu', () => () => null);
jest.mock('../Workspace/JaspenAiDrawer', () => () => null);

const response = (body) => ({
  ok: true,
  status: 200,
  json: jest.fn().mockResolvedValue(body),
});

beforeEach(() => {
  jest.clearAllMocks();
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) {
      return Promise.resolve(response({
        connectors: [{
          id: 'jira_sync',
          label: 'Jira',
          implementation_status: 'implemented',
          lifecycle_status: 'disconnected',
          connected: false,
          available_sync_modes: ['two_way'],
          available_conflict_policies: ['latest_wins'],
        }],
      }));
    }
    if (String(url).includes('/api/v1/ai-agent/threads')) {
      return Promise.resolve(response({
        success: true,
        sessions: [{ session_id: 'thread-1', name: 'Test decision' }],
      }));
    }
    if (String(url).includes('/audit')) {
      return Promise.resolve(response({ events: [] }));
    }
    throw new Error(`Unexpected request: ${url}`);
  });
});

it('loads connector and thread data once when initial selections are established', async () => {
  render(
    <MemoryRouter initialEntries={['/connectors-manage']}>
      <ConnectorsManage />
    </MemoryRouter>
  );

  expect(await screen.findByRole('heading', { name: 'Connectors' })).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByLabelText('Loading connectors')).not.toBeInTheDocument());
  await waitFor(() => expect(screen.getAllByText('Jira').length).toBeGreaterThan(0));

  const requested = (fragment) => authFetch.mock.calls.filter(([url]) => String(url).includes(fragment));
  expect(requested('/api/v1/connectors/status')).toHaveLength(1);
  expect(requested('/api/v1/ai-agent/threads')).toHaveLength(1);
});
