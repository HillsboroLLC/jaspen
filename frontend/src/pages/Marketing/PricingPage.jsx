import React, { useEffect, useMemo, useRef, useState } from 'react';
import MarketingPageLayout from './MarketingPageLayout';
import { API_BASE } from '../../config/apiBase';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import Seo from '../../shared/components/Seo';
import { PLAN_ORDER, PLAN_RANK } from '../../shared/constants/appConstants';

const FALLBACK_PLANS = [
  {
    plan_key: 'free',
    label: 'Free',
    price: '$0',
    detail: 'Test Jaspen on a real decision · 300 credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'starter',
    label: 'Starter',
    price: '$7 / month',
    detail: 'Light personal use when you need more room than Free · 1,000 credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'essential',
    label: 'Essential',
    price: '$39 / month',
    detail: 'Turn ideas into clear decisions and walk away with execution plans · 7,000 credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'team',
    label: 'Team',
    price: '$129 / month',
    detail: 'Align your team, pressure-test decisions, and execute with clarity · 29,000 shared credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'enterprise',
    label: 'Enterprise',
    price: '$299 / month+',
    detail: 'Bring structure, speed, and consistency to how your business operates · 80,000 shared credits/month.',
    sales_only: false,
  },
];

const FALLBACK_PACKS = [
  { pack_key: 'credits_3000', label: '3,000 credits', price_usd: 10, credits: 3000 },
  { pack_key: 'credits_8000', label: '8,000 credits', price_usd: 25, credits: 8000 },
  { pack_key: 'credits_18000', label: '18,000 credits', price_usd: 50, credits: 18000 },
];

const FALLBACK_MODEL_TYPES = {
  pluto: {
    model_type: 'pluto',
    label: 'Pluto',
    version: '1.0',
    description: 'Fastest model for core intake and scorecard workflows.',
    min_plan: 'free',
  },
  orbit: {
    model_type: 'orbit',
    label: 'Orbit',
    version: '1.0',
    description: 'Balanced depth and speed for broader cross-functional synthesis.',
    min_plan: 'free',
  },
  titan: {
    model_type: 'titan',
    label: 'Titan',
    version: '1.0',
    description: 'Highest-depth reasoning for complex multi-team initiatives.',
    min_plan: 'free',
  },
};

const MODEL_ORDER = ['pluto', 'orbit', 'titan'];

