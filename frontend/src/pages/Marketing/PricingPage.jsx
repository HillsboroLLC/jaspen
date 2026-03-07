import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';

const PLAN_ITEMS = [
  {
    name: 'Free',
    price: '$0',
    detail: 'For individual users starting with core workflows and basic access.',
  },
  {
    name: 'Essential',
    price: '$20 / month',
    detail: 'For individuals ready for higher limits, stronger context depth, and daily usage.',
  },
  {
    name: 'Team',
    price: 'Contact sales',
    detail: 'For cross-functional teams that need shared workspaces, controls, and collaboration.',
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    detail: 'For organizations requiring governance, SSO, security controls, and implementation support.',
  },
];

export default function PricingPage() {
  return (
    <MarketingPageLayout pageClass="page-pricing">
      <section className="page-hero page-hero-pricing">
        <div className="hero-copy">
          <p className="hero-kicker">Pricing</p>
          <h1>Clear pricing from individual use to enterprise rollout</h1>
          <p>Start free, upgrade to Essential at $20, and scale with Team or Enterprise as adoption grows.</p>
        </div>
        <div className="hero-abstract pricing-abstract">
          <div className="floating-price">Free</div>
          <div className="floating-price">Essential $20</div>
          <div className="floating-price">Team</div>
          <div className="floating-price">Enterprise</div>
        </div>
      </section>

      <section id="overview" className="marketing-section">
        <h2>Overview</h2>
        <div className="pricing-overview-split">
          <article className="marketing-card pricing-highlight">
            <h3>Designed like modern AI-agent pricing</h3>
            <p>
              Start free as an individual, upgrade to Essential at $20/month, then scale to Team or Enterprise as adoption expands.
            </p>
          </article>
          <article className="marketing-card pricing-summary">
            <h3>What pricing includes</h3>
            <ul className="pricing-checks">
              <li>Individual entry tier with no paid commitment</li>
              <li>Simple Essential upgrade path at $20</li>
              <li>Team and Enterprise options for org-wide deployment</li>
            </ul>
          </article>
        </div>
      </section>

      <section id="api" className="marketing-section">
        <h2>API</h2>
        <article className="marketing-card api-surface">
          <h3>Integration and automation</h3>
          <p>
            API access supports custom automation, internal dashboards, and workflow handoffs.
            API limits and support tiers scale by plan and deployment model.
          </p>
        </article>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-pricing">
          <div className="lydia-visual pricing-architecture">
            <div className="pricing-node">Free</div>
            <div className="pricing-link"></div>
            <div className="pricing-node emphasized">Essential $20</div>
            <div className="pricing-link"></div>
            <div className="pricing-node">Team</div>
            <div className="pricing-link"></div>
            <div className="pricing-node">Enterprise</div>
          </div>
          <article className="lydia-content">
            <h3>Structured upgrade path</h3>
            <p>
              The model mirrors common AI-agent adoption patterns: individual entry, low-friction paid upgrade,
              then organization-scale rollout with governance and support.
            </p>
            <ul className="lydia-bullets">
              <li>Free for individual discovery and light usage</li>
              <li>Essential at $20 for daily individual workflows</li>
              <li>Team and Enterprise for controls, collaboration, and security</li>
            </ul>
          </article>
        </div>
      </section>

      <section id="plans" className="marketing-section">
        <h2>Plans</h2>
        <div className="plans-grid">
          {PLAN_ITEMS.map((plan) => (
            <article key={plan.name} className="marketing-card pricing-plan-card">
              <div className="pricing-plan-head">
                <h3>{plan.name}</h3>
                <span className="plan-price">{plan.price}</span>
              </div>
              <p>{plan.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
