import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ConnectorsManage, { fitCredentialHelpToViewport } from './ConnectorsManage';
import { authFetch } from '../../shared/auth/http';

let mockUser = { subscription_plan: 'free' };
jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
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
  mockUser = { subscription_plan: 'free' };
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
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/health')) return Promise.resolve(response({ live_status: { status: 'healthy', message: 'Connection successful' } }));
    throw new Error(`Unexpected request: ${url}`);
  });
});

it('keeps credential help inside narrow and wide viewports and flips left when needed', () => {
  const narrow = fitCredentialHelpToViewport({ left: 280, right: 300 }, 320);
  expect(narrow).toEqual({ left: 16, width: 288, placement: 'left' });
  expect(narrow.left + narrow.width).toBeLessThanOrEqual(320 - 16);

  const wideRightEdge = fitCredentialHelpToViewport({ left: 1120, right: 1140 }, 1200);
  expect(wideRightEdge.placement).toBe('left');
  expect(wideRightEdge.left + wideRightEdge.width).toBeLessThanOrEqual(1200 - 16);

  const wideWithRoom = fitCredentialHelpToViewport({ left: 180, right: 200 }, 1200);
  expect(wideWithRoom).toEqual({ left: 180, width: 360, placement: 'right' });
});

it('shows the full connector catalog for the canonical Business plan key', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  const labels = [
    ['jira_sync', 'Jira'],
    ['smartsheet_sync', 'Smartsheet'],
    ['salesforce_insights', 'Salesforce'],
    ['snowflake_insights', 'Snowflake'],
    ['oracle_fusion_insights', 'Oracle Fusion'],
    ['servicenow_insights', 'ServiceNow'],
    ['netsuite_insights', 'NetSuite'],
  ];
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) {
      return Promise.resolve(response({ connectors: labels.map(([id, label]) => ({
        id, label, implementation_status:'implemented', lifecycle_status:'disconnected', connected:false,
      })) }));
    }
    if (String(url).includes('/api/v1/ai-agent/threads')) {
      return Promise.resolve(response({ success:true, sessions:[] }));
    }
    if (String(url).includes('/audit')) return Promise.resolve(response({ events:[] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/health')) return Promise.resolve(response({ live_status: { status: 'healthy', message: 'Connection successful' } }));
    throw new Error(`Unexpected request: ${url}`);
  });

  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);

  expect(await screen.findByText('7 available on your business plan')).toBeInTheDocument();
  ['Jira', 'Smartsheet', 'Salesforce', 'Snowflake'].forEach((label) => {
    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  });
  fireEvent.click(screen.getByRole('button', { name:/Enterprise Sources/i }));
  ['Oracle Fusion', 'ServiceNow', 'NetSuite'].forEach((label) => {
    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
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

it('treats Jira as Data & Insights without requiring a default project', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) {
      return Promise.resolve(response({ connectors: [{
        id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'connected', connected: true,
        available_sync_modes: ['import', 'push', 'two_way'], available_conflict_policies: ['latest_wins'],
        jira: { base_url: 'https://acme.atlassian.net', email: 'owner@acme.test', has_api_token: true, data_enabled: true, data_project_scope: 'all' },
      }] }));
    }
    if (String(url).includes('/api/v1/connectors/jira/projects')) {
      return Promise.resolve(response({ success: true, projects: [{ key: 'ABC', name: 'Alpha' }] }));
    }
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/health')) return Promise.resolve(response({ live_status: { status: 'healthy', message: 'Connection successful' } }));
    throw new Error(`Unexpected request: ${url}`);
  });

  const { container } = render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);

  expect(await screen.findByText('Execution Sync')).toBeInTheDocument();
  expect(screen.getAllByText('Data & Insights').length).toBeGreaterThan(0);
  expect(Array.from(container.querySelectorAll('.connector-list-item-label')).filter((node) => node.textContent === 'Jira')).toHaveLength(2);
  expect(await screen.findByText('Connected as owner@acme.test on acme.atlassian.net')).toBeInTheDocument();
  expect(screen.getByLabelText(/^Use Jira data in analysis/)).toBeChecked();
  expect(screen.getByText(/summary metrics from your Jira projects/)).toHaveTextContent('never issue content or names');
  expect(screen.getByLabelText(/Jira site URL/i)).toHaveValue('https://acme.atlassian.net');
  expect(screen.getByRole('button', { name: /Test connection/i })).toBeInTheDocument();
  expect(screen.queryByLabelText(/Project Key/i)).not.toBeInTheDocument();
  ['Sync Mode', 'Conflict Policy', 'External Workspace', 'Sync Thread', 'Auto-sync', 'Issue Type', 'Field Mapping JSON', 'Automatic', 'Manual', 'Run Setup Check', 'Revert Draft'].forEach((label) => {
    expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
  });
  await waitFor(() => expect(authFetch.mock.calls.some(([url]) => String(url).includes('/api/v1/connectors/jira/projects'))).toBe(true));
  fireEvent.click(screen.getByLabelText('Selected projects'));
  expect(await screen.findByRole('option', { name: 'ABC · Alpha' })).toBeInTheDocument();
});

