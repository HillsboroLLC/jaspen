import React from 'react';
import { render, waitFor } from '@testing-library/react';
import AuthCallback from './AuthCallback';

const mockNavigate = jest.fn();
const mockSetMfaEnforcement = jest.fn();
const mockAuthFetch = jest.fn();

jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useLocation: () => ({ search: '?next=%2Fnew&mfa=1' }),
}));
jest.mock('../auth/AuthContext', () => ({ useAuth: () => ({ setMfaEnforcement: mockSetMfaEnforcement }) }));
jest.mock('../auth/http', () => ({ authFetch: (...args) => mockAuthFetch(...args) }));
jest.mock('../auth/pendingIntakeContext', () => ({
  readPendingIntakeContext: () => null,
  clearPendingIntakeContext: jest.fn(),
  getOrCreatePendingThreadId: jest.fn(),
  clearPendingIntakeThreadId: jest.fn(),
  runExclusiveHandoff: jest.fn(),
}));

it('finishes a Google sign-in that needs 2FA in the challenge form', async () => {
  mockAuthFetch.mockResolvedValue({
    ok: true,
    json: async () => ({ mfa_required: true, mfa_setup_required: false, pending_token: 'pending-1' }),
  });
  render(<AuthCallback />);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/?auth=1', { replace: true }));
  expect(mockAuthFetch).toHaveBeenCalledWith('/api/v1/auth/mfa/pending');
  expect(mockSetMfaEnforcement).toHaveBeenCalledWith(expect.objectContaining({
    mfaRequired: true, pendingToken: 'pending-1', mfaSetupRequired: false,
  }));
});
