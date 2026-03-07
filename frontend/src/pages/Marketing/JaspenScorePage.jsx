import React from 'react';
import MarketingPageLayout from './MarketingPageLayout';

const SCORE_PILLARS = [
  {
    title: 'Strategic Fit',
    score: 91,
    detail: 'Measures alignment to business outcomes, risk posture, and operating priorities.',
  },
  {
    title: 'Execution Readiness',
    score: 84,
    detail: 'Evaluates clarity of owners, milestones, dependencies, and sequencing risk.',
  },
  {
    title: 'Impact Potential',
    score: 86,
    detail: 'Surfaces expected value, confidence range, and upside/downside assumptions.',
  },
];

export default function JaspenScorePage() {
  return (
    <MarketingPageLayout pageClass="page-score">
      <section className="page-hero page-hero-score">
        <div className="hero-copy">
          <p className="hero-kicker">Product</p>
          <h1>Jaspen Score turns ambiguity into a decision signal</h1>
          <p>Quantify initiative quality before execution begins so teams can prioritize with confidence and speed.</p>
        </div>
        <div className="hero-abstract score-abstract">
          <div className="floating-pill">Strategic Fit</div>
          <div className="floating-pill">Execution Readiness</div>
          <div className="floating-pill">Impact Potential</div>
        </div>
      </section>

      <section className="marketing-section">
        <div className="score-intro-layout">
          <article className="scorecard-shell">
            <div className="scorecard-head">
              <p>JASPEN SCORECARD</p>
              <span>Live evaluation</span>
            </div>
            <div className="scorecard-main">
              <div className="score-ring-wrap">
                <div className="score-ring">
                  <span>87</span>
                  <small>Total</small>
                </div>
                <div className="scorecard-readiness">Execution Ready</div>
              </div>
              <div className="scorecard-rows">
                {SCORE_PILLARS.map((pillar) => (
                  <div key={`row-${pillar.title}`} className="scorecard-row">
                    <span>{pillar.title}</span>
                    <div className="scorecard-bar-track">
                      <div className="scorecard-bar-fill" style={{ '--score-width': `${pillar.score}%` }}></div>
                    </div>
                    <strong>{pillar.score}</strong>
                  </div>
                ))}
              </div>
            </div>
            <p className="scorecard-footnote">Built from context quality, delivery confidence, and expected impact signals.</p>
          </article>
          <article className="score-guidance-panel">
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
            <article key={pillar.title} className="score-pillar-card">
              <div className="score-pillar-head">
                <h3>{pillar.title}</h3>
                <span>{pillar.score}</span>
              </div>
              <p>{pillar.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
