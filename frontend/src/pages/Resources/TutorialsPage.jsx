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
    <MarketingPageLayout
      eyebrow="RESOURCES"
      title="Tutorials for adoption and rollout"
      subtitle="Practical guides designed for operators, transformation leads, and execution teams."
    >
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
