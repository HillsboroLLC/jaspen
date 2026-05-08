import React, { useEffect, useState } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './PricingResult.css';

export default function PricingResult() {
  const { search } = useLocation();
  const params    = new URLSearchParams(search);
  const status    = params.get('status');
  const sessionId = params.get('session_id');
  const [session, setSession] = useState(null);

  useEffect(() => {
    if (status === 'success' && sessionId) {
      fetch(`${API_BASE}/api/v1/billing/checkout-session?session_id=${sessionId}`)
        .then(res => res.json())
        .then(setSession)
        .catch(console.error);
    }
  }, [status, sessionId]);

  return (
    <div className="pricing-result">
      {status === 'success' ? (
        <div className="status success">
          <h1>🎉 Subscription Confirmed!</h1>
          {session ? (
            <>
              {session?.metadata?.checkout_type === 'overage_pack' ? (
                <p>
                  Credits added: <strong>{Number(session?.metadata?.credits || 0).toLocaleString()}</strong>
                </p>
              ) : (
                <p>
                  Your plan: <strong>{session?.metadata?.plan_key || 'essential'}</strong>
                </p>
              )}
              {session?.subscription?.current_period_end && (
                <p>
                  Next charge:{' '}
                  {new Date(session.subscription.current_period_end * 1000).toLocaleDateString()}
                </p>
              )}
            </>
          ) : (
            <p>Loading your subscription details…</p>
          )}
          <Link className="button" to="/dashboard">Go to Dashboard →</Link>
        </div>
      ) : (
        <div className="status cancel">
          <h1>Subscription Canceled</h1>
          <p>
            It looks like you canceled.{' '}
            <Link to="/pages/pricing">Try again →</Link>
          </p>
        </div>
      )}
    </div>
  );
}
