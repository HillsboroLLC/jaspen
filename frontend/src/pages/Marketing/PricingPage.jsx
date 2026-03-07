import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';

const PLAN_ITEMS = [
  {
    name: 'Essential',
    detail: 'For teams starting with structured decision support and action planning.',
  },
  {
    name: 'Growth',
    detail: 'For organizations scaling cross-functional execution and portfolio visibility.',
  },
  {
    name: 'Transform',
    detail: 'For enterprise initiatives that require governance, integration, and advanced orchestration.',
  },
];

export default function PricingPage() {
  return (
    <MarketingPageLayout
      eyebrow="PRICING"
      title="Clear pricing for teams moving from analysis to execution"
      subtitle="Choose the plan that matches your scale today, then expand as your initiatives and integrations grow."
    >
      <section id="overview" className="marketing-section">
        <h2>Overview</h2>
        <div className="pricing-overview-split">
          <article className="marketing-card pricing-highlight">
            <h3>Designed for staged adoption</h3>
            <p>
              Jaspen pricing is designed around adoption stage, number of active initiatives, and depth of integrations.
              Start with core workflows and scale into enterprise governance when needed.
            </p>
          </article>
          <article className="marketing-card pricing-summary">
            <h3>What pricing includes</h3>
            <ul className="pricing-checks">
              <li>Decision and execution workflows</li>
              <li>Role-based collaboration</li>
              <li>Progress and readiness reporting</li>
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
            Detailed API limits and onboarding options are available during implementation scoping.
          </p>
        </article>
      </section>

      <section id="plans" className="marketing-section">
        <h2>Plans</h2>
        <div className="plans-grid">
          {PLAN_ITEMS.map((plan) => (
            <article key={plan.name} className="marketing-card pricing-plan-card">
              <h3>{plan.name}</h3>
              <p>{plan.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
