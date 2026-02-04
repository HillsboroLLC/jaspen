// path: src/pages/PaymentPage/PaymentPage.jsx
import React, { useState, useMemo } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import axios from 'axios';
import './PaymentPage.css';

// WHY: Allow configurable backend base; safe default to same-origin proxy.
const API_BASE =
  (process.env.REACT_APP_API_BASE && process.env.REACT_APP_API_BASE.trim()) || '/api';

// SAFE: Only construct Stripe when a key exists (avoids runtime crash).
const STRIPE_PK = process.env.REACT_APP_STRIPE_PUBLIC_KEY || '';

const PLAN_INFO = {
  essential:            { label: 'Essential',            price: '$39.99/month' },
  growth:               { label: 'Growth',               price: '$99.99/month' },
  transform_standard:   { label: 'Transform Standard',   price: '$15,000/month' },
  transform_premium:    { label: 'Transform Premium',    price: '$25,000/month' },
  transform_enterprise: { label: 'Transform Enterprise', price: '$50,000/month' },
  founder:              { label: 'Founder',              price: '2,999/ONE TIME' },
};

export default function PaymentPage() {
  const stripePromise = useMemo(() => {
    if (!STRIPE_PK) return null; // WHY: prevent loadStripe('') which can blow up
    return loadStripe(STRIPE_PK);
  }, []);

  const planKey = new URLSearchParams(window.location.search).get('plan') || 'essential';
  const plan = PLAN_INFO[planKey] || PLAN_INFO.essential;

  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const handleCheckout = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await axios.post(`${API_BASE}/billing/create-checkout-session`, { plan: planKey });
      const stripe = await stripePromise;
      if (!stripe) throw new Error('Stripe.js failed to load (missing public key).');
      const { error: stripeErr } = await stripe.redirectToCheckout({ sessionId: data.sessionId });
      if (stripeErr) throw stripeErr;
    } catch (err) {
      // WHY: surface backend error message when available
      const msg =
        err?.response?.data?.message ||
        err?.message ||
        'Oops—something went wrong. Please try again.';
      setError(msg);
      setLoading(false);
    }
  };

  // Friendly notice instead of crashing the whole app
  if (!STRIPE_PK) {
    return (
      <div className="payment-page">
        <h2>{plan.label}</h2>
        <p className="price">{plan.price}</p>
        <p style={{ color: 'red' }}>
          Payments are temporarily unavailable. Missing{' '}
          <code>REACT_APP_STRIPE_PUBLIC_KEY</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="payment-page">
      <h2>Subscribe to {plan.label}</h2>
      <p className="price">{plan.price}</p>

      {error && <p className="error">{error}</p>}

      <button
        className="checkout-button"
        onClick={handleCheckout}
        disabled={loading}
      >
        {loading ? 'Redirecting…' : `Start ${plan.label}`}
      </button>
    </div>
  );
}
