import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const DEMOS = [
  { title: 'Executive Decision Flow', detail: 'See how strategic inputs become option sets, tradeoffs, and recommended actions.' },
  { title: 'Cross-Functional Plan Build', detail: 'Watch an initiative move from framing to owner-ready milestones in one flow.' },
  { title: 'Readiness and Risk Review', detail: 'Understand how readiness scoring and delivery risk signals stay connected.' },
];

export default function DemosPage() {
  return (
    <MarketingPageLayout
      eyebrow="RESOURCES"
      title="Product demos for decision and execution workflows"
      subtitle="Use demo walkthroughs to evaluate fit before implementation planning."
    >
      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Recommended order</h3>
          <p>Start with Decision Flow, then Plan Build, then Readiness Review for a full product picture.</p>
        </div>
      </section>
      <section className="marketing-section">
        <h2>Demo Library</h2>
        <div className="resource-track">
          {DEMOS.map((demo, idx) => (
            <article key={demo.title} className="resource-card">
              <span className="resource-index">0{idx + 1}</span>
              <h3>{demo.title}</h3>
              <p>{demo.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
