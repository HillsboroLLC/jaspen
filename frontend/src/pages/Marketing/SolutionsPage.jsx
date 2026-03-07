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
        <div className="lydia-story lydia-story-solutions">
          <div className="lydia-visual solution-map">
            <div className="map-core">Jaspen Core</div>
            <div className="map-branch">Security Controls</div>
            <div className="map-branch">Execution Planning</div>
            <div className="map-branch">Industry Playbooks</div>
          </div>
          <article className="lydia-content">
            <h3>One system, different operating contexts</h3>
            <p>
              Jaspen keeps decision quality, governance, and execution flow connected while adapting to each industry pattern.
              Security and execution are separate tracks that still share a common operating signal.
            </p>
            <ul className="lydia-bullets">
              <li>Security and execution playbooks run as separate solution tracks</li>
              <li>Shared signal model keeps leadership aligned across teams</li>
              <li>Industry overlays adjust language, constraints, and metrics</li>
            </ul>
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