it('keeps the last Jira portfolio visible when refresh fails', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  const snapshot = {
    fetched_at: '2026-10-12T16:00:00Z',
    projects: [{
      project_key: 'ABC', project_name: 'Alpha', completion_percent: 50, overdue_count: 1,
      status_counts: { to_do: 1, in_progress: 0, done: 1 },
      throughput: { trend: 'flat' }, cycle_time: { median_days: null, sample_size: 0 },
      health: { status: 'healthy' }, jira_url: 'https://acme.atlassian.net/browse/ABC', jira_links: {},
    }],
    portfolio: {
      completion_percent: 50, overdue_count: 1, status_counts: { to_do: 1, in_progress: 0, done: 1 },
      throughput: { trend: 'flat' }, cycle_time: { median_days: null, sample_size: 0 }, health: { status: 'healthy' },
    },
  };
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'connected', connected: true,
      jira: { base_url: 'https://acme.atlassian.net', email: 'owner@acme.test', has_api_token: true, data_enabled: true, data_project_scope: 'all', portfolio_snapshot: snapshot },
    }] }));
    if (String(url).includes('/api/v1/connectors/jira/projects')) return Promise.resolve(response({ success: true, projects: [] }));
    if (String(url).includes('/api/v1/connectors/jira/context/summary')) return Promise.resolve({
      ok: false, status: 400, json: jest.fn().mockResolvedValue({
        error: "Jaspen couldn't read Jira data — we've logged the details.", category: 'request_format', reconnect_required: false,
      }),
    });
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/health')) return Promise.resolve(response({ live_status: { status: 'healthy', message: 'Connection successful' } }));
    throw new Error(`Unexpected request: ${url}`);
  });

  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);
  expect(await screen.findByText('ABC · Alpha')).toBeInTheDocument();
  expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh portfolio evidence' }));
  expect(await screen.findByRole('alert')).toHaveTextContent("Jaspen couldn't read Jira data — we've logged the details.");
  expect(screen.getByText('ABC · Alpha')).toBeInTheDocument();
});


