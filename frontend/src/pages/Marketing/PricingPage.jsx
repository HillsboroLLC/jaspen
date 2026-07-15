import React, { useEffect, useRef, useState } from 'react';
import MarketingPageLayout from './MarketingPageLayout';
import { API_BASE } from '../../config/apiBase';
import { useAuth } from '../../shared/auth/AuthContext';
import Seo from '../../shared/components/Seo';
import { PLAN_ORDER } from '../../shared/constants/appConstants';

const FALLBACK_PLANS = [
  {
    plan_key: 'free',
    label: 'Free',
    price: '$0',
    detail: 'Try Jaspen on a real decision and see how structured thinking feels · 300 credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'starter',
    label: 'Starter',
    price: '$7 / month',
    detail: 'More room for personal decisions, early ideas, and occasional planning · 1,000 credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'essential',
    label: 'Essential',
    price: '$39 / month',
    detail: 'When the decision has real consequences, Essential is built for you · 7,000 credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'team',
    label: 'Team',
    price: '$129 / month',
    detail: 'Shared thinking power for teams deciding what to fund, prioritize, or execute next · 29,000 shared credits/month.',
    sales_only: false,
  },
  {
    plan_key: 'enterprise',
    label: 'Enterprise',
    price: '$299 / month+',
    detail: 'Governed decision support for organizations managing portfolios, resources, and cross-functional tradeoffs · 80,000 shared credits/month.',
    sales_only: false,
  },
];

const FALLBACK_PACKS = [
  { pack_key: 'credits_3000', label: '3,000 credits', price_usd: 10, credits: 3000 },
  { pack_key: 'credits_8000', label: '8,000 credits', price_usd: 25, credits: 8000 },
  { pack_key: 'credits_18000', label: '18,000 credits', price_usd: 50, credits: 18000 },
];

const ESSENTIAL_POSITIONING_HEADLINE = 'When the decision has real consequences, Essential is built for you.';
const ESSENTIAL_POSITIONING_DETAIL = 'Use Essential when you need room to examine evidence, pressure test assumptions, compare tradeoffs, and preserve the reasoning behind decisions that matter.';
const PLAN_DISPLAY = {
  free: {
    fit: 'Try one real decision',
    summary: 'Use Jaspen to frame a choice, compare options, and see how structured decision support feels.',
    credits: '300 credits/month',
  },
  starter: {
    fit: 'Light personal use',
    summary: 'A little more thinking power for personal decisions, early ideas, and occasional planning.',
    credits: '1,000 credits/month',
  },
  essential: {
    fit: 'Important decisions',
    summary: ESSENTIAL_POSITIONING_HEADLINE,
    credits: '7,000 credits/month',
  },
  team: {
    fit: 'Shared resource choices',
    summary: 'Give a team more room to prioritize work, compare tradeoffs, and turn decisions into plans.',
    credits: '29,000 shared credits/month',
  },
  enterprise: {
    fit: 'Governed rollout',
    summary: 'Support portfolios, resource allocation, and cross-functional planning with more capacity.',
    credits: '80,000 shared credits/month',
  },
};

const formatPlanPrice = (price) => {
  if (!price) return '';
  return String(price)
    .replace(/\s*\/\s*month\+/i, '+/mo')
    .replace(/\s*\/\s*month/i, '/mo');
};

