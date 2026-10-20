import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from './AuthContext';
import { authFetch } from './http';
import { getSignupReferralCode } from '../inviteLink';

jest.mock('./http', () => ({
  AUTH_EVENTS: {
    SESSION_EXPIRED_EVENT: 'auth-session-expired',
    SERVER_ERROR_EVENT: 'auth-server-error',
  },
  authFetch: jest.fn(),
}));

function SignupHarness() {
  const { signup } = useAuth();
  return (
    <button type="button" onClick={() => signup('new@example.com', 'StrongPass1', 'New User')}>
      Sign up
    </button>
  );
}

describe('AuthContext referral signup', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.pushState({}, '', '/?ref=abc123');
    authFetch.mockReset();
    authFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({}),
    });
  });

  afterEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('sends a saved landing-page referral and clears it only after signup succeeds', async () => {
    render(
      <AuthProvider>
        <SignupHarness />
      </AuthProvider>,
    );

    await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/me'),
      { method: 'GET' },
    ));
    window.history.pushState({}, '', '/pricing');
    expect(getSignupReferralCode()).toBe('abc123');

    authFetch.mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({ user: { id: 42, email: 'new@example.com', subscription_plan: 'free' } }),
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign up' }));

    await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/signup'),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"referral_code":"abc123"'),
      }),
    ));
    await waitFor(() => expect(getSignupReferralCode()).toBeNull());
  });

  it('keeps the saved referral when signup fails', async () => {
    render(
      <AuthProvider>
        <SignupHarness />
      </AuthProvider>,
    );

    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(1));
    window.history.pushState({}, '', '/pricing');
    authFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ message: 'Email already registered' }),
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign up' }));

    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(getSignupReferralCode()).toBe('abc123');
  });

  it('clears a saved referral when Google returns from a completed signup', async () => {
    getSignupReferralCode();
    window.history.pushState({}, '', '/auth/callback?next=%2Fnew&signup_completed=1');

    render(
      <AuthProvider>
        <SignupHarness />
      </AuthProvider>,
    );

    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(1));
    expect(getSignupReferralCode()).toBeNull();
  });
});
