import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RankThemPromoModal from './RankThemPromoModal';

const mockAuthFetch = jest.fn();
let mockUser = null;

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}));

jest.mock('../../shared/auth/http', () => ({
  authFetch: (...args) => mockAuthFetch(...args),
}));

function jsonResponse(body) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

/** Resolves only when `release()` is called — lets a test control which of two
 *  in-flight requests answers first. */
function deferredJson(body) {
  let release;
  const promise = new Promise((resolve) => {
    release = () => resolve({ ok: true, json: () => Promise.resolve(body) });
  });
  return { promise, release: (...args) => release(...args) };
}

const ACTIVE_PROMOTION = {
  promotion: { active: true, headline: 'RANK THEM', campaign_path: '/limited-time/project-prioritization' },
};

function renderModal() {
  return render(<MemoryRouter><RankThemPromoModal /></MemoryRouter>);
}

async function settle() {
  // Let the pending fetch promises flush before the dwell timer runs.
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

describe('RANK THEM promotion modal', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockUser = null;
    mockAuthFetch.mockReset();
    window.localStorage.clear();
    global.fetch = jest.fn(() => jsonResponse(ACTIVE_PROMOTION));
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  it('appears for a visitor once the dwell time has passed', async () => {
    renderModal();
    await settle();

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => { jest.advanceTimersByTime(12000); });

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /RANK THEM/i })).toBeInTheDocument();
  });

  it('never appears for someone who already bought the offer, even when billing answers last', async () => {
    // The realistic ordering: the promotion config comes back before the
    // slower authenticated billing lookup that reveals the purchase.
    mockUser = { id: 'u1' };
    const billing = deferredJson({ has_300k_limited_time: true });
    mockAuthFetch.mockImplementation(() => billing.promise);

    renderModal();
    await settle();

    await act(async () => { billing.release(); await Promise.resolve(); });
    await act(async () => { jest.advanceTimersByTime(12000); });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
