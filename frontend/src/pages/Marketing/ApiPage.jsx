import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const API_CAPABILITIES = [
  {
    title: 'Send decision context',
    detail: 'Pass goals, constraints, options, evidence, and operating context into Jaspen from internal systems.',
  },
  {
    title: 'Return structured reasoning',
    detail: 'Receive decision-ready outputs your systems can store, review, or route into the next workflow.',
  },
  {
    title: 'Connect decisions to planning',
    detail: 'Use approved direction to generate planning artifacts that teams can adapt before execution.',
  },
];

const API_WORKFLOWS = [
  {
    title: 'Resource prioritization',
    detail: 'Compare competing investments, initiatives, or requests against the criteria and information available.',
  },
  {
    title: 'Decision-to-plan handoff',
    detail: 'Convert an approved decision into plan structure that humans can review, assign, and carry forward.',
  },
  {
    title: 'Governed decision records',
    detail: 'Preserve why a recommendation was made, what evidence shaped it, and what assumptions should be revisited.',
  },
];

export default function ApiPage() {
  return (
    <MarketingPageLayout pageClass="page-api page-flat-refresh">
      <Seo
        title="Jaspen API (Coming Soon) for Decision Automation"
        description="The Jaspen API is in development, built to let internal systems send context, evaluate scenarios, and receive decision-grade recommendations programmatically."
        canonicalPath="/pages/api"
      />
      <div className="coming-soon-banner">
        <span className="coming-soon-badge">Coming Soon</span>
        The Jaspen API is in development and not yet available. <a href="mailto:hello@jaspen.ai">Get notified when it launches</a>
      </div>
      <section className="page-hero page-hero-api page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">API</p>
          <h1>Decision context, structured for your internal systems.</h1>
          <p>
            The Jaspen API is planned for teams that want to bring governed context into
            decision workflows and carry approved reasoning into their own systems.
          </p>
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

      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-api">
          <article className="lydia-content">
            <h3>How the flow should work in practice</h3>
            <p>
              Applications would send structured context to Jaspen, Jaspen would help compare the
              decision against the available information, and your systems would receive a reasoning
              record or planning artifact for review.
            </p>
            <ul className="lydia-bullets">
              <li>Programmatic support for recurring prioritization workflows</li>
              <li>Structured responses for reviewable system handoffs</li>
              <li>Decision records that preserve assumptions and tradeoffs</li>
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