export default function PricingPage() {
  const { user, loading } = useAuth();
  const [plans, setPlans] = useState(FALLBACK_PLANS);
  const [packs, setPacks] = useState(FALLBACK_PACKS);
  const [modelTypes, setModelTypes] = useState(FALLBACK_MODEL_TYPES);
  const [pendingKey, setPendingKey] = useState('');
  const [statusMessage, setStatusMessage] = useState('');
  const autoCheckoutFiredRef = useRef(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/billing/catalog`)
      .then((res) => res.json())
      .then((data) => {
        if (data?.plans) {
          const ordered = PLAN_ORDER
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

        const packCatalog = data?.credit_packs || data?.overage_packs;
        if (packCatalog) {
          const orderedPacks = ['credits_3000', 'credits_8000', 'credits_18000', 'pack_1000', 'pack_5000', 'pack_20000']
            .map((key) => packCatalog[key])
            .filter(Boolean);
          if (orderedPacks.length) setPacks(orderedPacks);
        }

        if (data?.model_types) {
          setModelTypes(data.model_types);
        }
      })
      .catch(() => {
        // Keep fallback content if catalog fetch fails.
      });
  }, []);

  // Auto-start checkout if user arrived with ?plan=essential (frictionless flow)
  useEffect(() => {
    if (loading || !user || autoCheckoutFiredRef.current) return;
    const params = new URLSearchParams(window.location.search || '');
    const planParam = (params.get('plan') || params.get('plan_key') || '').trim().toLowerCase();
    if (!planParam || planParam === 'free') return;
    autoCheckoutFiredRef.current = true;
    // Remove the param from the URL so a refresh doesn't re-trigger
    params.delete('plan');
    params.delete('plan_key');
    const newSearch = params.toString();
    window.history.replaceState(
      {},
      document.title,
      `${window.location.pathname}${newSearch ? `?${newSearch}` : ''}#plans`,
    );
    // Small delay so the page renders before redirecting to Stripe
    setTimeout(() => beginCheckout(planParam), 400);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, user]);

  const planByKey = useMemo(
    () => plans.reduce((acc, plan) => ({ ...acc, [plan.plan_key]: plan }), {}),
    [plans]
  );
  const planOrder = useMemo(
    () => PLAN_ORDER.filter((key) => Boolean(planByKey[key])),
    [planByKey]
  );
  const orderedModelTypes = useMemo(
    () => MODEL_ORDER.map((key) => modelTypes?.[key]).filter(Boolean),
    [modelTypes]
  );
  const isLoggedIn = !!user;
  const formatModelDisplayName = (model) => {
    const label = model?.label || model?.model_type || 'Model';
    const version = String(model?.version || '1.0').trim();
    return `${label}-${version}`;
  };

  const isModelAvailableForPlan = (minPlan, planKey) => {
    const requiredRank = PLAN_RANK[String(minPlan || 'free').toLowerCase()] ?? 0;
    const planRank = PLAN_RANK[String(planKey || 'free').toLowerCase()] ?? 0;
    return planRank >= requiredRank;
  };

  const beginCheckout = async (planKey) => {
    if (!user) {
      window.location.href = '/?auth=1';
      return;
    }

    setPendingKey(planKey);
    setStatusMessage('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/billing/create-checkout-session`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
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

  const buyCreditPack = async (packKey) => {
    if (!user) {
      window.location.href = '/?auth=1';
      return;
    }

    setPendingKey(packKey);
    setStatusMessage('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/billing/create-credit-pack-checkout-session`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        body: JSON.stringify({ pack_key: packKey }),
      });

      const data = await response.json();
      if (!response.ok || !data?.url) {
        throw new Error(data?.msg || 'Unable to open credit pack checkout.');
      }

      window.location.href = data.url;
    } catch (err) {
      setStatusMessage(err.message || 'Unable to open credit pack checkout.');
    } finally {
      setPendingKey('');
    }
  };

  const openPortal = async () => {
    if (!user) {
      window.location.href = '/?auth=1';
      return;
    }

    setPendingKey('portal');
    setStatusMessage('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/billing/create-portal-session`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        body: JSON.stringify({ return_url: `${window.location.origin}/pages/pricing#plans` }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        throw new Error(data?.msg || 'Unable to open billing settings.');
      }
      window.location.href = data.url;
    } catch (err) {
      setStatusMessage(err.message || 'Unable to open billing settings.');
    } finally {
      setPendingKey('');
    }
  };

  return (
    <MarketingPageLayout pageClass="page-pricing">
      <Seo
        title="Pricing"
        description="Explore Jaspen pricing from Free and Starter to Essential, Team, and Enterprise plans."
        canonicalPath="/pages/pricing"
      />
      <section className="page-hero page-hero-pricing">
        <div className="hero-copy">
          <p className="hero-kicker">Pricing</p>
          <h1>Clear pricing from individual use to enterprise rollout</h1>
          <p>
            Start free, move to Starter at $7/month, upgrade to Essential at $39/month, and scale with Team or Enterprise.
            Need more usage? Add thinking power credit packs as needed.
          </p>
        </div>
        <div className="hero-abstract pricing-abstract">
          <div className="floating-price">Free 300 credits</div>
          <div className="floating-price">Starter 1,000 credits</div>
          <div className="floating-price">Essential 7,000 credits</div>
          <div className="floating-price">Team 29,000 shared</div>
          <div className="floating-price">Enterprise 80,000 shared</div>
        </div>
      </section>

      <section id="overview" className="marketing-section">
        <h2>Overview</h2>
        <div className="pricing-overview-split">
          <article className="marketing-card pricing-highlight">
            <h3>Structured for modern AI-agent adoption</h3>
            <p>
              Free lets users test a real decision. Starter supports light personal use at $7/month. Essential supports everyday use at $39/month. Team and Enterprise add
              pooled thinking power, governance, and rollout control.
            </p>
          </article>
          <article className="marketing-card pricing-summary">
            <h3>Usage policy</h3>
            <ul className="pricing-checks">
              <li>Free: 300 credits/month</li>
              <li>Starter: 1,000 credits/month</li>
              <li>Essential: 7,000 credits/month</li>
              <li>Team: 29,000 shared credits/month + seat pricing</li>
              <li>Enterprise: 80,000 shared credits/month + seat pricing</li>
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
              <article key={plan.plan_key} id={plan.plan_key} className={`marketing-card pricing-plan-card ${isEssential ? 'is-featured' : ''}`}>
                <div className="pricing-plan-head">
                  <h3>{plan.label}</h3>
                  <span className="plan-price">{plan.price}</span>
                </div>
                <p>{plan.detail}</p>
                {plan.sales_only ? (
                  <a className="pricing-cta-link" href="/pages/pricing#plans">Talk to sales</a>
                ) : !isLoggedIn ? (
                  <a
                    className="pricing-cta-button"
                    href="/?auth=1"
                  >
                    {isFree ? 'Sign up' : 'Start free'}
                  </a>
                ) : (
                  <button
                    type="button"
                    className="pricing-cta-button"
                    onClick={() => beginCheckout(plan.plan_key)}
                    disabled={loading} aria-disabled={loading}
                  >
                    {loading
                      ? 'Redirecting...'
                      : isFree
                      ? 'Stay on Free'
                      : `Get ${plan.label}`}
                  </button>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section id="model-access" className="marketing-section">
        <h2>Model access by plan</h2>
        <p className="pricing-pack-copy">
          Access is plan-gated by model depth. You can switch models from the chat composer.
        </p>
        <div className="pricing-model-table-wrap">
          <table className="pricing-model-table">
            <thead>
              <tr>
                <th scope="col">Model</th>
                {planOrder.map((planKey) => (
                  <th scope="col" key={planKey}>{planByKey[planKey]?.label || planKey}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orderedModelTypes.map((model) => (
                <tr key={model.model_type || model.label}>
                  <th scope="row">
                    <div className="pricing-model-name">{formatModelDisplayName(model)}</div>
                    <div className="pricing-model-desc">{model.description || ''}</div>
                  </th>
                  {planOrder.map((planKey) => (
                    <td key={`${model.model_type}-${planKey}`}>
                      {isModelAvailableForPlan(model.min_plan, planKey) ? 'Included' : 'Upgrade'}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section id="api" className="marketing-section">
        <h2>One-time credit packs</h2>
        {isLoggedIn ? (
          <>
            <p className="pricing-pack-copy">
              Add thinking power without changing plan tier.
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
                    <p>{(pack.credits || 0).toLocaleString()} one-time credits added to this cycle.</p>
                    <button
                      type="button"
                      className="pricing-cta-button"
                      onClick={() => buyCreditPack(pack.pack_key)}
                      disabled={loading} aria-disabled={loading}
                    >
                      {loading ? 'Redirecting...' : 'Buy credit pack'}
                    </button>
                  </article>
                );
              })}
            </div>
          </>
        ) : (
          <p className="pricing-pack-copy">Credit packs are available after sign-in, inside Account settings.</p>
        )}
      </section>

      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Manage subscription</h3>
          <p>
            Update payment methods, manage Essential, or cancel at period end from your billing settings.
          </p>
          {isLoggedIn ? (
            <button type="button" className="pricing-portal-button" onClick={openPortal} disabled={pendingKey === 'portal'} aria-disabled={pendingKey === 'portal'}>
              {pendingKey === 'portal' ? 'Opening...' : 'Manage billing'}
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
            <div className="pricing-node">{planByKey.starter?.label || 'Starter'}</div>
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
              Start free, move to Starter ($7/month) for light use, upgrade to Essential ($39/month) as volume grows, then move to Team or Enterprise when
              governance, shared thinking power, and cross-functional deployment become the priority.
            </p>
          </article>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
