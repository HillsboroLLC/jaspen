import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import ShareButton from './ShareButton';
import SharedPage from './SharedPage';
import { Jaspen } from '../Workspace/JaspenClient';

jest.mock('../Workspace/JaspenClient', () => ({
  Jaspen: {
    previewShare: jest.fn(),
    createShare: jest.fn(),
    listShares: jest.fn(),
    revokeShare: jest.fn(),
  },
}));

// The real views are exercised by their own tests; here we only need to know
// which snapshot reached them.
jest.mock('./SharedArtifactView', () => ({ artifactType, snapshot }) => (
  <div data-testid="shared-view">{artifactType}:{snapshot?.scorecard?.project_name}</div>
));

const snapshot = { scorecard: { project_name: 'Paid search', jaspen_score: 72 } };
const summary = (overrides = {}) => ({
  scorecard_count: 1,
  evidence_quotes_available: 3,
  evidence_quotes_included: false,
  includes_financials: false,
  includes_rationale: true,
  includes_risks: true,
  includes_assumptions: false,
  excluded_always: ['Chat conversation', 'Uploaded files'],
  ...overrides,
});

describe('ShareDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    Jaspen.listShares.mockResolvedValue({ links: [], block_reason: null });
    Jaspen.previewShare.mockImplementation(async (payload) => ({
      artifact_type: 'scorecard',
      title: 'Paid search',
      snapshot,
      summary: summary({ evidence_quotes_included: payload.include_evidence }),
    }));
    Jaspen.createShare.mockResolvedValue({
      link: { id: 'l1', url: 'https://jaspen.ai/s/abc', expires_at: '2026-10-26T00:00:00Z', status: 'active' },
    });
  });

  test('previews without evidence, then creates a 30-day link by default', async () => {
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));

    expect(await screen.findByTestId('shared-view')).toHaveTextContent('scorecard:Paid search');
    expect(Jaspen.previewShare).toHaveBeenCalledWith(expect.objectContaining({
      artifact_type: 'scorecard', thread_id: 't1', scorecard_id: 'card-a', include_evidence: false,
    }));
    expect(screen.getByText(/Evidence quotes from your conversation \(3\)/)).toBeInTheDocument();
    expect(screen.getByLabelText('Link expires')).toHaveValue('30');

    await user.click(screen.getByRole('button', { name: 'Create link' }));
    expect(Jaspen.createShare).toHaveBeenCalledWith(expect.objectContaining({ expires_in_days: 30, include_evidence: false }));
    expect(await screen.findByDisplayValue('https://jaspen.ai/s/abc')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download PDF' })).toHaveAttribute('href', 'https://jaspen.ai/s/abc?print=1');
    expect(screen.getByRole('link', { name: 'Email' }).getAttribute('href')).toContain('mailto:');
  });

  test('turning on evidence rebuilds the preview before sharing', async () => {
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));
    await screen.findByTestId('shared-view');

    await user.click(screen.getByRole('checkbox', { name: /Include evidence quotes/ }));
    await waitFor(() => expect(Jaspen.previewShare).toHaveBeenLastCalledWith(
      expect.objectContaining({ include_evidence: true }),
    ));
  });

  test('free accounts see the plan requirement instead of options', async () => {
    Jaspen.listShares.mockResolvedValue({ links: [], block_reason: 'paid_plan_required' });
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));

    expect(await screen.findByText(/available on paid plans, starting with Starter/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create link' })).not.toBeInTheDocument();
  });
});

describe('SharedPage', () => {
  const renderAt = (path) => render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/s/:token" element={<SharedPage />} /></Routes>
    </MemoryRouter>,
  );

  afterEach(() => { delete global.fetch; });

  test('renders the shared copy with the footer, report link, and noindex', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ artifact_type: 'scorecard', title: 'Paid search', created_at: '2026-09-26T00:00:00Z', expires_at: null, snapshot }),
    });
    renderAt('/s/tok123');

    expect(await screen.findByRole('heading', { name: 'Paid search' })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/api/v1/shares/public/tok123'), { credentials: 'omit' });
    expect(screen.getByText('Made with Jaspen')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Report this page' })).toBeInTheDocument();
    expect(document.querySelector('meta[name="robots"]').content).toContain('noindex');
  });

  test('shows one message for missing, expired, and revoked links', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    renderAt('/s/gone');
    expect(await screen.findByText(/no longer available/)).toBeInTheDocument();
  });
});