it('shows Jira connection fields immediately and tests changed credentials before saving', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  authFetch.mockImplementation((url, options = {}) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'connected', connected: true,
      jira: { base_url: 'https://acme.atlassian.net', email: 'owner@acme.test', has_api_token: true, data_enabled: true, data_project_scope: 'all' },
    }] }));
    if (String(url).includes('/api/v1/connectors/jira/projects')) return Promise.resolve(response({ projects: [] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [] }));
    if (String(url).includes('/health')) return Promise.resolve(response({ live_status: { status: 'healthy' } }));
    if (String(url).includes('/api/v1/pm-sync/jira/test-connection')) return Promise.resolve(response({ success: true, base_url: 'https://acme.atlassian.net' }));
    if (String(url).includes('/api/v1/pm-sync/jira/connect')) return Promise.resolve(response({ success: true }));
    throw new Error(`Unexpected request: ${url} ${options.method || 'GET'}`);
  });

  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);
  expect(await screen.findByText('Connected as owner@acme.test on acme.atlassian.net')).toBeInTheDocument();
  expect(screen.getByLabelText(/Jira site URL/i)).toHaveValue('https://acme.atlassian.net');
  expect(screen.getByLabelText(/^Email/i)).toHaveValue('owner@acme.test');
  expect(screen.getByLabelText(/^API token$/i)).toHaveAttribute('placeholder', 'Token saved · enter a new one only to replace it');
  expect(screen.queryByText('Required to connect')).not.toBeInTheDocument();
  expect(document.querySelectorAll('.connector-required-marker')).toHaveLength(0);
  expect(screen.getByRole('button', { name: /Test connection/i })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Connect|Reconnect/ })).not.toBeInTheDocument();

  const save = screen.getByRole('button', { name: /^Save$/i });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/API token/i), { target: { value: 'new-token' } });
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: /Test connection/i }));
  await waitFor(() => expect(authFetch.mock.calls.some(([url]) => String(url).includes('/api/v1/pm-sync/jira/test-connection'))).toBe(true));
  await waitFor(() => expect(save).toBeEnabled());
  fireEvent.click(save);
  await waitFor(() => expect(authFetch.mock.calls.some(([url]) => String(url).includes('/api/v1/pm-sync/jira/connect'))).toBe(true));
});

it('marks missing credentials as required and exposes Jira credential help to keyboard and touch users', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };

  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);

  expect(await screen.findByText('Jira is not connected')).toBeInTheDocument();
  expect(screen.getAllByText('Required to connect').length).toBeGreaterThanOrEqual(3);
  expect(document.querySelectorAll('.connector-required-marker').length).toBeGreaterThanOrEqual(3);
  expect(screen.getByLabelText(/API token/i)).toHaveAttribute('placeholder', 'Paste your API token');

  const help = screen.getByLabelText('About Jira credentials');
  expect(help.querySelector('svg')).toBeInTheDocument();
  expect(help).not.toHaveTextContent('(i)');
  expect(help).toHaveAttribute('aria-label', 'About Jira credentials');
  expect(help).toHaveAttribute('aria-describedby');
  help.focus();
  expect(help).toHaveFocus();
  fireEvent.click(help);
  const note = await screen.findByRole('note');
  expect(note).toHaveTextContent("Jaspen uses this token to sign in to Jira");
  expect(within(note).getByRole('link', { name: 'Create a Jira API token' })).toHaveAttribute(
    'href',
    'https://id.atlassian.com/manage-profile/security/api-tokens'
  );
  expect(within(note).getByRole('link', { name: 'Create a Jira API token' })).toHaveAttribute('target', '_blank');
});

it('returns connected credentials to the required state when the live connection check fails', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'connected', connected: true,
      jira: { base_url: 'https://acme.atlassian.net', email: 'owner@acme.test', has_api_token: true, data_project_scope: 'all' },
    }] }));
    if (String(url).includes('/api/v1/connectors/jira/projects')) return Promise.resolve(response({ projects: [] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [] }));
    if (String(url).includes('/health')) return Promise.resolve({
      ok: false,
      status: 401,
      json: jest.fn().mockResolvedValue({ error: 'Unauthorized' }),
    });
    throw new Error(`Unexpected request: ${url}`);
  });

  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);

  expect(await screen.findByRole('alert')).toHaveTextContent('The saved connection could not be verified. Reconnect and check the credentials.');
  expect(screen.getAllByText('Required to connect').length).toBeGreaterThanOrEqual(3);
  expect(screen.getByLabelText(/API token/i)).toHaveAttribute('placeholder', 'Token saved · enter a new one only to replace it');
  expect(document.querySelectorAll('.connector-list-item-dot.is-warn')).toHaveLength(2);
  expect(document.querySelectorAll('.connector-list-item-dot.is-on')).toHaveLength(0);
  expect(document.querySelector('.connector-status-dot')).toHaveClass('is-attention');
});

it('shows saved-but-unverified connector rows as amber instead of green', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'degraded', connected: false,
      health: { status: 'failed' },
      jira: { base_url: 'https://acme.atlassian.net', email: 'owner@acme.test', has_api_token: true, data_project_scope: 'all' },
    }] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [] }));
    throw new Error(`Unexpected request: ${url}`);
  });

  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);

  expect(await screen.findByText('Jira is not connected')).toBeInTheDocument();
  expect(document.querySelectorAll('.connector-list-item-dot.is-warn')).toHaveLength(2);
  expect(document.querySelectorAll('.connector-list-item-dot.is-on')).toHaveLength(0);
});

