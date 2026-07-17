import React, { useState } from 'react';
import { createAnalytics } from '../../tools/shared/createAnalytics';
import EnterpriseInvestmentCalculator from './EnterpriseInvestmentCalculator';
import './PricingVariantB.css';

const analytics = createAnalytics('homepage_pricing');

const PLANS = [
  {
    key: 'free',
    name: 'Free',
    monthly: 0,
    annual: 0,
    seats: '1 seat',
    tagline: 'Test Jaspen on a real decision.',
    cta: 'Sign up',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'starter',
    name: 'Starter',
    monthly: 7,
    annual: 6,
    seats: '1 seat',
    tagline: 'Keep going with light personal use.',
    cta: 'Start free',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'essential',
    name: 'Essential',
    monthly: 39,
    annual: 32,
    seats: '1 seat',
    tagline: 'When the decision has real consequences, Essential is built for you.',
    cta: 'Start Free',
    href: '/?auth=1',
    featured: true,
  },
  {
    key: 'team',
    name: 'Team',
    monthly: 129,
    annual: 107,
    seats: '3 seats included',
    tagline: 'Align your team, execute with clarity.',
    cta: 'Start free',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'business',
    name: 'Business',
    monthly: 299,
    annual: 249,
    seats: '5 seats included',
    tagline: 'Bring a team together around clearer decisions, stronger execution, and reasoning that does not disappear when work changes hands.',
    cta: 'Start with Business',
    href: '/?auth=1',
    featured: false,
  },
];

const FEATURES = [
  {
    category: 'Credits & capacity',
    rows: [
      { label: 'Monthly credits',            sub: 'Resets each billing cycle',         free: '300',     starter: '1,000',   essential: '7,000',  team: '29,000',      business: '80,000'    },
      { label: 'Credits shared across team', sub: 'Pool drawn from one balance',        free: false,     starter: false,     essential: false,    team: true,          business: true        },
      { label: 'Buy additional credits',     sub: 'Top up any time mid-cycle',          free: true,      starter: true,      essential: true,     team: true,          business: true        },
    ],
  },
  {
    category: 'Workspace & seats',
    rows: [
      { label: 'Seats included',             sub: '',                                   free: '1',       starter: '1',       essential: '1',      team: '3',           business: '5'         },
      { label: 'Additional seats',           sub: 'Pay as you grow',                    free: false,     starter: false,     essential: false,    team: '+$25/seat',   business: 'Up to 10 users' },
      { label: 'Shared team workspace',      sub: '',                                   free: false,     starter: false,     essential: false,    team: true,          business: true        },
      { label: 'Scorecard export',           sub: 'PDF download',                       free: true,      starter: true,      essential: true,     team: true,          business: true        },
    ],
  },
  {
    category: 'AI models',
    rows: [
      { label: 'Pluto',                      sub: 'Fastest, lowest credit burn',        free: true,      starter: true,      essential: true,     team: true,          business: true        },
      { label: 'Orbit',                      sub: 'Deeper reasoning, moderate burn',    free: true,      starter: true,      essential: true,     team: true,          business: true        },
      { label: 'Titan',                      sub: 'Highest depth, highest burn',        free: true,      starter: true,      essential: true,     team: true,          business: true        },
    ],
  },
  {
    category: 'Support',
    rows: [
      { label: 'Community support',          sub: '',                                   free: true,      starter: true,      essential: true,     team: true,          business: true        },
      { label: 'Priority support',           sub: '',                                   free: false,     starter: false,     essential: false,    team: true,          business: true        },
      { label: 'Dedicated success manager',  sub: '',                                   free: false,     starter: false,     essential: false,    team: false,         business: true        },
    ],
  },
];

function Cell({ value }) {
  if (value === true)  return <i className="fa-solid fa-check pvb-check" aria-label="Included" />;
  if (value === false) return <span className="pvb-dash" aria-label="Not included">—</span>;
  return <span className="pvb-cell-text">{value}</span>;
}

