import React, { useEffect, useRef, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { Elements, PaymentElement, useStripe, useElements } from '@stripe/react-stripe-js';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import { FOUNDER_CREDITS, FOUNDER_PRICE } from './founderCampaigns';

// Combined promo checkout card for the 300K Thinking Power Pack. Unlike the generic
// StrategyAccessCard (which only creates an account and then redirects to the
// workspace), this card keeps the visitor on the offer and carries the Stripe
// Payment Element itself:
//   Step 1 (only when logged out): create account / sign in, INLINE (no redirect).
//   Step 2: pay $599 today + start Essential (first month free) via the embedded
//            Payment Element (POST /api/v1/billing/create-thinking-power-checkout).
// The 300K bonus is granted webhook-side only, never here.
const NAVY = '#161f3b';
const MAGENTA = '#a0036c';

const APPEARANCE = {
  theme: 'flat',
  variables: {
    colorPrimary: MAGENTA,
    colorText: '#0f172a',
    colorTextSecondary: '#64748b',
    colorBackground: '#ffffff',
    colorDanger: '#dc2626',
    fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
    borderRadius: '8px',
    spacingUnit: '4px',
  },
  rules: {
    '.Input': { border: '1px solid #e6eaf2', boxShadow: 'none', padding: '10px 12px' },
    '.Input:focus': { border: `1px solid ${MAGENTA}`, boxShadow: `0 0 0 1px ${MAGENTA}` },
    '.Label': { fontWeight: '600', color: '#475569' },
  },
};

const fallbackIntervals = [
  { key: 'monthly', label: 'Monthly', note: 'Recurring billing begins after the included month' },
  { key: 'annual', label: 'Annual', note: 'Recurring billing begins after the included month' },
];

const inputStyle = {
  width: '100%', padding: '11px 12px', border: '1px solid #e6eaf2', borderRadius: 8,
  fontSize: 14, fontFamily: 'inherit', color: '#0f172a', outline: 'none', background: '#fbfcff',
  marginBottom: 12,
};
const labelStyle = { display: 'block', fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 6 };
const errorBox = { marginTop: 4, marginBottom: 12, fontSize: 13, color: '#dc2626', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '8px 10px' };
const noticeBox = { fontSize: 13, color: '#0f172a', background: '#f8f5f0', border: '1px solid #ecdcc9', borderRadius: 8, padding: '12px 14px', lineHeight: 1.5 };

// ------------------------------------------------------------------------
// Step 1: account (create / sign in), inline. Sets the auth cookie + context
// user; the parent then re-renders straight into the payment step.
// ------------------------------------------------------------------------
function AccountStep({ returnPath }) {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState('signup'); // 'signup' | 'signin'
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const isSignup = mode === 'signup';

  const handleGoogle = () => {
    // Google is a redirect flow; come back to the offer and auto-resume checkout.
    const next = `${returnPath}?tp_checkout=1`;
    window.location.href = `${API_BASE}/api/v1/auth/google/start?next=${encodeURIComponent(next)}`;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError('');
    setNotice('');

    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail || !password) {
      setError('Enter your email and password.');
      return;
    }
    if (isSignup && !String(name).trim()) {
      setError('Enter your name.');
      return;
    }
    if (isSignup && password !== confirm) {
      setError('Those passwords don’t match.');
      return;
    }

    setSubmitting(true);
    try {
      if (isSignup) {
        const res = await signup(normalizedEmail, password, String(name).trim(), { planKey: 'essential' });
        if (res?.success) return; // context user flips → parent shows payment step
        if (res?.verificationRequired) {
          setNotice(`Check ${normalizedEmail} to verify your account, then reopen this offer to complete payment.`);
          setSubmitting(false);
          return;
        }
        setError(res?.error || 'Unable to create your account right now.');
        setSubmitting(false);
        return;
      }

      const res = await login(normalizedEmail, password);
      if (res?.success) return; // context user flips → parent shows payment step
      if (res?.mfaRequired) {
        setNotice('Your account uses two-step verification. Please sign in on jaspen.ai first, then reopen this offer to complete your purchase.');
        setSubmitting(false);
        return;
      }
      if (res?.verificationRequired) {
        setNotice(`Check ${normalizedEmail} to verify your account, then reopen this offer to complete payment.`);
        setSubmitting(false);
        return;
      }
      setError(res?.error || 'Incorrect email or password.');
      setSubmitting(false);
    } catch (err) {
      setError(err?.message || 'Something went wrong. Please try again.');
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, background: '#f1f5f9', borderRadius: 10, padding: 4, marginBottom: 16 }}>
        {[['signup', 'Create account'], ['signin', 'Sign in']].map(([key, text]) => {
          const active = mode === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => { setMode(key); setError(''); setNotice(''); }}
              style={{
                flex: 1, border: 'none', borderRadius: 8, padding: '9px 10px', fontSize: 13, fontWeight: 600,
                cursor: 'pointer', fontFamily: 'inherit',
                background: active ? '#fff' : 'transparent',
                color: active ? NAVY : '#64748b',
                boxShadow: active ? '0 1px 2px rgba(15,23,42,0.08)' : 'none',
              }}
            >
              {text}
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={handleGoogle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          border: '1px solid #e6eaf2', borderRadius: 10, background: '#fff', color: '#0f172a',
          padding: '11px 12px', fontSize: 14, fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer',
        }}
      >
        Continue with Google
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '16px 0' }}>
        <span style={{ flex: 1, height: 1, background: '#e6eaf2' }} />
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#94a3b8' }}>OR</span>
        <span style={{ flex: 1, height: 1, background: '#e6eaf2' }} />
      </div>

      <form onSubmit={handleSubmit}>
        {isSignup && (
          <>
            <label htmlFor="tp-name" style={labelStyle}>Full name</label>
            <input id="tp-name" type="text" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="Alex Rivera" style={inputStyle} />
          </>
        )}
        <label htmlFor="tp-email" style={labelStyle}>Work email</label>
        <input id="tp-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" placeholder="you@company.com" style={inputStyle} />

        <label htmlFor="tp-password" style={labelStyle}>Password</label>
        <input id="tp-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={isSignup ? 'new-password' : 'current-password'} placeholder="••••••••" style={inputStyle} />

        {isSignup && (
          <>
            <label htmlFor="tp-confirm" style={labelStyle}>Confirm password</label>
            <input id="tp-confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" placeholder="••••••••" style={inputStyle} />
          </>
        )}

        {error && <div style={errorBox}>{error}</div>}
        {notice && <div style={{ ...noticeBox, marginBottom: 12 }}>{notice}</div>}

        <button
          type="submit"
          disabled={submitting}
          style={{
            width: '100%', border: 'none', borderRadius: 10, background: submitting ? '#c1568f' : MAGENTA,
            color: '#fff', padding: '12px 16px', fontSize: 14, fontWeight: 600, fontFamily: 'inherit',
            cursor: submitting ? 'default' : 'pointer',
          }}
        >
          {submitting ? 'One moment…' : isSignup ? 'Create account & continue' : 'Sign in & continue'}
        </button>
      </form>

      <p style={{ margin: '12px 0 0', fontSize: 11.5, color: '#94a3b8', textAlign: 'center', lineHeight: 1.5 }}>
        Step 1 of 2. Next you’ll enter payment. No charge until you confirm.
      </p>
    </div>
  );
}