export default function PricingPage() {
  const { user } = useAuth();
  const [plans, setPlans] = useState(FALLBACK_PLANS);
  const [packs, setPacks] = useState(FALLBACK_PACKS);
  const [statusMessage, setStatusMessage] = useState('');
  const planIntentCleanedRef = useRef(false);

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
      })
      .catch(() => {
        // Keep fallback content if catalog fetch fails.
      });
  }, []);

  // Public pricing always starts with a free account; paid upgrades happen inside Account.
  useEffect(() => {
    if (planIntentCleanedRef.current) return;
    const params = new URLSearchParams(window.location.search || '');
    const planParam = (params.get('plan') || params.get('plan_key') || '').trim().toLowerCase();
    if (!planParam || planParam === 'free') return;
    planIntentCleanedRef.current = true;
    params.delete('plan');
    params.delete('plan_key');
    const newSearch = params.toString();
    window.history.replaceState(
      {},
      document.title,
      `${window.location.pathname}${newSearch ? `?${newSearch}` : ''}#plans`,
    );
    setStatusMessage('Start with a free account. You can upgrade from Account after sign-in.');
  }, []);

  const isLoggedIn = !!user;

  const openAccountPlans = () => {
    if (!user) {
      window.location.href = '/?auth=1';
      return;
    }
    window.location.href = '/account?tab=plans';
  };

  return (
    <MarketingPageLayout pageClass="page-pricing page-flat-refresh">
      <Seo
        title="Pricing"
        description="Explore Jaspen pricing for individuals, teams, and organizations making important resource decisions."
        canonicalPath="/pages/pricing"
      />
      <section className="page-hero page-hero-pricing page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Pricing</p>
          <h1>Start with one decision. Scale when the work gets bigger.</h1>
          <p>
            Jaspen starts free so you can try it on a real choice. Upgrade when you need more
            room to examine evidence, compare tradeoffs, preserve reasoning, or bring a team
            into the decision-to-plan workflow.
          </p>
        </div>
      </section>

      <section id="overview" className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-pricing">
          <article className="lydia-content">
            <h3>Pricing follows the way decisions grow.</h3>
            <p>
              A single person may need help choosing what deserves attention. A team may need
              shared context, clearer tradeoffs, and a plan everyone can execute from. Larger
              organizations need the same thinking with more governance and capacity.
            </p>
            <ul className="lydia-bullets">
              <li>Free and Starter help individuals test and use Jaspen</li>
              <li>Essential gives more room for consequential decisions</li>
              <li>Team and Enterprise support shared resources and rollout</li>
            </ul>
          </article>
        </div>
      </section>

      <section id="plans" className="marketing-section">
        <h2>Plans</h2>
        {statusMessage && <p className="pricing-inline-status">{statusMessage}</p>}
        <div className="plans-grid">
          {plans.map((plan) => {
            const isEssential = plan.plan_key === 'essential';
            const isFree = plan.plan_key === 'free';
            const display = PLAN_DISPLAY[plan.plan_key] || {
              fit: 'Plan',
              summary: plan.detail,
              credits: '',
            };
            return (
              <article key={plan.plan_key} id={plan.plan_key} className={`marketing-card pricing-plan-card ${isEssential ? 'is-featured' : ''}`}>
                <div>
                  <div className="pricing-plan-head">
                    <h3>{plan.label}</h3>
                    {isEssential && <span className="pricing-plan-marker">Most useful</span>}
                  </div>
                  <div className="pricing-price-row">
                    <span className="plan-price">{formatPlanPrice(plan.price)}</span>
                  </div>
                  <p className="pricing-plan-fit">{display.fit}</p>
                  <p className="pricing-plan-summary">{display.summary}</p>
                  {display.credits && <p className="pricing-plan-credits">{display.credits}</p>}
                </div>
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
                    onClick={openAccountPlans}
                  >
                    {isFree ? 'Open workspace' : 'Upgrade inside'}
                  </button>
                )}
              </article>
            );
          })}
        </div>
        <p className="pricing-plan-note">{ESSENTIAL_POSITIONING_DETAIL}</p>
      </section>

      <section id="credit-packs" className="marketing-section">
        <h2>One-time credit packs</h2>
        {isLoggedIn ? (
          <>
            <p className="pricing-pack-copy">
              Add thinking power without changing plan tier.
            </p>
            <div className="plans-grid pricing-pack-grid">
              {packs.map((pack) => {
                const price = Number(pack.price_usd);
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
                      onClick={() => {
                        window.location.href = '/account?tab=packs';
                      }}
                    >
                      Buy credit pack
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

      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-pricing">
          <article className="lydia-content">
            <h3>Upgrade path</h3>
            <p>
              Start free, use Starter when you need a little more room, choose Essential for
              decisions with meaningful consequences, and move to Team or Enterprise when the
              work involves shared resources, governance, or cross-functional planning.
            </p>
          </article>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
