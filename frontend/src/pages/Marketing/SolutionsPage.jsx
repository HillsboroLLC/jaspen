import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';

const USE_CASES = [
  {
    id: 'jaspen-security',
    title: 'Jaspen Security',
    detail: 'Tie initiative decisions to governance constraints, controls, and risk posture from day one.',
  },
  {
    id: 'execution',
    title: 'Execution',
    detail: 'Translate strategy into owner-ready milestones, tracked dependencies, and concrete progress signals.',
  },
];

const INDUSTRIES = [
  'Financial Services',
  'Nonprofits',
  'Quick Service Restaurants',
  'Government',
  'Healthcare',
  'Wellness',
  'Energy',
  'Aviation',
];

export default function SolutionsPage() {
  return (
    <MarketingPageLayout pageClass="page-solutions">
      <section className="page-hero page-hero-solutions">
        <div className="hero-copy">
          <p className="hero-kicker">Solutions</p>
          <h1>Solutions built for decision quality and execution speed</h1>
          <p>Use-case and industry frameworks tailored for teams that need clear recommendations and reliable delivery.</p>
        </div>
        <div className="hero-abstract solutions-abstract">
          <div className="flow-node">Security</div>
          <div className="flow-node">Execution</div>
          <div className="flow-node">Governance</div>
        </div>
      </section>

      <section className="marketing-section">
        <div className="solutions-intro-grid">
          <article className="marketing-card solutions-intro-card">
            <h3>Why teams use Jaspen for solutions</h3>
            <p>
              Teams use Jaspen to keep decision quality and operational execution in one flow.
              The platform reduces rework between strategic planning, risk review, and delivery.
            </p>
          </article>
          <article className="marketing-card solutions-intro-metrics">
            <div>
              <strong>Use-case fit</strong>
              <p>Security, transformation, and execution workflows</p>
            </div>
            <div>
              <strong>Industry coverage</strong>
              <p>Eight active vertical patterns including Wellness</p>
            </div>
          </article>
        </div>
      </section>

      <section id="use-cases" className="marketing-section">
        <h2>Use Cases</h2>
        <div className="solutions-use-case-stack">
          {USE_CASES.map((item) => (
            <article key={item.title} id={item.id} className="marketing-card">
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="industries" className="marketing-section">
        <h2>Industries</h2>
        <div className="marketing-card industry-surface">
          <ul className="industry-grid">
            {INDUSTRIES.map((industry) => (
              <li key={industry}>{industry}</li>
            ))}
          </ul>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
