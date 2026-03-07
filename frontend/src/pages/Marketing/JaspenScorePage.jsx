import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';

const SCORE_PILLARS = [
  {
    title: 'Strategic Fit',
    detail: 'Measures alignment to business outcomes, risk posture, and operating priorities.',
  },
  {
    title: 'Execution Readiness',
    detail: 'Evaluates clarity of owners, milestones, dependencies, and sequencing risk.',
  },
  {
    title: 'Impact Potential',
    detail: 'Surfaces expected value, confidence range, and upside/downside assumptions.',
  },
];

export default function JaspenScorePage() {
  return (
    <MarketingPageLayout
      eyebrow="PRODUCT"
      title="Jaspen Score turns ambiguity into a decision signal"
      subtitle="Quantify initiative quality before execution begins so teams can prioritize with confidence and speed."
    >
      <section className="marketing-section">
        <div className="score-intro-layout">
          <article className="marketing-card score-signal-card">
            <p className="score-label">Sample Signal</p>
            <div className="score-value-row">
              <span className="score-value">87</span>
              <span className="score-state">Execution Ready</span>
            </div>
            <p>Jaspen Score summarizes strategic fit, delivery readiness, and impact potential in one decision view.</p>
          </article>
          <article className="marketing-card score-guidance-card">
            <h3>How teams use it</h3>
            <ul className="score-guidance-list">
              <li>Prioritize initiatives with stronger execution odds</li>
              <li>Identify weak assumptions before funding decisions</li>
              <li>Align leadership on tradeoffs and delivery confidence</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>Scoring Pillars</h2>
        <div className="score-pillars-grid">
          {SCORE_PILLARS.map((pillar) => (
            <article key={pillar.title} className="marketing-card score-pillar-card">
              <h3>{pillar.title}</h3>
              <p>{pillar.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