// ------------------------------------------------------------------------
// Step 2: payment (embedded Stripe Payment Element).
// ------------------------------------------------------------------------
function PaymentForm({ billingInterval, onSuccess, renewalNote }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [succeeded, setSucceeded] = useState(false);
  const successHandledRef = useRef(false);

  const markSucceeded = (delay = 600) => {
    if (successHandledRef.current) return;
    successHandledRef.current = true;
    setSucceeded(true);
    setTimeout(() => onSuccess?.(), delay);
  };

  // Wait for the webhook to flip the plan to Essential before declaring success.
  const pollActivation = async () => {
    for (let attempt = 0; attempt < 14; attempt += 1) {
      if (attempt > 0) await new Promise((r) => setTimeout(r, 1500));
      try {
        const resp = await authFetch(`${API_BASE}/api/v1/billing/status`, { credentials: 'include' });
        const data = await resp.json().catch(() => ({}));
        const plan = String(data?.plan_key || data?.subscription_plan || '').trim().toLowerCase();
        const status = String(data?.subscription_status || '').trim().toLowerCase();
        if (resp.ok && plan === 'essential' && (status === 'active' || status === 'trialing' || data?.stripe_subscription_id)) {
          return true;
        }
      } catch (_) {
        // Webhook reconciliation can lag a moment; keep waiting.
      }
    }
    return false;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!stripe || !elements || submitting) return;
    setSubmitting(true);
    setError('');

    const confirmPromise = stripe.confirmPayment({
      elements,
      redirect: 'if_required',
      confirmParams: { return_url: window.location.href },
    });
    const statusPromise = pollActivation().then((ok) => (ok ? { activatedByStatus: true } : null));
    const result = await Promise.race([confirmPromise, statusPromise]);

    if (result?.activatedByStatus) {
      markSucceeded(600);
      return;
    }

    const { error: confirmError, paymentIntent } = result || {};
    if (confirmError) {
      if (await pollActivation()) {
        markSucceeded(600);
        return;
      }
      setError(confirmError.message || 'Your payment could not be completed.');
      setSubmitting(false);
      return;
    }
    if (paymentIntent && (paymentIntent.status === 'succeeded' || paymentIntent.status === 'processing')) {
      markSucceeded(600);
      return;
    }
    if (await pollActivation()) {
      markSucceeded(600);
      return;
    }
    setError('Payment did not complete. Please try again.');
    setSubmitting(false);
  };

  if (succeeded) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 8px' }}>
        <div style={{ width: 48, height: 48, borderRadius: '50%', background: '#ecfdf3', color: '#0d7a3e', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 12px', fontSize: 24 }}>✓</div>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#0f172a' }}>You&rsquo;re in.</div>
        <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
          Essential is active and your {FOUNDER_CREDITS} Thinking Power credits are on the way.
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <PaymentElement options={{ layout: 'tabs' }} />
      {error && <div style={{ ...errorBox, marginTop: 12 }}>{error}</div>}
      <div style={{ marginTop: 14, fontSize: 11.5, color: '#64748b', lineHeight: 1.5 }}>
        You&rsquo;re charged ${FOUNDER_PRICE} today for the Founder offer and you&rsquo;re enrolling in Essential.
        Your first month is included. You accept {billingInterval === 'annual' ? 'annual' : 'monthly'} recurring
        billing at checkout; {renewalNote.toLowerCase()}. Essential renews until you cancel.
      </div>
      <button
        type="submit"
        disabled={!stripe || submitting}
        style={{
          marginTop: 16, width: '100%', border: 'none', borderRadius: 10,
          background: submitting ? '#c1568f' : MAGENTA, color: '#fff',
          padding: '12px 16px', fontSize: 14, fontWeight: 600,
          cursor: submitting || !stripe ? 'default' : 'pointer',
        }}
      >
        {submitting ? 'Confirming payment…' : `Pay $${FOUNDER_PRICE} and claim ${FOUNDER_CREDITS}`}
      </button>
      <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8', textAlign: 'center' }}>
        Secure payment processing. Cancel anytime.
      </div>
    </form>
  );
}

