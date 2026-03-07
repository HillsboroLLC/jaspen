import React, { useEffect, useMemo, useState } from 'react';
import MarketingPageLayout from './MarketingPageLayout';
import { API_BASE } from '../../config/apiBase';
import { useAuth } from '../../shared/auth/AuthContext';

const FALLBACK_PLANS = [
  {
    plan_key: 'free',
    label: 'Free',
    price: '$0',
    detail: '300 credits/month for individual exploration and light usage.',
    sales_only: false,
  },
  {
    plan_key: 'essential',
    label: 'Essential',
    price: '$20 / month',
    detail: '3,000 credits/month for individual daily execution workflows.',
    sales_only: false,
  },
  {
    plan_key: 'team',
    label: 'Team',
    price: 'Contact sales',
    detail: 'Sales-led pooled usage for cross-functional teams.',
    sales_only: true,
  },
  {
    plan_key: 'enterprise',
    label: 'Enterprise',
    price: 'Custom',
    detail: 'Sales-led deployment with governance, security, and rollout support.',
    sales_only: true,
  },
];

const FALLBACK_PACKS = [
  { pack_key: 'pack_1000', label: '1,000 credits', price_usd: 12, credits: 1000 },
  { pack_key: 'pack_5000', label: '5,000 credits', price_usd: 50, credits: 5000 },
  { pack_key: 'pack_20000', label: '20,000 credits', price_usd: 180, credits: 20000 },
];

function getToken() {
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}

