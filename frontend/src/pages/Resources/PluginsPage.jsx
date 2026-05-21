import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const PLUGINS = [
  {
    title: 'Briefing Plugin',
    detail: 'Generate executive-ready updates from active initiative context.',
    expanded: 'Pulls live milestone status, score changes, and risk flags into a structured briefing format. Outputs are formatted for leadership review without requiring manual assembly.',
    roles: 'Strategy leads, Chiefs of Staff',
  },
  {
    title: 'Risk Escalation Plugin',
    detail: 'Trigger escalations when readiness or dependency risk drops below threshold.',
    expanded: 'Monitors execution signals and fires escalation alerts when confidence drops, blockers stack, or delivery risk crosses a defined threshold. Keeps the right people informed before issues become failures.',
    roles: 'Program managers, PMO, delivery leads',
  },
  {
    title: 'Decision Log Plugin',
    detail: 'Capture final decisions and rationale as a durable operating record.',
    expanded: 'Records the context, options considered, tradeoffs evaluated, and final direction for every significant initiative decision. Creates an auditable thread teams can reference during reviews or handoffs.',
    roles: 'All team roles, audit and compliance',
  },
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
        <div className="plugins-card-stack">
          {PLUGINS.map((plugin, idx) => (
            <article key={plugin.title} className="marketing-card plugin-detail-card">
              <div className="plugin-detail-header">
                <span className="resource-index">P{idx + 1}</span>
                <div>
                  <h3>{plugin.title}</h3>
                  <p className="plugin-summary">{plugin.detail}</p>
                </div>
              </div>
              <p className="plugin-expanded">{plugin.expanded}</p>
              <p className="plugin-roles"><strong>Built for:</strong> {plugin.roles}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Build a plugin for your workflow</h3>
            <p>
              Plugins are designed to extend without replacing. Talk to us about composing a plugin pattern
              that fits your team's recurring output requirements.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/login" className="demos-cta-btn demos-cta-btn-primary">Get in touch</Link>
            <Link to="/pages/resources/integrations" className="demos-cta-btn demos-cta-btn-secondary">View integrations</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
