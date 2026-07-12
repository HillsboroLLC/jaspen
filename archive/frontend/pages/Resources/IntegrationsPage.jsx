import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const INTEGRATION_CAPABILITIES = [
  {
    title: 'Unified operating context',
    detail: 'Bring strategic inputs, delivery progress, and business signals into one connected workspace experience.',
  },
  {
    title: 'Cross-system workflow continuity',
    detail: 'Keep teams in flow by reducing manual context switching and handoff overhead between systems.',
  },
  {
    title: 'Actionable recommendations in context',
    detail: 'Surface recommendations where teams work so decisions can move directly into operational follow-through.',
  },
];

const INTEGRATION_PACKAGES = [
  {
    name: 'Execution Package',
    detail: 'For planning and delivery teams that need synchronized progress, ownership, and milestone visibility.',
  },
  {
    name: 'Revenue & Operations Package',
    detail: 'For teams combining pipeline and operating data with initiative planning and execution updates.',
  },
  {
    name: 'Enterprise Governance Package',
    detail: 'For organizations requiring consistent controls, auditable flows, and leadership-level visibility.',
  },
];

export default function IntegrationsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-integrations">
      <section className="page-hero page-hero-integrations">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Integrations for one connected operating experience</h1>
          <p>
            Integrations package connected systems into a usable workflow so teams can move from insight to execution
            without tool-hopping or manual rework.
          </p>
        </div>
        <div className="hero-abstract integration-abstract">
          <span className="integration-chip">Unified context</span>
          <span className="integration-chip">Workflow continuity</span>
          <span className="integration-chip">Execution follow-through</span>
        </div>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-integrations">
          <div className="lydia-visual integrations-canvas">
            <div className="integration-block">Business data</div>
            <div className="integration-block">Execution systems</div>
            <div className="integration-block">Jaspen workspace</div>
          </div>
          <article className="lydia-content">
            <h3>What integrations do for teams</h3>
            <p>
              Integrations are the experience layer teams use to keep context, decisions, and operational progress
              connected across systems in day-to-day execution.
            </p>
            <ul className="lydia-bullets">
              <li>Reduce manual synchronization across systems</li>
              <li>Keep decision rationale attached to delivery updates</li>
              <li>Improve cross-functional alignment and execution speed</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>Integration capabilities</h2>
        <div className="marketing-grid">
          {INTEGRATION_CAPABILITIES.map((item) => (
            <article key={item.title} className="marketing-card">
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <h2>Integration packages</h2>
        <div className="resource-track">
          {INTEGRATION_PACKAGES.map((item, idx) => (
            <article key={item.name} className="resource-card">
              <span className="resource-index">I{idx + 1}</span>
              <h3>{item.name}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
