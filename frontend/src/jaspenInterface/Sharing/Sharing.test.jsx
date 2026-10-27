import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import ShareButton from './ShareButton';
import SharedPage from './SharedPage';
import SharedWithJaspenList from './SharedWithJaspenList';
import { Jaspen } from '../Workspace/JaspenClient';

jest.mock('../Workspace/JaspenClient', () => ({
  Jaspen: {
    previewShare: jest.fn(),
    createShare: jest.fn(),
    listShares: jest.fn(),
    revokeShare: jest.fn(),
    previewDecisionShare: jest.fn(),
    createDecisionShare: jest.fn(),
    listDecisionShares: jest.fn(),
    withdrawDecisionShare: jest.fn(),
    getShareManage: jest.fn(),
    saveSharePresentation: jest.fn(),
  },
}));

const snapshot = { scorecard: { project_name: 'Paid search', jaspen_score: 72 } };
const tradeoffSnapshot = {
  scorecards: [
    { id: 'c1', project_name: 'Paid search', jaspen_score: 72 },
    { id: 'c2', project_name: 'Partner channel', jaspen_score: 64 },
  ],
};
const summary = (overrides = {}) => ({
  scorecard_count: 1,
  evidence_quotes_available: 3,
  evidence_quotes_included: false,
  includes_financials: false,
  includes_rationale: true,
  includes_risks: true,
  includes_assumptions: false,
  excluded_always: ['Chat conversation', 'Uploaded files'],
  available_facts: [
    { key: 'contract_value', label: 'Contract value', value: 2400000, unit: 'USD' },
    { key: 'margin_pct', label: 'Margin', value: 18, unit: 'percent' },
  ],
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
      disclosure_review: {
        required: !payload?.disclosure_settings?.include_financials,
        matches: [],
        warning: 'Automated detection can miss figures written in other ways. Review the shared narrative before creating this link.',
      },
    }));
    Jaspen.createShare.mockResolvedValue({
      link: { id: 'l1', url: 'https://jaspen.ai/s/abc', expires_at: '2026-10-26T00:00:00Z', status: 'active' },
    });
    Jaspen.previewDecisionShare.mockResolvedValue({
      artifact_type: 'scorecard', snapshot, snapshot_sha256: 'preview-hash',
    });
    Jaspen.createDecisionShare.mockResolvedValue({ share: { id: 'ds1' } });
    Jaspen.listDecisionShares.mockResolvedValue({ shares: [] });
    Jaspen.withdrawDecisionShare.mockResolvedValue({ share: { id: 'ds1', status: 'withdrawn' } });
  });

  test('previews without evidence, then creates a 30-day link by default', async () => {
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));

    expect(await screen.findByRole('heading', { name: 'Should we pursue Paid search?' })).toBeInTheDocument();
    expect(Jaspen.previewShare).toHaveBeenCalledWith(expect.objectContaining({
      artifact_type: 'scorecard', thread_id: 't1', scorecard_id: 'card-a', include_evidence: false,
    }));
    expect(screen.getByText(/Evidence quotes from your conversation \(3\)/)).toBeInTheDocument();
    expect(screen.getByLabelText('Link expires')).toHaveValue('30');

    expect(screen.getByRole('button', { name: 'Create link' })).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /I reviewed the shared narrative/ }));
    await user.click(screen.getByRole('button', { name: 'Create link' }));
    expect(Jaspen.createShare).toHaveBeenCalledWith(expect.objectContaining({
      expires_in_days: 30,
      include_evidence: false,
      disclosure_review_confirmed: true,
    }));
    expect(await screen.findByDisplayValue('https://jaspen.ai/s/abc')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download PDF' })).toHaveAttribute('href', 'https://jaspen.ai/s/abc?print=1');
    expect(screen.getByRole('link', { name: 'Email' }).getAttribute('href')).toContain('mailto:');
  });

  test('turning on evidence rebuilds the preview before sharing', async () => {
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));
    await screen.findByRole('heading', { name: 'Should we pursue Paid search?' });

    await user.click(screen.getByRole('checkbox', { name: /Include evidence quotes/ }));
    await waitFor(() => expect(Jaspen.previewShare).toHaveBeenLastCalledWith(
      expect.objectContaining({ include_evidence: true }),
    ));
  });

  test('turning Facts on selects every fact and allows individual exclusions', async () => {
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));
    await screen.findByRole('heading', { name: 'Should we pursue Paid search?' });

    await user.click(screen.getByRole('checkbox', { name: /^Facts/ }));
    await waitFor(() => expect(Jaspen.previewShare).toHaveBeenLastCalledWith(
      expect.objectContaining({
        disclosure_settings: expect.objectContaining({
          include_facts: true,
          fact_keys: ['contract_value', 'margin_pct'],
        }),
      }),
    ));
    await user.click(screen.getByRole('checkbox', { name: 'Margin' }));
    await waitFor(() => expect(Jaspen.previewShare).toHaveBeenLastCalledWith(
      expect.objectContaining({
        disclosure_settings: expect.objectContaining({ fact_keys: ['contract_value'] }),
      }),
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

  test('Share with Jaspen renders the preview and confirms the exact hash', async () => {
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share with Jaspen' }));
    expect(await screen.findByRole('heading', { name: 'Should we pursue Paid search?' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm share' }));
    expect(Jaspen.createDecisionShare).toHaveBeenCalledWith({
      thread_id: 't1', scorecard_id: 'card-a', snapshot_sha256: 'preview-hash', preview_confirmed: true,
    });
    expect(await screen.findByText('Decision shared with Jaspen.')).toBeInTheDocument();
  });

  test('mounts both share dialog backdrops directly under document.body', async () => {
    const user = userEvent.setup();
    const shell = document.createElement('div');
    shell.className = 'jas-shell';
    document.body.appendChild(shell);
    render(<ShareButton threadId="t1" scorecardId="card-a" />, { container: shell });

    await user.click(screen.getByRole('button', { name: 'Share' }));
    let backdrop = Array.from(document.body.children)
      .find((element) => element.classList.contains('share-modal-backdrop'));
    expect(backdrop).toBeDefined();
    expect(backdrop.parentElement).toBe(document.body);
    expect(shell).not.toContainElement(backdrop);

    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(document.body.querySelector('.share-modal-backdrop')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Share with Jaspen' }));
    backdrop = Array.from(document.body.children)
      .find((element) => element.classList.contains('share-modal-backdrop'));
    expect(backdrop).toBeDefined();
    expect(backdrop.parentElement).toBe(document.body);
    expect(shell).not.toContainElement(backdrop);
  });

  test('Share with Jaspen reloads the preview when the decision changed', async () => {
    const changed = Object.assign(new Error('This decision changed after the preview.'), { status: 409 });
    Jaspen.createDecisionShare.mockRejectedValueOnce(changed);
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share with Jaspen' }));
    await screen.findByRole('heading', { name: 'Should we pursue Paid search?' });
    await user.click(screen.getByRole('button', { name: 'Confirm share' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('changed after the preview');
    await waitFor(() => expect(Jaspen.previewDecisionShare).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('heading', { name: 'Should we pursue Paid search?' })).toBeInTheDocument();
  });

  test('both share previews use the one-pager for trade-off snapshots', async () => {
    Jaspen.previewShare.mockResolvedValue({
      artifact_type: 'tradeoff', title: 'Channel choice', snapshot: tradeoffSnapshot,
      summary: summary({ scorecard_count: 2 }),
      disclosure_review: { required: false, matches: [], warning: null },
    });
    Jaspen.previewDecisionShare.mockResolvedValue({
      artifact_type: 'tradeoff', title: 'Channel choice', snapshot: tradeoffSnapshot, snapshot_sha256: 'tradeoff-hash',
    });
    const user = userEvent.setup();
    const first = render(<ShareButton threadId="t1" artifactType="tradeoff" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));
    expect(await screen.findByRole('heading', { name: 'Which option should we choose?' })).toBeInTheDocument();
    expect(first.container.querySelector('[class*="score-dashboard"]')).toBeNull();
    first.unmount();

    const second = render(<ShareButton threadId="t1" artifactType="tradeoff" />);
    await user.click(screen.getByRole('button', { name: 'Share with Jaspen' }));
    expect(await screen.findByRole('heading', { name: 'Which option should we choose?' })).toBeInTheDocument();
    expect(second.container.querySelector('[class*="score-dashboard"]')).toBeNull();
  });

  test('reserves the disclosure summary and modal height before the preview resolves', async () => {
    let resolvePreview;
    Jaspen.previewShare.mockReturnValue(new Promise((resolve) => { resolvePreview = resolve; }));
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share' }));

    const slotBefore = screen.getByTestId('share-includes-slot');
    expect(slotBefore).toHaveStyle({ minHeight: '176px' });

    resolvePreview({
      artifact_type: 'scorecard', title: 'Paid search', snapshot, summary: summary(),
      disclosure_review: { required: true, matches: [], warning: 'Review it.' },
    });
    await screen.findByRole('heading', { name: 'Should we pursue Paid search?' });
    expect(screen.getByTestId('share-includes-slot')).toBe(slotBefore);
    expect(screen.getByTestId('share-includes-slot')).toHaveStyle({ minHeight: '176px' });
  });

  test('Share with Jaspen shows an API refusal reason', async () => {
    Jaspen.previewDecisionShare.mockRejectedValue(new Error(
      'Sharing decisions with Jaspen is off. An owner or admin can turn it on in Team settings.',
    ));
    const user = userEvent.setup();
    render(<ShareButton threadId="t1" scorecardId="card-a" />);
    await user.click(screen.getByRole('button', { name: 'Share with Jaspen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('owner or admin can turn it on in Team settings');
  });
});

describe('SharedWithJaspenList', () => {
  test('Withdraw calls the decision-share DELETE client', async () => {
    Jaspen.listDecisionShares
      .mockResolvedValueOnce({ shares: [{ id: 'ds1', thread_id: 't1', scorecard_id: 'card-a', user_id: 'u1', title: 'Paid search', shared_by: 'pat@example.com', status: 'shared' }] })
      .mockResolvedValueOnce({ shares: [{ id: 'ds1', thread_id: 't1', scorecard_id: 'card-a', user_id: 'u1', status: 'withdrawn' }] });
    const user = userEvent.setup();
    render(<SharedWithJaspenList />);
    expect(await screen.findByText('Paid search')).toBeInTheDocument();
    expect(screen.getByText('pat@example.com')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Withdraw' }));
    expect(Jaspen.withdrawDecisionShare).toHaveBeenCalledWith('ds1');
    expect(await screen.findByText('Withdrawn')).toBeInTheDocument();
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
    const snapshotWithSources = { ...snapshot, context: { data_sources: ['jira'] } };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ artifact_type: 'scorecard', title: 'Paid search', created_at: '2026-09-26T00:00:00Z', expires_at: null, snapshot: snapshotWithSources }),
    });
    renderAt('/s/tok123');

    expect(await screen.findByRole('heading', { name: 'Should we pursue Paid search?' })).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/api/v1/shares/public/tok123'), { credentials: 'omit' });
    expect(screen.getByText('Made with Jaspen')).toBeInTheDocument();
    expect(screen.getByText('Jira')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Report this page' })).toBeInTheDocument();
    expect(document.querySelector('meta[name="robots"]').content).toContain('noindex');
  });

  test('the public page uses saved presentation wording and never shows owner edit controls', async () => {
    const presentedSnapshot = {
      ...snapshot,
      presentation: { text: { headline: 'Is paid search worth it?' } },
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ artifact_type: 'scorecard', title: 'Paid search', created_at: '2026-09-26T00:00:00Z', expires_at: null, snapshot: presentedSnapshot }),
    });
    Jaspen.getShareManage.mockResolvedValue({ owner: true, can_edit: true, presentation: {} });
    renderAt('/s/tok123');

    expect(await screen.findByRole('heading', { name: 'Is paid search worth it?' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(Jaspen.getShareManage).not.toHaveBeenCalled();
  });

  test('visitors who do not own the link get no Edit button', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ artifact_type: 'scorecard', title: 'Paid search', created_at: '2026-09-26T00:00:00Z', expires_at: null, snapshot }),
    });
    Jaspen.getShareManage.mockRejectedValue(new Error('HTTP 401'));
    renderAt('/s/tok123');
    expect(await screen.findByRole('heading', { name: 'Should we pursue Paid search?' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
  });

  test('shows one message for missing, expired, and revoked links', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    renderAt('/s/gone');
    expect(await screen.findByText(/no longer available/)).toBeInTheDocument();
  });
});
