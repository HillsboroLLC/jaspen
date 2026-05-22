import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';

const API_CAPABILITIES = [
  {
    title: 'Automate plan updates',
    detail: 'Trigger milestone, owner, and status updates programmatically from your internal workflows.',
  },
  {
    title: 'Generate insight payloads',
    detail: 'Send operational context and receive structured recommendation outputs for downstream systems.',
  },
  {
    title: 'Embed Jaspen logic',
    detail: 'Use API responses in internal apps, dashboards, and orchestration pipelines.',
  },
];

const API_WORKFLOWS = [
  {
    title: 'Regional variance detection',
    detail: 'Detect differences in execution performance by region and return likely causes with action options.',
  },
  {
    title: 'Decision-to-delivery automation',
    detail: 'Convert approved recommendations into executable updates via internal workflow runners.',
  },
  {
    title: 'Executive signal generation',
    detail: 'Create recurring, structured decision signals for leadership reporting and governance review.',
  },
];

export default function ApiPage() {
  return (
    <MarketingPageLayout pageClass="page-api">
      <div className="coming-soon-banner">
        <span className="coming-soon-badge">Coming Soon</span>
        The Jaspen API is in development and not yet available. <a href="mailto:hello@jaspen.ai">Get notified when it launches</a>
      </div>
      <section className="page-hero page-hero-api">
        <div className="hero-copy">
          <p className="hero-kicker">API</p>
          <h1>Jaspen API for custom automation and intelligence workflows</h1>
          <p>
            Build custom workflows that send context to Jaspen, evaluate scenarios, and return decision-grade
            recommendations or action payloads to your internal systems.
          </p>
        </div>
        <div className="hero-abstract api-abstract">
          <div className="api-tag">POST /analysis</div>
          <div className="api-tag">POST /plan-updates</div>
          <div className="api-tag">GET /insights</div>
        </div>
      </section>

      <section className="marketing-section">
        <h2>What the API can do</h2>
        <div className="api-terms-grid">
          {API_CAPABILITIES.map((item) => (
            <article key={item.title} className="marketing-card api-term-card">
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-api">
          <div className="lydia-visual api-flow-canvas">
            <div className="api-flow-node">Input context</div>
            <div className="api-flow-node">Jaspen API evaluation</div>
            <div className="api-flow-node">Action payloads</div>
          </div>
          <article className="lydia-content">
            <h3>How the flow works in practice</h3>
            <p>
              Applications send structured context to the API, Jaspen evaluates risk and opportunity patterns, and your
              systems receive response payloads ready for operational action.
            </p>
            <ul className="lydia-bullets">
              <li>Programmatic analysis for recurring or event-based workflows</li>
              <li>Structured responses for deterministic system handoffs</li>
              <li>Custom orchestration aligned to enterprise architecture</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>Common API workflows</h2>
        <div className="marketing-grid">
          {API_WORKFLOWS.map((workflow) => (
            <article key={workflow.title} className="marketing-card">
              <h3>{workflow.title}</h3>
              <p>{workflow.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
