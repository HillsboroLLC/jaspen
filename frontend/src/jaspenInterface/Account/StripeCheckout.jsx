import React, { useEffect, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { Elements, PaymentElement, useStripe, useElements } from '@stripe/react-stripe-js';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';

// Embedded Stripe checkout — the user pays with the Payment Element IN OUR UI and
// never leaves the site. Branded via Stripe's Appearance API to match Jaspen.
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

function CheckoutForm({ planLabel, priceLabel, onSuccess }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [succeeded, setSucceeded] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!stripe || !elements || submitting) return;
    setSubmitting(true);
    setError('');
    // redirect: 'if_required' keeps the user in-page for card payments; only
    // methods that genuinely require a redirect (rare) would navigate away.
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
      setSucceeded(true);
      // The webhook activates the plan server-side; give the caller a beat to refresh.
      setTimeout(() => onSuccess?.(), 600);
      return;
    }
    setError('Payment did not complete. Please try again.');
    setSubmitting(false);
  };

  if (succeeded) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 8px' }}>
        <div style={{ width: 48, height: 48, borderRadius: '50%', background: '#ecfdf3', color: '#0d7a3e', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 12px', fontSize: 24 }}>✓</div>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#0f172a' }}>You're on {planLabel}</div>
        <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>Finalizing your account…</div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <PaymentElement options={{ layout: 'tabs' }} />
      {error && (
        <div style={{ marginTop: 12, fontSize: 13, color: '#dc2626', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '8px 10px' }}>
          {error}
        </div>
      )}
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
        {submitting ? 'Processing…' : `Subscribe — ${priceLabel}`}
      </button>
      <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8', textAlign: 'center' }}>
        🔒 Payments are securely processed by Stripe. Cancel anytime.
      </div>
    </form>
  );
}

export default function StripeCheckout({ planKey, planLabel, priceLabel, onSuccess, onClose }) {
  const [clientSecret, setClientSecret] = useState('');
  const [stripePromise, setStripePromise] = useState(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await authFetch(`${API_BASE}/api/v1/billing/create-subscription`, {
          method: 'POST',
          headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
          credentials: 'include',
          body: JSON.stringify({ plan_key: planKey }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data?.msg || 'Could not start checkout.');
        if (!alive) return;
        if (!data.client_secret) throw new Error('Payment could not be initialized.');
        if (!data.publishable_key) throw new Error('Payments are not configured yet.');
        setClientSecret(data.client_secret);
        setStripePromise(loadStripe(data.publishable_key));
      } catch (e) {
        if (alive) setLoadError(String(e?.message || e));
      }
    })();
    return () => { alive = false; };
  }, [planKey]);

  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(15,23,42,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: '100%', maxWidth: 460, background: '#fff', borderRadius: 16, boxShadow: '0 20px 60px rgba(15,23,42,0.25)', overflow: 'hidden' }}
      >
        {/* Branded header */}
        <div style={{ background: NAVY, color: '#fff', padding: '18px 20px', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#cbd5e1', fontWeight: 600 }}>Subscribe</div>
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>{planLabel} plan</div>
            {priceLabel && <div style={{ fontSize: 13, color: '#cbd5e1', marginTop: 2 }}>{priceLabel}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ border: 'none', background: 'transparent', color: '#cbd5e1', fontSize: 20, cursor: 'pointer', lineHeight: 1, padding: 2 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ padding: 20 }}>
          {loadError ? (
            <div style={{ fontSize: 13, color: '#dc2626', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '10px 12px' }}>
              {loadError}
            </div>
          ) : (clientSecret && stripePromise) ? (
            <Elements stripe={stripePromise} options={{ clientSecret, appearance: APPEARANCE }}>
              <CheckoutForm planLabel={planLabel} priceLabel={priceLabel} onSuccess={onSuccess} />
            </Elements>
          ) : (
            <div style={{ padding: '32px 0', textAlign: 'center', color: '#64748b', fontSize: 13 }}>Loading secure checkout…</div>
          )}
        </div>
      </div>
    </div>
  );
}
