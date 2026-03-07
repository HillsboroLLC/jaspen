import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const TUTORIALS = [
  'Set up initiative framing and decision criteria',
  'Build execution milestones and assign ownership',
  'Configure recurring score reviews and updates',
  'Create leadership-ready summaries and status signals',
];

export default function TutorialsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-tutorials">
      <section className="page-hero page-hero-resources">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Tutorials for adoption and rollout</h1>
          <p>Practical guides designed for operators, transformation leads, and execution teams.</p>
        </div>
        <div className="hero-abstract tutorials-abstract">
          <div className="step-dot"></div>
          <div className="step-dot"></div>
          <div className="step-dot"></div>
          <div className="step-dot"></div>
        </div>
      </section>
      <section className="marketing-section">
        <div className="lydia-story lydia-story-tutorials">
          <div className="lydia-visual tutorials-canvas">
            <div className="tutorial-step">01 Setup context</div>
            <div className="tutorial-step">02 Define milestones</div>
            <div className="tutorial-step">03 Track readiness</div>
            <div className="tutorial-step">04 Report decisions</div>
          </div>
          <article className="lydia-content">
            <h3>Learning path with operational continuity</h3>
            <p>
              Each tutorial step builds on the last so users can progress from setup to leadership reporting
              without switching frameworks or redoing artifacts.
            </p>
            <ul className="lydia-bullets">
              <li>Progressive path for first-time and advanced users</li>
              <li>Hands-on exercises tied to real initiative data</li>
              <li>Outcome format aligned to leadership updates</li>
            </ul>
          </article>
        </div>
      </section>
      <section className="marketing-section">
        <h2>Tutorial Path</h2>
        <ol className="tutorial-ladder">
          {TUTORIALS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ol>
      </section>
      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Enablement note</h3>
          <p>Tutorials are meant to be run against a live initiative so teams can see outputs in real context.</p>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