it('renders connector activity newest first with readable names', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'disconnected', connected: false,
      jira: { data_enabled: false, data_project_scope: 'all' },
    }] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [
      { id: 'old', timestamp: '2026-10-12T10:00:00Z', action: 'config_update', status: 'success', message: '' },
      { id: 'new', timestamp: '2026-10-12T12:00:00Z', action: 'context_summary', status: 'success', message: '' },
      { id: 'mid', timestamp: '2026-10-12T11:00:00Z', action: 'pm_sync', status: 'success', message: '' },
    ] }));
    throw new Error(`Unexpected request: ${url}`);
  });

  const { container } = render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);
  expect(await screen.findByRole('heading', { name: 'Activity' })).toBeInTheDocument();
  await waitFor(() => expect(container.querySelectorAll('.connector-activity-list strong')).toHaveLength(3));
  const labels = Array.from(container.querySelectorAll('.connector-activity-list strong')).map((node) => node.textContent);
  expect(labels).toEqual(['Portfolio evidence refreshed', 'Execution plan sync completed', 'Connection or settings saved']);
});

it('shows execution sync ownership and authorization warnings on the connector page', async () => {
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id:'jira_sync', label:'Jira', implementation_status:'implemented',
      lifecycle_status:'connected', connected:true,
      settings:{ jira_base_url:'https://acme.atlassian.net', jira_email:'owner@acme.test', jira_api_token:'__saved__' },
      jira:{ data_project_scope:'all' },
    }] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success:true, sessions:[{ session_id:'thread-1', name:'Road decision' }] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings:[{
      id:'binding-1', thread_id:'thread-1', plan_key:'score-1', connector_id:'jira_sync',
      external_container_id:'JPT', status:'reconnect_required', sync_warning_code:'authorization_expired',
      sync_owner:{ name:'Lydia Bailey', email:'owner@acme.test', available:true },
    }] }));
    if (String(url).includes('/api/v1/connectors/jira/projects')) return Promise.resolve(response({ success:true, projects:[] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events:[] }));
    if (String(url).includes('/health')) return Promise.resolve(response({ live_status:{ status:'healthy', message:'Connection successful' } }));
    throw new Error(`Unexpected request: ${url}`);
  });
  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);
  expect(await screen.findByText('Synced by Lydia Bailey with their Jira account')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Jira needs to be reconnected by Lydia Bailey before this plan can sync.'
  );
});


it('shows connection fields immediately for Jira, Smartsheet, Salesforce, and Snowflake', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  const connectors = [
    { id: 'jira_sync', label: 'Jira', jira: { data_project_scope: 'all' } },
    { id: 'smartsheet_sync', label: 'Smartsheet' },
    { id: 'salesforce_insights', label: 'Salesforce' },
    { id: 'snowflake_insights', label: 'Snowflake' },
  ].map((item) => ({ ...item, implementation_status: 'implemented', lifecycle_status: 'disconnected', connected: false }));
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [] }));
    throw new Error(`Unexpected request: ${url}`);
  });

  const { container } = render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);
  expect(await screen.findByText('4 available on your business plan')).toBeInTheDocument();
  const cases = [
    ['Jira', /Jira site URL/i, 'About Jira credentials', 'id.atlassian.com'],
    ['Smartsheet', /Smartsheet Base URL/i, 'About Smartsheet credentials', 'help.smartsheet.com'],
    ['Salesforce', /Auth Base URL/i, 'About Salesforce credentials', 'help.salesforce.com'],
    ['Snowflake', /Account Identifier/i, 'About Snowflake credentials', 'docs.snowflake.com'],
  ];
  for (const [label, credentialLabel, helpLabel, helpHost] of cases) {
    const button = Array.from(container.querySelectorAll('.connector-list-item')).find((node) => node.textContent.includes(label));
    fireEvent.click(button);
    expect(screen.getByLabelText(credentialLabel)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Test connection/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Connect$/i })).not.toBeInTheDocument();
    const help = screen.getByLabelText(helpLabel);
    expect(help.closest('details').querySelector('a')).toHaveAttribute('href', expect.stringContaining(helpHost));
  }
  ['Automatic', 'Manual', 'Run Setup Check', 'Revert Draft'].forEach((label) => {
    expect(screen.queryByText(label)).not.toBeInTheDocument();
  });
});

