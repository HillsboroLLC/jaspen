import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const PLUGINS = [
  { title: 'Briefing Plugin', detail: 'Generate executive-ready updates from active initiative context.' },
  { title: 'Risk Escalation Plugin', detail: 'Trigger escalations when readiness or dependency risk drops below threshold.' },
  { title: 'Decision Log Plugin', detail: 'Capture final decisions and rationale as a durable operating record.' },
];

export default function PluginsPage() {
  return (
    <MarketingPageLayout
      eyebrow="RESOURCES"
      title="Plugins for workflow-specific extension"
      subtitle="Extend Jaspen into role-specific workflows without breaking your core decision-to-execution flow."
    >
      <section className="marketing-section">
        <h2>Plugin Patterns</h2>
        <div className="resource-track">
          {PLUGINS.map((plugin, idx) => (
            <article key={plugin.title} className="resource-card">
              <span className="resource-index">P{idx + 1}</span>
              <h3>{plugin.title}</h3>
              <p>{plugin.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