function PaymentStep({ onSuccess }) {
  const [billingInterval, setBillingInterval] = useState('monthly');
  const [clientSecret, setClientSecret] = useState('');
  const [stripePromise, setStripePromise] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [intervals, setIntervals] = useState(fallbackIntervals);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/v1/billing/catalog`, { credentials: 'include' });
        const data = await resp.json().catch(() => ({}));
        const plans = data?.plans || data?.catalog || data;
        const essential = plans?.essential || {};
        const monthly = Number(essential.monthly_price_usd);
        const annualMonthly = Number(essential.annual_monthly_price_usd);
        if (!alive) return;
        setIntervals([
          {
            key: 'monthly',
            label: 'Monthly',
            note: Number.isFinite(monthly)
              ? `$${monthly}/month after the included month`
              : fallbackIntervals[0].note,
          },
          {
            key: 'annual',
            label: 'Annual',
            note: Number.isFinite(annualMonthly)
              ? `$${annualMonthly}/month equivalent, billed annually after the included month`
              : fallbackIntervals[1].note,
          },
        ]);
      } catch (_) {
        // Checkout remains usable with a non-numeric renewal disclosure.
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    setClientSecret('');
    setLoadError('');
    (async () => {
      try {
        const resp = await authFetch(`${API_BASE}/api/v1/billing/create-thinking-power-checkout`, {
          method: 'POST',
          headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
          credentials: 'include',
          body: JSON.stringify({ billing_interval: billingInterval }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data?.msg || 'Could not start checkout.');
        if (!alive) return;
        if (!data.client_secret) throw new Error('Payment could not be initialized.');
        if (!data.publishable_key) throw new Error('Payments are not configured yet.');
        setClientSecret(data.client_secret);
        setStripePromise((prev) => prev || loadStripe(data.publishable_key));
      } catch (e) {
        if (alive) setLoadError(String(e?.message || e));
      }
    })();
    return () => { alive = false; };
  }, [billingInterval]);

  return (
    <div>
      {/* Essential is the plan; the customer only picks how it recurs. */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#94a3b8', marginBottom: 8 }}>
          Essential renews
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {intervals.map((opt) => {
            const active = opt.key === billingInterval;
            return (
              <button
                key={opt.key}
                type="button"
                onClick={() => setBillingInterval(opt.key)}
                style={{
                  flex: 1, textAlign: 'left', borderRadius: 10, padding: '10px 12px', cursor: 'pointer', fontFamily: 'inherit',
                  border: `1px solid ${active ? MAGENTA : '#e6eaf2'}`,
                  background: active ? `${MAGENTA}0d` : '#fff',
                  boxShadow: active ? `0 0 0 1px ${MAGENTA}` : 'none',
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{opt.label}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 1 }}>{opt.note}</div>
              </button>
            );
          })}
        </div>
      </div>

      {loadError ? (
        <div style={errorBox}>{loadError}</div>
      ) : (clientSecret && stripePromise) ? (
        <Elements key={clientSecret} stripe={stripePromise} options={{ clientSecret, appearance: APPEARANCE }}>
          <PaymentForm
            billingInterval={billingInterval}
            renewalNote={intervals.find((option) => option.key === billingInterval)?.note || fallbackIntervals[0].note}
            onSuccess={onSuccess}
          />
        </Elements>
      ) : (
        <div style={{ padding: '32px 0', textAlign: 'center', color: '#64748b', fontSize: 13 }}>Loading secure checkout…</div>
      )}
    </div>
  );
}

export default function ThinkingPowerCheckout({ onSuccess, onClose, returnPath = '/thinking-power' }) {
  const { user } = useAuth();

  const headerSub = user
    ? 'First month of Essential free, then it renews after month one.'
    : 'Create your account, then pay. The first month of Essential is free.';

  return (
    <div
      onClick={onClose}
      role="presentation"
      style={{ position: 'fixed', inset: 0, zIndex: 12000, background: 'rgba(15,23,42,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="founder-checkout-title"
        style={{ width: '100%', maxWidth: 500, background: '#fff', borderRadius: 16, boxShadow: '0 20px 60px rgba(15,23,42,0.25)', overflow: 'hidden', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}
      >
        <div style={{ background: NAVY, color: '#fff', padding: '18px 20px', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#cbd5e1', fontWeight: 600 }}>
              Jaspen Founder offer
            </div>
            <div id="founder-checkout-title" style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>${FOUNDER_PRICE} today · Essential included</div>
            <div style={{ fontSize: 13, color: '#cbd5e1', marginTop: 2 }}>{headerSub}</div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ border: 'none', background: 'transparent', color: '#cbd5e1', fontSize: 20, cursor: 'pointer', lineHeight: 1, padding: 2 }}>×</button>
        </div>

        <div style={{ padding: 20, overflowY: 'auto' }}>
          {user ? <PaymentStep onSuccess={onSuccess} /> : <AccountStep returnPath={returnPath} />}
        </div>
      </div>
    </div>
  );
}
