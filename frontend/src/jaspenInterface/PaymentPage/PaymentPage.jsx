import React, { useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import './PaymentPage.css';

const PLAN_INFO = {
  free: { label: 'Free', price: '$0' },
  essential: { label: 'Essential', price: '$20/month' },
  team: { label: 'Team', price: 'Sales-led' },
  enterprise: { label: 'Enterprise', price: 'Sales-led' },
};

export default function PaymentPage() {
  const planKey = new URLSearchParams(window.location.search).get('plan') || 'essential';
  const plan = PLAN_INFO[planKey] || PLAN_INFO.essential;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleCheckout = async () => {
    setLoading(true);
    setError(null);

    try {
      if (planKey === 'team' || planKey === 'enterprise') {
        window.location.href = '/login';
        return;
      }

      const response = await authFetch(`${API_BASE}/api/v1/billing/create-checkout-session`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        body: JSON.stringify({ plan_key: planKey }),
      });

      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401) {
          window.location.href = '/?auth=1';
          return;
        }
        throw new Error(data?.msg || 'Unable to start checkout.');
      }

      if (data?.url) {
        window.location.href = data.url;
        return;
      }

      window.location.href = '/dashboard';
    } catch (err) {
      setError(err?.message || 'Unable to start checkout.');
      setLoading(false);
    }
  };

  return (
    <div className="payment-page">
      <h2>{plan.label}</h2>
      <p className="price">{plan.price}</p>

      {error && <p className="error">{error}</p>}

      <button className="checkout-button" onClick={handleCheckout} disabled={loading}>
        {loading ? 'Redirecting...' : planKey === 'team' || planKey === 'enterprise' ? 'Contact Sales' : `Continue with ${plan.label}`}
      </button>
    </div>
  );
}
