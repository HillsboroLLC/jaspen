import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ThinkingPowerCheckout from './ThinkingPowerCheckout';

const mockSignup = jest.fn();
const mockLogin = jest.fn();
const mockAuthFetch = jest.fn();
let mockUser = null;

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, signup: mockSignup, login: mockLogin }),
}));

jest.mock('../../shared/auth/http', () => ({
  authFetch: (...args) => mockAuthFetch(...args),
  buildAuthHeaders: () => ({ 'Content-Type': 'application/json' }),
}));

describe('Limited-time offer checkout acknowledgements', () => {
  beforeEach(() => {
    mockUser = null;
    mockSignup.mockReset();
    mockLogin.mockReset();
    mockAuthFetch.mockReset();
  });

  it('requires the terms acknowledgement before account creation', () => {
    render(<ThinkingPowerCheckout onClose={() => {}} />);

    const createButton = screen.getByRole('button', { name: 'Create account and continue' });
    const googleButton = screen.getByRole('button', { name: 'Continue with Google' });
    const terms = screen.getByRole('checkbox', { name: /I have read and agree to the Terms of Service/i });

    expect(terms).not.toBeChecked();
    expect(createButton).toBeDisabled();
    expect(googleButton).toBeDisabled();
    fireEvent.click(terms);
    expect(createButton).toBeEnabled();
    expect(googleButton).toBeEnabled();
  });

  it('requires both acknowledgements before creating a Stripe checkout session', async () => {
    mockUser = { id: 'user_1', email: 'owner@example.com' };
    mockAuthFetch.mockResolvedValue({
      ok: false,
      json: async () => ({ msg: 'Test stopped before redirect.' }),
    });

    render(<ThinkingPowerCheckout onClose={() => {}} campaignId="advantage_pmo" returnPath="/limited-time/project-prioritization" />);

    const terms = screen.getByRole('checkbox', { name: /I have read and agree to the Terms of Service/i });
    const finalSale = screen.getByRole('checkbox', { name: /all sales are final except for a qualifying Covered Technical Failure/i });
    const payButton = screen.getByRole('button', { name: 'Continue to pay $999' });

    expect(terms).not.toBeChecked();
    expect(finalSale).not.toBeChecked();
    expect(payButton).toBeDisabled();
    fireEvent.click(terms);
    expect(payButton).toBeDisabled();
    fireEvent.click(finalSale);
    expect(payButton).toBeEnabled();
    fireEvent.click(payButton);

    await waitFor(() => expect(mockAuthFetch).toHaveBeenCalledTimes(1));
    const [, request] = mockAuthFetch.mock.calls[0];
    expect(JSON.parse(request.body)).toEqual({
      campaign_id: 'advantage_pmo',
      return_path: '/limited-time/project-prioritization',
      terms_accepted: true,
      final_sale_acknowledged: true,
    });
  });

  it('links to all policies from the acknowledgement', () => {
    render(<ThinkingPowerCheckout onClose={() => {}} />);

    expect(screen.getByRole('link', { name: 'Terms of Service' })).toHaveAttribute('href', '/pages/terms');
    expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/pages/privacy');
    expect(screen.getByRole('link', { name: 'AI limitations and refund terms' })).toHaveAttribute('href', '/limited-time/terms-and-conditions');
  });
});