export default function PricingPage() {
  const { user, loading } = useAuth();
  const [plans, setPlans] = useState(FALLBACK_PLANS);
  const [packs, setPacks] = useState(FALLBACK_PACKS);
  const [pendingKey, setPendingKey] = useState('');
  const [statusMessage, setStatusMessage] = useState('');

  useEffect(() => {
    fetch(`${API_BASE}/api/billing/catalog`)
      .then((res) => res.json())
      .then((data) => {
        if (data?.plans) {
          const ordered = ['free', 'essential', 'team', 'enterprise']
            .map((key) => data.plans[key])
            .filter(Boolean)
            .map((plan) => ({
              plan_key: plan.plan_key,
              label: plan.label,
              price:
                plan.monthly_price_usd === 0
                  ? '$0'
                  : Number.isFinite(plan.monthly_price_usd)
                  ? `$${plan.monthly_price_usd} / month`
                  : plan.sales_only
                  ? 'Contact sales'
                  : 'Custom',
              detail:
                plan.monthly_credits != null
                  ? `${plan.monthly_credits.toLocaleString()} credits/month. ${plan.description}`
                  : plan.description,
              sales_only: !!plan.sales_only,
            }));
          if (ordered.length) setPlans(ordered);
        }

        if (data?.overage_packs) {
          const orderedPacks = ['pack_1000', 'pack_5000', 'pack_20000']
            .map((key) => data.overage_packs[key])
            .filter(Boolean);
          if (orderedPacks.length) setPacks(orderedPacks);
        }
      })
      .catch(() => {
        // Keep fallback content if catalog fetch fails.
      });
  }, []);

  const planByKey = useMemo(
    () => plans.reduce((acc, plan) => ({ ...acc, [plan.plan_key]: plan }), {}),
    [plans]
  );
  const isLoggedIn = !!user;

  const beginCheckout = async (planKey) => {
    const token = getToken();
    if (!token) {
      window.location.href = '/?auth=1';
      return;
    }

    setPendingKey(planKey);
    setStatusMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ plan_key: planKey }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.msg || 'Unable to start checkout right now.');
      }

      if (data?.url) {
        window.location.href = data.url;
        return;
      }

      setStatusMessage('Plan updated successfully.');
    } catch (err) {
      setStatusMessage(err.message || 'Unable to start checkout right now.');
    } finally {
      setPendingKey('');
    }
  };

  const buyOveragePack = async (packKey) => {
    const token = getToken();
    if (!token) {
      window.location.href = '/?auth=1';
      return;
    }

    setPendingKey(packKey);
    setStatusMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-overage-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ pack_key: packKey }),
      });

      const data = await response.json();
      if (!response.ok || !data?.url) {
        throw new Error(data?.msg || 'Unable to open overage checkout.');
      }

      window.location.href = data.url;
    } catch (err) {
      setStatusMessage(err.message || 'Unable to open overage checkout.');
    } finally {
      setPendingKey('');
    }
  };

  const openPortal = async () => {
    const token = getToken();
    if (!token) {
      window.location.href = '/?auth=1';
      return;
    }

    setPendingKey('portal');
    setStatusMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-portal-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ return_url: `${window.location.origin}/pages/pricing#plans` }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        throw new Error(data?.msg || 'Unable to open billing portal.');
      }
      window.location.href = data.url;
    } catch (err) {
      setStatusMessage(err.message || 'Unable to open billing portal.');
    } finally {
      setPendingKey('');
    }
  };

  return (
    <MarketingPageLayout pageClass="page-pricing">
      <section className="page-hero page-hero-pricing">
        <div className="hero-copy">
          <p className="hero-kicker">Pricing</p>
          <h1>Clear pricing from individual use to enterprise rollout</h1>
          <p>
            Start free, upgrade to Essential at $20, and scale with Team or Enterprise through sales-led rollout.
            Need more usage? Add overage credit packs as needed.
          </p>
        </div>
        <div className="hero-abstract pricing-abstract">
          <div className="floating-price">Free 300 credits</div>
          <div className="floating-price">Essential 3,000 credits</div>
          <div className="floating-price">Team (Sales)</div>
          <div className="floating-price">Enterprise (Sales)</div>
        </div>
      </section>

      <section id="overview" className="marketing-section">
        <h2>Overview</h2>
        <div className="pricing-overview-split">
          <article className="marketing-card pricing-highlight">
            <h3>Structured for modern AI-agent adoption</h3>
            <p>
              Free gets users started. Essential supports everyday use at $20/month. Team and Enterprise are
              sales-led for pooled usage, governance, and rollout control.
            </p>
          </article>
          <article className="marketing-card pricing-summary">
            <h3>Usage policy</h3>
            <ul className="pricing-checks">
              <li>Free: 300 credits/month</li>
              <li>Essential: 3,000 credits/month</li>
              <li>Team and Enterprise: contract-based pooled usage</li>
              <li>Overage packs available now for self-serve growth</li>
            </ul>
          </article>
        </div>
      </section>

      <section id="plans" className="marketing-section">
        <h2>Plans</h2>
        {!loading && !isLoggedIn && (
          <p className="pricing-inline-status">
            Sign in to see your current plan and manage upgrades/downgrades from Settings or Account.
          </p>
        )}
        {statusMessage && <p className="pricing-inline-status">{statusMessage}</p>}
        <div className="plans-grid">
          {plans.map((plan) => {
            const isEssential = plan.plan_key === 'essential';
            const isFree = plan.plan_key === 'free';
            const loading = pendingKey === plan.plan_key;
            return (
              <article key={plan.plan_key} className={`marketing-card pricing-plan-card ${isEssential ? 'is-featured' : ''}`}>
                <div className="pricing-plan-head">
                  <h3>{plan.label}</h3>
                  <span className="plan-price">{plan.price}</span>
                </div>
                <p>{plan.detail}</p>
                {plan.sales_only ? (
                  <a className="pricing-cta-link" href="/login">Talk to sales</a>
                ) : !isLoggedIn ? (
                  <span className="pricing-cta-muted">Sign in to manage this plan</span>
                ) : (
                  <button
                    type="button"
                    className="pricing-cta-button"
                    onClick={() => beginCheckout(plan.plan_key)}
                    disabled={loading}
                  >
                    {loading
                      ? 'Redirecting...'
                      : isFree
                      ? 'Stay on Free'
                      : 'Upgrade to Essential'}
                  </button>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section id="api" className="marketing-section">
        <h2>Overage credit packs</h2>
        {isLoggedIn ? (
          <>
            <p className="pricing-pack-copy">
              For teams staying self-serve, add credits without changing plan tier.
            </p>
            <div className="plans-grid pricing-pack-grid">
              {packs.map((pack) => {
                const price = Number(pack.price_usd);
                const loading = pendingKey === pack.pack_key;
                return (
                  <article key={pack.pack_key} className="marketing-card pricing-plan-card pricing-pack-card">
                    <div className="pricing-plan-head">
                      <h3>{pack.label || `${pack.credits?.toLocaleString()} credits`}</h3>
                      <span className="plan-price">${Number.isFinite(price) ? price : pack.price_usd}</span>
                    </div>
                    <p>{(pack.credits || 0).toLocaleString()} one-time credits added to your balance.</p>
                    <button
                      type="button"
                      className="pricing-cta-button"
                      onClick={() => buyOveragePack(pack.pack_key)}
                      disabled={loading}
                    >
                      {loading ? 'Redirecting...' : 'Buy credit pack'}
                    </button>
                  </article>
                );
              })}
            </div>
          </>
        ) : (
          <p className="pricing-pack-copy">Overage packs are available after sign-in, inside Account settings.</p>
        )}
      </section>

      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Manage subscription</h3>
          <p>
            Use Stripe Customer Portal to update payment methods, manage Essential, or cancel at period end.
          </p>
          {isLoggedIn ? (
            <button type="button" className="pricing-portal-button" onClick={openPortal} disabled={pendingKey === 'portal'}>
              {pendingKey === 'portal' ? 'Opening...' : 'Open billing portal'}
            </button>
          ) : (
            <a href="/?auth=1" className="pricing-cta-link">Sign in to manage billing</a>
          )}
        </div>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-pricing">
          <div className="lydia-visual pricing-architecture">
            <div className="pricing-node">{planByKey.free?.label || 'Free'}</div>
            <div className="pricing-link"></div>
            <div className="pricing-node emphasized">{planByKey.essential?.label || 'Essential'}</div>
            <div className="pricing-link"></div>
            <div className="pricing-node">{planByKey.team?.label || 'Team'}</div>
            <div className="pricing-link"></div>
            <div className="pricing-node">{planByKey.enterprise?.label || 'Enterprise'}</div>
          </div>
          <article className="lydia-content">
            <h3>Upgrade path</h3>
            <p>
              Start with individual usage, move to Essential as volume grows, then shift to Team or Enterprise when
              governance and shared deployment requirements appear.
            </p>
          </article>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