it('renders last-confirmed connector timestamps consistently in browser local time', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  const storedUtc = '2026-10-13T01:26:45';
  const expectedLocal = new Date(`${storedUtc}Z`).toLocaleString();
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'disconnected', connected: false,
      last_confirmed_at: storedUtc, jira: { data_project_scope: 'all' },
    }] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [{
      id: 'same-check', timestamp: storedUtc, action: 'health_check', status: 'success', message: '',
    }] }));
    throw new Error(`Unexpected request: ${url}`);
  });

  render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);

  expect(await screen.findByText(`Last confirmed ${expectedLocal}`)).toBeInTheDocument();
  expect(await screen.findByText(expectedLocal, { selector: 'time' })).toBeInTheDocument();
});

it('shows a stale connector with a neutral dot and setup summary', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  const confirmedAt = '2026-09-30T12:00:00Z';
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'disconnected', connected: false,
      jira: { data_project_scope: 'all' },
    }, {
      id: 'salesforce_insights', label: 'Salesforce', implementation_status: 'implemented', lifecycle_status: 'connected', connected: true,
      freshness: 'unconfirmed', last_confirmed_at: confirmedAt,
      salesforce: { instance_url: 'https://acme.my.salesforce.com' },
    }] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events: [] }));
    throw new Error(`Unexpected request: ${url}`);
  });

  const { container } = render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);

  expect(await screen.findByText('1 set up')).toBeInTheDocument();
  expect(container.querySelector('.connector-list-item-dot.is-unconfirmed')).toBeInTheDocument();
});

it('hides raw provider errors behind Details and shows activity 10 at a time', async () => {
  mockUser = { subscription_plan: 'business', active_organization_plan_key: 'business' };
  const events = Array.from({ length: 12 }, (_, index) => ({
    id: `event-${index}`,
    timestamp: `2026-10-13T${String(23 - index).padStart(2, '0')}:00:00Z`,
    action: 'pm_sync',
    status: index === 0 ? 'failed' : 'success',
    message: index === 0 ? "HTTP 405: {'type': 'about:blank', 'title': 'Method Not Allowed'}" : '',
  }));
  authFetch.mockImplementation((url) => {
    if (String(url).includes('/api/v1/connectors/status')) return Promise.resolve(response({ connectors: [{
      id: 'jira_sync', label: 'Jira', implementation_status: 'implemented', lifecycle_status: 'disconnected', connected: false,
      jira: { data_project_scope: 'all' },
    }] }));
    if (String(url).includes('/api/v1/ai-agent/threads')) return Promise.resolve(response({ success: true, sessions: [] }));
    if (String(url).includes('/api/v1/pm-sync/bindings')) return Promise.resolve(response({ bindings: [] }));
    if (String(url).includes('/audit')) return Promise.resolve(response({ events }));
    throw new Error(`Unexpected request: ${url}`);
  });

  const { container } = render(<MemoryRouter initialEntries={['/connectors-manage']}><ConnectorsManage /></MemoryRouter>);
  await waitFor(() => expect(container.querySelectorAll('.connector-activity-list li')).toHaveLength(10));
  expect(screen.getByText("Some Jira links couldn't be added — fixed in a later sync")).toBeInTheDocument();
  expect(screen.queryByText(/about:blank/)).not.toBeInTheDocument();

  const firstActivity = container.querySelector('.connector-activity-list li');
  fireEvent.click(within(firstActivity).getByRole('button', { name: 'Details' }));
  expect(within(firstActivity).getByText(/about:blank/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Show more' }));
  expect(container.querySelectorAll('.connector-activity-list li')).toHaveLength(12);
  expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument();
});
