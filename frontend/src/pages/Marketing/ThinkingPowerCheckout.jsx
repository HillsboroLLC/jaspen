import React, { useEffect, useRef, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { Elements, PaymentElement, useStripe, useElements } from '@stripe/react-stripe-js';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import { LIMITED_TIME_300K_CREDITS, LIMITED_TIME_300K_PRICE } from './founderCampaigns';

const MAGENTA = '#a0036c';
const STRIPE_APPEARANCE = {
  theme: 'flat',
  variables: {
    colorPrimary: MAGENTA,
    colorText: '#0f172a',
    colorTextSecondary: '#64748b',
    colorBackground: '#ffffff',
    colorDanger: '#dc2626',
    fontFamily: "'Inter', 'Inter Tight', system-ui, sans-serif",
    borderRadius: '8px',
    spacingUnit: '4px',
  },
  rules: {
    '.Input': { border: '1px solid #e6eaf2', boxShadow: 'none', padding: '10px 12px' },
    '.Input:focus': { border: `1px solid ${MAGENTA}`, boxShadow: `0 0 0 1px ${MAGENTA}` },
    '.Label': { fontWeight: '600', color: '#475569' },
  },
};

const inputStyle = {
  width: '100%', padding: '11px 12px', border: '1px solid #e6eaf2', borderRadius: 8,
  fontSize: 14, fontFamily: 'inherit', color: '#0f172a', outline: 'none', background: '#fbfcff',
  marginBottom: 12,
};
const labelStyle = { display: 'block', fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 6 };
const errorBox = { marginTop: 4, marginBottom: 12, fontSize: 13, color: '#b42318', background: '#fef3f2', border: '1px solid #fecdca', borderRadius: 8, padding: '9px 11px' };
const noticeBox = { fontSize: 13, color: '#0f172a', background: '#f8f5f0', border: '1px solid #ecdcc9', borderRadius: 8, padding: '12px 14px', lineHeight: 1.5 };

function TermsAcknowledgement({ id, checked, onChange }) {
  return (
    <label className="fc-checkout-acknowledgement" htmlFor={id}>
      <input id={id} type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>
        I have read and agree to the{' '}
        <a href="/pages/terms" target="_blank" rel="noopener noreferrer">Terms of Service</a> and{' '}
        <a href="/pages/privacy" target="_blank" rel="noopener noreferrer">Privacy Policy</a>, including the{' '}
        <a href="/limited-time/terms-and-conditions" target="_blank" rel="noopener noreferrer">AI limitations and refund terms</a>.
      </span>
    </label>
  );
}

function AccountStep({ returnPath }) {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState('signup');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const isSignup = mode === 'signup';

  const handleGoogle = () => {
    if (isSignup && !termsAccepted) {
      setError('Review and accept the terms before creating your account.');
      return;
    }
    const next = `${returnPath}?limited_time_checkout=resume`;
    window.location.href = `${API_BASE}/api/v1/auth/google/start?next=${encodeURIComponent(next)}`;
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    setError('');
    setNotice('');
    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail || !password) return setError('Enter your email and password.');
    if (isSignup && !String(name).trim()) return setError('Enter your name.');
    if (isSignup && password !== confirm) return setError('Those passwords do not match.');
    if (isSignup && !termsAccepted) return setError('Review and accept the terms before creating your account.');

    setSubmitting(true);
    try {
      const result = isSignup
        ? await signup(normalizedEmail, password, String(name).trim(), {
          planKey: '300k_limited_time',
          nextPath: `${returnPath}?limited_time_checkout=resume`,
        })
        : await login(normalizedEmail, password);
      if (result?.success) return;
      if (result?.mfaRequired) {
        setNotice('Your account uses two-step verification. Sign in first, then reopen this offer to complete your purchase.');
      } else if (result?.verificationRequired) {
        setNotice(`Check ${normalizedEmail} for a verification link. Click it to continue straight to payment — no need to come back here.`);
      } else if (isSignup && /already registered/i.test(String(result?.error || ''))) {
        // Don't dead-end on a raw error — this email already has an
        // account, so the actual instruction is to sign in with it.
        setMode('signin');
        setPassword('');
        setConfirm('');
        setError('');
        setNotice('This email is already registered. Enter your password to sign in and continue.');
      } else {
        setError(result?.error || (isSignup ? 'Unable to create your account right now.' : 'Incorrect email or password.'));
      }
    } catch (err) {
      setError(err?.message || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="fc-checkout-tabs" role="tablist" aria-label="Account options">
        {[['signup', 'Create account'], ['signin', 'Sign in']].map(([key, text]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mode === key}
            onClick={() => { setMode(key); setTermsAccepted(false); setError(''); setNotice(''); }}
          >
            {text}
          </button>
        ))}
      </div>
      <button type="button" className="fc-checkout-google" disabled={isSignup && !termsAccepted} onClick={handleGoogle}>Continue with Google</button>
      <div className="fc-checkout-divider"><span />OR<span /></div>
      <form onSubmit={handleSubmit}>
        {isSignup && <><label htmlFor="limited-time-name" style={labelStyle}>Full name</label><input id="limited-time-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" style={inputStyle} /></>}
        <label htmlFor="limited-time-email" style={labelStyle}>Email</label>
        <input id="limited-time-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" style={inputStyle} />
        <label htmlFor="limited-time-password" style={labelStyle}>Password</label>
        <input id="limited-time-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={isSignup ? 'new-password' : 'current-password'} style={inputStyle} />
        {isSignup && <><label htmlFor="limited-time-confirm" style={labelStyle}>Confirm password</label><input id="limited-time-confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" style={inputStyle} /></>}
        {error && <div role="alert" style={errorBox}>{error}</div>}
        {notice && <div role="status" style={{ ...noticeBox, marginBottom: 12 }}>{notice}</div>}
        {isSignup && (
          <div className="fc-checkout-acknowledgements">
            <TermsAcknowledgement id="limited-time-signup-terms" checked={termsAccepted} onChange={setTermsAccepted} />
          </div>
        )}
        <button type="submit" className="fc-checkout-primary" disabled={submitting || (isSignup && !termsAccepted)}>
          {submitting ? 'One moment...' : isSignup ? 'Confirm account' : 'Sign in and continue'}
        </button>
      </form>
      <p className="fc-checkout-footnote">Next, you'll review and complete the one-time purchase. No subscription is created.</p>
    </div>
  );
}

function PaymentForm({ onSuccess, clientSecret }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [priceLabel, setPriceLabel] = useState(`$${LIMITED_TIME_300K_PRICE}`);
  const [appliedCoupon, setAppliedCoupon] = useState('');
  const [couponInput, setCouponInput] = useState('');
  const [couponError, setCouponError] = useState('');
  const [applyingCoupon, setApplyingCoupon] = useState(false);
  const paymentIntentId = String(clientSecret || '').split('_secret_')[0];

  const applyCoupon = async () => {
    const code = couponInput.trim();
    if (applyingCoupon || code === appliedCoupon) return;
    setApplyingCoupon(true);
    setCouponError('');
    try {
      const resp = await authFetch(`${API_BASE}/api/v1/billing/apply-300k-limited-time-coupon`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify({ payment_intent_id: paymentIntentId, coupon_code: code }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data?.msg || 'Could not apply that coupon.');
      setPriceLabel(data.price_label?.startsWith('$') ? data.price_label : `$${data.price_label}`);
      setAppliedCoupon(code);
    } catch (err) {
      setCouponError(err?.message || 'Could not apply that coupon.');
    } finally {
      setApplyingCoupon(false);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!stripe || !elements || submitting) return;
    setSubmitting(true);
    setError('');
    const { error: confirmError, paymentIntent } = await stripe.confirmPayment({
      elements,
      redirect: 'if_required',
      confirmParams: { return_url: window.location.href },
    });
    if (confirmError) {
      setError(confirmError.message || 'Your payment could not be completed.');
      setSubmitting(false);
      return;
    }
    if (paymentIntent && (paymentIntent.status === 'succeeded' || paymentIntent.status === 'processing')) {
      try {
        const resp = await authFetch(`${API_BASE}/api/v1/billing/confirm-300k-limited-time-payment`, {
          method: 'POST',
          headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
          credentials: 'include',
          body: JSON.stringify({ payment_intent_id: paymentIntent.id }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data?.msg || 'Payment completed, but credits could not be finalized.');
      } catch (err) {
        setError(err?.message || 'Payment completed, but credits could not be finalized.');
        setSubmitting(false);
        return;
      }
      onSuccess?.();
      return;
    }
    setError('Payment did not complete. Please try again.');
    setSubmitting(false);
  };

  const fullPriceLabel = `$${LIMITED_TIME_300K_PRICE}`;
  const discounted = appliedCoupon && priceLabel !== fullPriceLabel;

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ marginBottom: 16 }}>
        <label htmlFor="limited-time-coupon" style={labelStyle}>Promo code (optional)</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            id="limited-time-coupon"
            name="jaspen-promo-code"
            type="text"
            value={couponInput}
            onChange={(e) => { setCouponInput(e.target.value); setCouponError(''); }}
            placeholder="Enter promo code"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck="false"
            data-1p-ignore="true"
            data-lpignore="true"
            data-bwignore="true"
            data-form-type="other"
            style={{ ...inputStyle, marginBottom: 0, flex: 1 }}
          />
          <button
            type="button"
            onClick={applyCoupon}
            disabled={applyingCoupon || couponInput.trim() === appliedCoupon}
            style={{ border: '1px solid #dbe3ef', borderRadius: 8, background: '#fff', color: '#0f172a', padding: '0 14px', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
          >
            {applyingCoupon ? 'Applying…' : 'Apply'}
          </button>
        </div>
        {discounted && !couponError && (
          <div style={{ marginTop: 6, fontSize: 12, color: '#0d7a3e' }}>Promo code applied — you'll pay {priceLabel} instead of {fullPriceLabel}.</div>
        )}
        {couponError && (
          <div style={{ marginTop: 6, fontSize: 12, color: '#b42318' }}>{couponError}</div>
        )}
      </div>
      <PaymentElement options={{ layout: 'tabs' }} />
      {error && <div role="alert" style={{ ...errorBox, marginTop: 12 }}>{error}</div>}
      <button type="submit" className="fc-checkout-primary" disabled={!stripe || submitting} style={{ marginTop: 16 }}>
        {submitting
          ? 'Confirming payment...'
          : discounted
            ? <>Pay {priceLabel} <span style={{ textDecoration: 'line-through', opacity: 0.65, marginLeft: 4 }}>{fullPriceLabel}</span></>
            : `Pay ${priceLabel}`}
      </button>
      <p className="fc-checkout-footnote">Payment is processed securely. Your credits are granted after payment is confirmed.</p>
    </form>
  );
}

function PurchaseStep({ campaignId, returnPath, onSuccess }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [finalSaleAccepted, setFinalSaleAccepted] = useState(false);
  const [clientSecret, setClientSecret] = useState('');
  const [stripePromise, setStripePromise] = useState(null);
  const acknowledgementsComplete = termsAccepted && finalSaleAccepted;

  const startCheckout = async () => {
    if (submitting) return;
    if (!acknowledgementsComplete) {
      setError('Accept both acknowledgements before continuing to payment.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/billing/create-300k-limited-time-payment-intent`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify({
          campaign_id: campaignId,
          return_path: returnPath,
          terms_accepted: true,
          final_sale_acknowledged: true,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.client_secret) throw new Error(data?.msg || 'Could not start secure checkout.');
      if (!data.publishable_key) throw new Error('Payments are not configured yet.');
      setStripePromise((prev) => prev || loadStripe(data.publishable_key));
      setClientSecret(data.client_secret);
    } catch (err) {
      setError(err?.message || 'Could not start secure checkout.');
    } finally {
      setSubmitting(false);
    }
  };

  if (clientSecret && stripePromise) {
    return (
      <Elements stripe={stripePromise} options={{ clientSecret, appearance: STRIPE_APPEARANCE }}>
        <PaymentForm onSuccess={onSuccess} clientSecret={clientSecret} />
      </Elements>
    );
  }

  return (
    <div>
      <ul className="fc-checkout-summary">
        <li><strong>Personal account</strong><span>non-transferable and not shared</span></li>
      </ul>
      {error && <div role="alert" style={errorBox}>{error}</div>}
      <div className="fc-checkout-acknowledgements">
        <TermsAcknowledgement id="limited-time-purchase-terms" checked={termsAccepted} onChange={setTermsAccepted} />
        <label className="fc-checkout-acknowledgement" htmlFor="limited-time-final-sale">
          <input id="limited-time-final-sale" type="checkbox" checked={finalSaleAccepted} onChange={(event) => setFinalSaleAccepted(event.target.checked)} />
          <span>I understand that AI-generated outputs may contain errors and that all sales are final except for a qualifying Covered Technical Failure or where a refund is required by law.</span>
        </label>
      </div>
      <button type="button" className="fc-checkout-primary" disabled={submitting || !acknowledgementsComplete} onClick={startCheckout}>
        {submitting ? 'Loading payment…' : `Continue to pay $${LIMITED_TIME_300K_PRICE}`}
      </button>
      <p className="fc-checkout-footnote">A promo code field is on the next screen, next to payment. Payment is processed securely. Your credits are granted after payment is confirmed.</p>
    </div>
  );
}

export default function ThinkingPowerCheckout({ onClose, onSuccess, campaignId = '', returnPath = '/limited-time/client-decisions' }) {
  const { user } = useAuth();
  const closeRef = useRef(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event) => { if (event.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="fc-checkout-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="limited-time-checkout-title" className="fc-checkout-dialog">
        <div className="fc-checkout-header">
          <div>
            <span>Limited-time offer</span>
            <h2 id="limited-time-checkout-title">{LIMITED_TIME_300K_CREDITS} usage credits</h2>
            <p>${LIMITED_TIME_300K_PRICE} once. No subscription. Non-expiring.</p>
            <p>{user ? 'Review the offer, then continue to payment.' : 'Create or sign in to your personal Jaspen account.'}</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close checkout">×</button>
        </div>
        <div className="fc-checkout-body">
          {user ? <PurchaseStep campaignId={campaignId} returnPath={returnPath} onSuccess={onSuccess} /> : <AccountStep returnPath={returnPath} />}
        </div>
      </div>
    </div>
  );
}
