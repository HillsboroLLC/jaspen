import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';

const USE_CASES = [
  {
    id: 'jaspen-security',
    title: 'Jaspen Security',
    detail: 'Tie initiative decisions to governance constraints, controls, and risk posture from day one.',
    bullets: [
      'Score security initiatives against business risk appetite and control frameworks',
      'Keep remediation and compliance efforts connected to strategic priorities',
      'Track delivery accountability for security programs with milestone-level visibility',
      'Surface readiness gaps before audits, reviews, or regulatory deadlines',
    ],
  },
  {
    id: 'execution',
    title: 'Execution',
    detail: 'Translate strategy into owner-ready milestones, tracked dependencies, and concrete progress signals.',
    bullets: [
      'Convert approved decisions into structured work plans with owners and timelines',
      'Monitor delivery confidence against original plan assumptions in real time',
      'Identify sequencing risk and blocked dependencies before they delay delivery',
      'Generate leadership-ready status signals from active execution context',
    ],
  },
];

const INDUSTRIES = [
  {
    name: 'Financial Services',
    detail: 'Govern investment decisions and regulatory initiatives with traceable rationale and risk-adjusted prioritization.',
  },
  {
    name: 'Nonprofits',
    detail: 'Align mission-critical programs to funding constraints and board priorities with clear delivery accountability.',
  },
  {
    name: 'Quick Service Restaurants',
    detail: 'Coordinate multi-location rollouts, operational changes, and new concept launches with synchronized execution.',
  },
  {
    name: 'Government',
    detail: 'Connect policy decisions to delivery milestones with auditable rationale and cross-agency coordination.',
  },
  {
    name: 'Healthcare',
    detail: 'Manage clinical and operational initiatives under compliance constraints with clear ownership and readiness signals.',
  },
  {
    name: 'Wellness',
    detail: 'Plan service expansions and provider network changes with confidence scoring and delivery coordination.',
  },
  {
    name: 'Energy',
    detail: 'Sequence infrastructure projects and capital programs with risk-adjusted prioritization and execution tracking.',
  },
  {
    name: 'Aviation',
    detail: 'Manage operational readiness reviews and multi-phase programs where safety, compliance, and timing intersect.',
  },
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
            <article key={item.title} id={item.id} className="marketing-card solutions-use-case-card">
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
              <ul className="solutions-use-case-bullets">
                {item.bullets.map((b) => <li key={b}>{b}</li>)}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section id="industries" className="marketing-section">
        <h2>Industries</h2>
        <div className="industry-cards-grid">
          {INDUSTRIES.map((industry) => (
            <article
              key={industry.name}
              id={industry.name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')}
              className="marketing-card industry-card"
            >
              <h3>{industry.name}</h3>
              <p>{industry.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
