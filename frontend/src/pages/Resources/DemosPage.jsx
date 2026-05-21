import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const DEMOS = [
  {
    title: 'Executive Decision Flow',
    detail: 'See how strategic inputs become option sets, tradeoffs, and recommended actions.',
    duration: '~12 min',
    audience: 'Strategy leads, executives',
  },
  {
    title: 'Cross-Functional Plan Build',
    detail: 'Watch an initiative move from framing to owner-ready milestones in one flow.',
    duration: '~18 min',
    audience: 'Program managers, PMO teams',
  },
  {
    title: 'Readiness and Risk Review',
    detail: 'Understand how readiness scoring and delivery risk signals stay connected.',
    duration: '~10 min',
    audience: 'Delivery leads, operations teams',
  },
];

export default function DemosPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-demos">
      <section className="page-hero page-hero-resources">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Product demos for decision and execution workflows</h1>
          <p>Use demo walkthroughs to evaluate fit before implementation planning.</p>
        </div>
        <div className="hero-abstract demos-abstract">
          <div className="demo-frame">01</div>
          <div className="demo-frame">02</div>
          <div className="demo-frame">03</div>
        </div>
      </section>
      <section className="marketing-section">
        <div className="lydia-story lydia-story-demos">
          <div className="lydia-visual demos-canvas">
            <div className="canvas-window">Decision framing</div>
            <div className="canvas-window">Execution plan</div>
            <div className="canvas-window">Risk review</div>
          </div>
          <article className="lydia-content">
            <h3>Walkthroughs built like real operator flow</h3>
            <p>
              Demos are sequenced to mirror adoption. Teams start with framing, move through execution setup,
              then validate readiness and delivery confidence.
            </p>
            <ul className="lydia-bullets">
              <li>Scenario-led demo flow instead of feature tour fragments</li>
              <li>Decision and execution artifacts shown in one sequence</li>
              <li>Built for stakeholder review and implementation planning</li>
            </ul>
          </article>
        </div>
      </section>
      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Recommended order</h3>
          <p>Start with Decision Flow, then Plan Build, then Readiness Review for a complete picture of the decision-to-execution journey.</p>
        </div>
      </section>
      <section className="marketing-section">
        <h2>Demo Library</h2>
        <div className="resource-track">
          {DEMOS.map((demo, idx) => (
            <article key={demo.title} className="resource-card demo-card">
              <span className="resource-index">0{idx + 1}</span>
              <h3>{demo.title}</h3>
              <p>{demo.detail}</p>
              <div className="demo-card-meta">
                <span>{demo.duration}</span>
                <span>{demo.audience}</span>
              </div>
            </article>
          ))}
        </div>
      </section>
      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>See Jaspen in action with your team</h3>
            <p>
              Request a live walkthrough tailored to your operating context — strategy review, program execution, or
              cross-functional coordination.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/login" className="demos-cta-btn demos-cta-btn-primary">Request a walkthrough</Link>
            <Link to="/pages/resources/tutorials" className="demos-cta-btn demos-cta-btn-secondary">Read the tutorials</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
