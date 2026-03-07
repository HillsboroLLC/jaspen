import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const PLUGINS = [
  { title: 'Briefing Plugin', detail: 'Generate executive-ready updates from active initiative context.' },
  { title: 'Risk Escalation Plugin', detail: 'Trigger escalations when readiness or dependency risk drops below threshold.' },
  { title: 'Decision Log Plugin', detail: 'Capture final decisions and rationale as a durable operating record.' },
];

export default function PluginsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-plugins">
      <section className="page-hero page-hero-resources">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Plugins for workflow-specific extension</h1>
          <p>Extend Jaspen into role-specific workflows without breaking your core decision-to-execution flow.</p>
        </div>
        <div className="hero-abstract plugins-abstract">
          <div className="plugin-block"></div>
          <div className="plugin-block"></div>
          <div className="plugin-block"></div>
        </div>
      </section>
      <section className="marketing-section">
        <div className="lydia-story lydia-story-plugins">
          <div className="lydia-visual plugins-canvas">
            <div className="plugin-card plugin-card-large">Briefing Output</div>
            <div className="plugin-card">Risk Escalation</div>
            <div className="plugin-card">Decision Log</div>
          </div>
          <article className="lydia-content">
            <h3>Composable extensions for role-specific workflows</h3>
            <p>
              Plugins let teams tailor outputs by function while preserving the same decision-to-execution backbone.
              Leadership, PMO, and delivery teams each get purpose-built views.
            </p>
            <ul className="lydia-bullets">
              <li>Drop-in modules for recurring workflow requirements</li>
              <li>Shared context across plugin outputs and core workflows</li>
              <li>Faster adoption by role without platform fragmentation</li>
            </ul>
          </article>
        </div>
      </section>
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
