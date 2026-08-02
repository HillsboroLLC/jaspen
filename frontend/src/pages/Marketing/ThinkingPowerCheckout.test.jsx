import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ThinkingPowerCheckout from './ThinkingPowerCheckout';

const mockSignup = jest.fn();
const mockLogin = jest.fn();
const mockAuthFetch = jest.fn();
const mockLoadStripe = jest.fn();
let mockUser = null;

jest.mock('../../shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, signup: mockSignup, login: mockLogin }),
}));

jest.mock('../../shared/auth/http', () => ({
  authFetch: (...args) => mockAuthFetch(...args),
  buildAuthHeaders: () => ({ 'Content-Type': 'application/json' }),
}));

jest.mock('@stripe/stripe-js', () => ({
  loadStripe: (...args) => mockLoadStripe(...args),
}));

jest.mock('@stripe/react-stripe-js', () => ({
  Elements: ({ children }) => <div>{children}</div>,
  PaymentElement: () => <div data-testid="payment-element" />,
  useStripe: () => ({}),
  useElements: () => ({}),
}));

describe('Limited-time offer checkout acknowledgements', () => {
  beforeEach(() => {
    mockUser = null;
    mockSignup.mockReset();
    mockLogin.mockReset();
    mockAuthFetch.mockReset();
    mockLoadStripe.mockReset();
    mockLoadStripe.mockResolvedValue({});
  });

  it('requires the terms acknowledgement before account creation', () => {
    render(<ThinkingPowerCheckout onClose={() => {}} />);

    const createButton = screen.getByRole('button', { name: 'Confirm account' });
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

    render(<ThinkingPowerCheckout onClose={() => {}} campaignId="limited_time_300k_pmo" returnPath="/limited-time/project-prioritization" />);

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
      campaign_id: 'limited_time_300k_pmo',
      return_path: '/limited-time/project-prioritization',
      terms_accepted: true,
      final_sale_acknowledged: true,
    });
  });

  it('switches to sign in with a clear instruction when the email is already registered', async () => {
    const user = userEvent.setup();
    mockSignup.mockResolvedValue({ success: false, error: 'Email already registered' });

    render(<ThinkingPowerCheckout onClose={() => {}} />);

    await user.type(screen.getByLabelText('Full name'), 'Jane Doe');
    await user.type(screen.getByLabelText('Email'), 'jane@example.com');
    await user.type(screen.getByLabelText('Password'), 'password123');
    await user.type(screen.getByLabelText('Confirm password'), 'password123');
    await user.click(screen.getByRole('checkbox', { name: /I have read and agree to the Terms of Service/i }));
    await user.click(screen.getByRole('button', { name: 'Confirm account' }));

    expect(await screen.findByText('This email is already registered. Enter your password to sign in and continue.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Sign in' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('applies a promo code on the payment screen and updates the price shown', async () => {
    const user = userEvent.setup();
    mockUser = { id: 'user_1', email: 'owner@example.com' };
    mockAuthFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          client_secret: 'pi_limited_time_300k_abc_secret_xyz',
          publishable_key: 'pk_test_123',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ price_label: '$799.20' }),
      });

    render(<ThinkingPowerCheckout onClose={() => {}} campaignId="limited_time_300k_pmo" returnPath="/limited-time/project-prioritization" />);

    fireEvent.click(screen.getByRole('checkbox', { name: /I have read and agree to the Terms of Service/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /all sales are final except for a qualifying Covered Technical Failure/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue to pay $999' }));

    const couponInput = await screen.findByLabelText('Promo code (optional)');
    await user.type(couponInput, 'LAUNCH20');
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => expect(mockAuthFetch).toHaveBeenCalledTimes(2));
    const [url, request] = mockAuthFetch.mock.calls[1];
    expect(url).toContain('/api/v1/billing/apply-300k-limited-time-coupon');
    expect(JSON.parse(request.body)).toEqual({
      payment_intent_id: 'pi_limited_time_300k_abc',
      coupon_code: 'LAUNCH20',
    });
    expect(await screen.findByText("Promo code applied — you'll pay $799.20 instead of $999.")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Pay \$799\.20/ })).toBeInTheDocument();
  });

  it('links to all policies from the acknowledgement', () => {
    render(<ThinkingPowerCheckout onClose={() => {}} />);

    expect(screen.getByRole('link', { name: 'Terms of Service' })).toHaveAttribute('href', '/pages/terms');
    expect(screen.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/pages/privacy');
    expect(screen.getByRole('link', { name: 'AI limitations and refund terms' })).toHaveAttribute('href', '/limited-time/terms-and-conditions');
  });
});