export default function PricingVariantB({ onOpenModal }) {
  const [isAnnual, setIsAnnual] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [activeAudience, setActiveAudience] = useState('individuals');
  const isBusinessAudience = activeAudience === 'business';
  const individualPlans = PLANS.filter(plan => plan.key !== 'business');
  const visiblePlans = isBusinessAudience ? PLANS.filter(plan => plan.key === 'business') : individualPlans;

  const selectAudience = (audience) => {
    setActiveAudience(audience);
    analytics.track('pricing_audience_tab_selected', { audience });
  };

  const handleTabKeyDown = (event, audience) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const nextAudience = audience === 'individuals' ? 'business' : 'individuals';
    selectAudience(nextAudience);
    document.getElementById(`pricing-tab-${nextAudience}`)?.focus();
  };

  return (
    <section className="pvb-section" id="pricing-variant-b">

      {/* ── Header ── */}
      <div className="pvb-header">
        <h2>Plans for every stage</h2>
        <p className="pvb-subhead">All models available on every plan. You move up when you need more capacity.</p>
        <div className="pvb-audience-tabs" role="tablist" aria-label="Pricing audiences">
          <button
            id="pricing-tab-individuals"
            type="button"
            role="tab"
            aria-selected={!isBusinessAudience}
            aria-controls="pricing-panel-individuals"
            tabIndex={!isBusinessAudience ? 0 : -1}
            className={`pvb-audience-tab${!isBusinessAudience ? ' is-active' : ''}`}
            onClick={() => selectAudience('individuals')}
            onKeyDown={(event) => handleTabKeyDown(event, 'individuals')}
          >
            Individuals &amp; Teams
          </button>
          <button
            id="pricing-tab-business"
            type="button"
            role="tab"
            aria-selected={isBusinessAudience}
            aria-controls="pricing-panel-business"
            tabIndex={isBusinessAudience ? 0 : -1}
            className={`pvb-audience-tab${isBusinessAudience ? ' is-active' : ''}`}
            onClick={() => selectAudience('business')}
            onKeyDown={(event) => handleTabKeyDown(event, 'business')}
          >
            Business &amp; Enterprise
          </button>
        </div>
        <div className="pvb-billing-toggle">
          <span className={!isAnnual ? 'pvb-toggle-label is-active' : 'pvb-toggle-label'}>Monthly</span>
          <button
            type="button"
            role="switch"
            aria-checked={isAnnual}
            className={`pvb-toggle-track ${isAnnual ? 'is-on' : ''}`}
            onClick={() => setIsAnnual(value => { const next = !value; analytics.track('billing_interval_selected', { interval: next ? 'annual' : 'monthly' }); return next; })}
          >
            <span className="pvb-toggle-thumb" />
          </button>
          <span className={isAnnual ? 'pvb-toggle-label is-active' : 'pvb-toggle-label'}>
            Annual <em className="pvb-save-chip">Save 17%</em>
          </span>
        </div>
      </div>

      {/* ── Plan cards ── */}
      <div className={`pvb-plan-layout${isBusinessAudience ? ' is-business' : ''}`}>
      <div
        id={`pricing-panel-${activeAudience}`}
        role="tabpanel"
        aria-labelledby={`pricing-tab-${activeAudience}`}
        className={`pvb-cards-row ${isBusinessAudience ? 'is-business' : 'is-individuals'}`}
      >
        {visiblePlans.map(plan => {
          const price = isAnnual ? plan.annual : plan.monthly;
          return (
            <div key={plan.key} className={`pvb-card ${plan.featured ? 'is-featured' : ''}`}>
              {plan.featured && <span className="pvb-popular-badge">Most popular</span>}
              <p className="pvb-card-name">{plan.name}</p>
              <div className="pvb-card-price">
                {price === 0 ? (
                  <strong className="pvb-price-num">Free</strong>
                ) : (
                  <>
                    <span className="pvb-price-dollar">$</span>
                    <strong className="pvb-price-num">{price}</strong>
                    <span className="pvb-price-period">/mo</span>
                  </>
                )}
              </div>
              {isAnnual && price > 0 && (
                <p className="pvb-billed-note">{`$${(price * 12).toLocaleString()} billed annually · ${plan.seats}`}</p>
              )}
              {(!isAnnual || price === 0) && (
                <p className="pvb-billed-note">{plan.seats}</p>
              )}
              <p className="pvb-card-tagline">{plan.tagline}</p>
              {plan.key === 'business' && (
                <p className="pvb-business-seat-note">
                  Need a few more seats? Add up to 5 additional seats for a maximum of 10 users on Business.
                </p>
              )}
              <button
                type="button"
                className={`pvb-card-cta jaspen-btn ${plan.featured ? 'jaspen-btn-primary' : 'jaspen-btn-outline'}`}
                onClick={() => { analytics.track(plan.key === 'business' ? 'business_cta_clicked' : 'pricing_cta_clicked', { plan: plan.key, interval: isAnnual ? 'annual' : 'monthly' }); onOpenModal?.('signup', 'free'); }}
              >
                {plan.cta}
              </button>
            </div>
          );
        })}
      </div>

      {isBusinessAudience && <aside className="pvb-enterprise-intro">
          <p><strong>Need more than 10 seats?</strong> Larger teams and organizations with advanced administration, integration, security, or support needs may qualify for an annual Enterprise agreement.</p>
          <button type="button" className="jaspen-btn jaspen-btn-outline" onClick={() => { analytics.track('contact_sales_clicked', { placement: 'business_card' }); document.getElementById('eic-title')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }}>Contact Sales</button>
        </aside>}
      </div>

      {isBusinessAudience && <div className="pvb-enterprise-calculator-section">
        <EnterpriseInvestmentCalculator billing={isAnnual ? 'annual' : 'monthly'} onOpenModal={onOpenModal} />
      </div>}

      {!isBusinessAudience && (
        <p className="pvb-plan-note">
          Use Essential when you need room to examine evidence, pressure test assumptions, compare tradeoffs, and preserve the reasoning behind decisions that matter.
        </p>
      )}

      {/* ── Compare plans accordion ── */}
      {!isBusinessAudience && <div className="pvb-compare-accordion">
        <button
          type="button"
          className="pvb-compare-toggle"
          onClick={() => setCompareOpen(v => !v)}
          aria-expanded={compareOpen}
        >
          <span>Compare plans</span>
          <i className={`fa-solid fa-chevron-down pvb-compare-chevron${compareOpen ? ' is-open' : ''}`} aria-hidden="true" />
        </button>

        {compareOpen && (
          <div className="pvb-table-wrap">
            <table className="pvb-table">
              <thead>
                <tr>
                  <th className="pvb-th-label">Key features</th>
                  {individualPlans.map(p => (
                    <th key={p.key} className={`pvb-th-plan ${p.featured ? 'is-featured' : ''}`}>
                      <span className="pvb-compare-plan-name">{p.name}</span>
                      <button type="button" className={`pvb-compare-pill ${p.featured ? 'is-featured' : ''}`} onClick={() => onOpenModal?.('signup', 'free')}>{p.cta}</button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURES.map(section => (
                  <React.Fragment key={section.category}>
                    <tr className="pvb-category-row">
                      <td colSpan={individualPlans.length + 1}>{section.category}</td>
                    </tr>
                    {section.rows.map(row => (
                      <tr key={row.label} className="pvb-feature-row">
                        <td className="pvb-feature-label">
                          {row.label}
                          {row.sub && <span className="pvb-feature-sub">{row.sub}</span>}
                        </td>
                        {individualPlans.map(plan => (
                          <td key={plan.key} className={`pvb-cell ${plan.featured ? 'is-featured' : ''}`}>
                            <Cell value={row[plan.key]} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>}

      {isAnnual && <p className="pvb-annual-note">* Per-month price shown. Charged as one annual payment.</p>}
      {!isBusinessAudience && <p className="pvb-addons-note">
        Mid-cycle top-ups: <a href="#pricing-variant-b">3,000 credits for $10 · 8,000 for $25 · 18,000 for $50</a>
      </p>}

    </section>
  );
}
