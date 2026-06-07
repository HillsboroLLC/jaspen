import React, { useEffect, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { Elements, PaymentElement, useStripe, useElements } from '@stripe/react-stripe-js';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';

// Embedded Stripe flows — the user pays / saves a card IN OUR UI and never leaves the
// site. Two modes:
//   mode="subscribe"       → create-subscription, confirmPayment (PaymentIntent)
//   mode="credit_pack"     → create-credit-pack-payment-intent, confirmPayment
//   mode="update_payment"  → create-setup-intent, confirmSetup (SetupIntent) + set default
// Branded via Stripe's Appearance API to match Jaspen.
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

function CheckoutForm({ mode, planLabel, packLabel, priceLabel, onSuccess }) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [succeeded, setSucceeded] = useState(false);
  const isUpdate = mode === 'update_payment';
  const isCreditPack = mode === 'credit_pack';

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!stripe || !elements || submitting) return;
    setSubmitting(true);
    setError('');

    if (isUpdate) {
      const { error: setupError, setupIntent } = await stripe.confirmSetup({
        elements,
        redirect: 'if_required',
        confirmParams: { return_url: window.location.href },
      });
      if (setupError) {
        setError(setupError.message || 'Your card could not be saved.');
        setSubmitting(false);
        return;
      }
      const pmId = setupIntent?.payment_method;
      if (pmId) {
        try {
          await authFetch(`${API_BASE}/api/v1/billing/set-default-payment-method`, {
            method: 'POST',
            headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
            credentials: 'include',
            body: JSON.stringify({ payment_method_id: pmId }),
          });
        } catch (_) { /* best-effort; webhook can reconcile */ }
      }
      setSucceeded(true);
      setTimeout(() => onSuccess?.(), 500);
      return;
    }

    // Subscribe and credit-pack modes both confirm a PaymentIntent in-page.
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
      if (isCreditPack && paymentIntent.status === 'succeeded') {
        try {
          const resp = await authFetch(`${API_BASE}/api/v1/billing/confirm-credit-pack-payment`, {
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
      }
      setSucceeded(true);
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
        <div style={{ fontSize: 16, fontWeight: 600, color: '#0f172a' }}>
          {isUpdate ? 'Card saved' : isCreditPack ? 'Credit pack purchased' : `You're on ${planLabel}`}
        </div>
        <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
          {isUpdate
            ? 'Your default payment method is updated.'
            : isCreditPack
              ? `${packLabel || 'Your credits'} are ready.`
              : 'Finalizing your account...'}
        </div>
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
      {!isUpdate && !isCreditPack && (
        <div style={{ marginTop: 14, fontSize: 11.5, color: '#64748b', lineHeight: 1.5 }}>
          By subscribing, you agree to be charged {priceLabel} now and on a recurring monthly
          basis until you cancel. You can cancel anytime in your account settings.
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
        {submitting ? 'Processing...' : isUpdate ? 'Save card' : isCreditPack ? `Purchase - ${priceLabel}` : `Subscribe - ${priceLabel}`}
      </button>
      <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8', textAlign: 'center' }}>
        Secure payment processing.{!isUpdate && !isCreditPack && ' Cancel anytime.'}
      </div>
    </form>
  );
}

export default function StripeCheckout({ mode = 'subscribe', planKey, planLabel, packKey, packLabel, priceLabel, plans = [], onSuccess, onClose }) {
  const isUpdate = mode === 'update_payment';
  const isCreditPack = mode === 'credit_pack';
  const [selectedPlanKey, setSelectedPlanKey] = useState(planKey);
  const [clientSecret, setClientSecret] = useState('');
  const [stripePromise, setStripePromise] = useState(null);
  const [loadError, setLoadError] = useState('');

  const selectedPlan = plans.find((p) => p.key === selectedPlanKey);
  const effLabel = isCreditPack ? (packLabel || 'Credit pack') : (selectedPlan?.label || planLabel);
  const effPrice = isCreditPack ? priceLabel : (selectedPlan?.priceLabel || priceLabel);
  const showSwitcher = !isUpdate && !isCreditPack && plans.length > 1;

  useEffect(() => {
    let alive = true;
    setClientSecret(''); // show loading while (re)initializing for the chosen plan
    setLoadError('');
    (async () => {
      try {
        const endpoint = isUpdate
          ? 'create-setup-intent'
          : isCreditPack
            ? 'create-credit-pack-payment-intent'
            : 'create-subscription';
        const body = isUpdate ? {} : isCreditPack ? { pack_key: packKey } : { plan_key: selectedPlanKey };
        const resp = await authFetch(`${API_BASE}/api/v1/billing/${endpoint}`, {
          method: 'POST',
          headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
          credentials: 'include',
          body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data?.msg || 'Could not start.');
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
  }, [selectedPlanKey, isUpdate, isCreditPack, packKey]);

  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(15,23,42,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: '100%', maxWidth: 500, background: '#fff', borderRadius: 16, boxShadow: '0 20px 60px rgba(15,23,42,0.25)', overflow: 'hidden', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}
      >
        <div style={{ background: NAVY, color: '#fff', padding: '18px 20px', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#cbd5e1', fontWeight: 600 }}>
              {isUpdate ? 'Payment method' : isCreditPack ? 'Credit pack' : 'Subscribe'}
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>
              {isUpdate ? 'Update your card' : isCreditPack ? effLabel : `${effLabel} plan`}
            </div>
            {!isUpdate && effPrice && (
              <div style={{ fontSize: 13, color: '#cbd5e1', marginTop: 2 }}>
                {isCreditPack ? `${effPrice} one-time purchase` : `${effPrice} · billed monthly · cancel anytime`}
              </div>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" style={{ border: 'none', background: 'transparent', color: '#cbd5e1', fontSize: 20, cursor: 'pointer', lineHeight: 1, padding: 2 }}>×</button>
        </div>

        <div style={{ padding: 20, overflowY: 'auto' }}>
          {/* Inline plan switcher — change plan without closing the modal */}
          {showSwitcher && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: '#94a3b8', marginBottom: 8 }}>Plan</div>
              <div style={{ display: 'flex', gap: 8 }}>
                {plans.map((p) => {
                  const active = p.key === selectedPlanKey;
                  return (
                    <button
                      key={p.key}
                      type="button"
                      onClick={() => { if (p.key !== selectedPlanKey) setSelectedPlanKey(p.key); }}
                      style={{
                        flex: 1, textAlign: 'left', borderRadius: 10, padding: '10px 12px', cursor: 'pointer',
                        border: `1px solid ${active ? MAGENTA : '#e6eaf2'}`,
                        background: active ? `${MAGENTA}0d` : '#fff',
                        boxShadow: active ? `0 0 0 1px ${MAGENTA}` : 'none',
                      }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{p.label}</div>
                      <div style={{ fontSize: 12, color: '#64748b', marginTop: 1 }}>{p.priceLabel}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {loadError ? (
            <div style={{ fontSize: 13, color: '#dc2626', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '10px 12px' }}>
              {loadError}
            </div>
          ) : (clientSecret && stripePromise) ? (
            // key forces a clean Elements remount when the plan (clientSecret) changes.
            <Elements key={clientSecret} stripe={stripePromise} options={{ clientSecret, appearance: APPEARANCE }}>
              <CheckoutForm mode={mode} planLabel={effLabel} packLabel={packLabel} priceLabel={effPrice} onSuccess={onSuccess} />
            </Elements>
          ) : (
            <div style={{ padding: '32px 0', textAlign: 'center', color: '#64748b', fontSize: 13 }}>Loading secure checkout…</div>
          )}
        </div>
      </div>
    </div>
  );
}
