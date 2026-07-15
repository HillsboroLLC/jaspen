import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const PLUGINS = [
  {
    title: 'Briefing Plugin',
    detail: 'Turn a decision record and plan into a clearer update.',
    expanded: 'Summarizes the decision, the reasoning, the plan, and the open assumptions so stakeholders can review the work without reconstructing the context.',
    roles: 'Strategy leads, Chiefs of Staff',
  },
  {
    title: 'Assumption Review Plugin',
    detail: 'Bring hidden assumptions back into the conversation.',
    expanded: 'Highlights the assumptions behind a decision or plan so teams can revisit what changed, what still holds, and where judgment may need to be updated.',
    roles: 'Program managers, PMO, delivery leads',
  },
  {
    title: 'Decision Log Plugin',
    detail: 'Capture final decisions and rationale as a durable record.',
    expanded: 'Records the context, options considered, tradeoffs evaluated, and final direction for every significant initiative decision. Creates an auditable thread teams can reference during reviews or handoffs.',
    roles: 'All team roles, audit and compliance',
  },
];

export default function PluginsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-plugins page-flat-refresh">
      <Seo
        title="Jaspen Plugins (Coming Soon) for Role-Specific Workflows"
        description="Jaspen plugins for briefings, risk escalation, and decision logging are in development. Join the waitlist to extend Jaspen into role-specific workflows at launch."
        canonicalPath="/pages/resources/plugins"
      />
      <div className="coming-soon-banner">
        <span className="coming-soon-badge">Coming Soon</span>
        Plugins are in development. Join the waitlist to be notified when they launch.{' '}
        <a href="mailto:hello@jaspen.ai">Get notified</a>
      </div>
      <section className="page-hero page-hero-resources page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Future plugins for decision-specific workflows.</h1>
          <p>
            Plugins are planned extensions that will help teams turn decision records into
            briefings, reviews, logs, and other recurring outputs.
          </p>
        </div>
      </section>
      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-plugins">
          <article className="lydia-content">
            <h3>Extensions without changing the core promise</h3>
            <p>
              The core product helps people choose where to spend resources and create a plan from
              that choice. Plugins should extend that record into specific recurring outputs.
            </p>
            <ul className="lydia-bullets">
              <li>Decision context stays shared across plugin outputs</li>
              <li>Teams get useful formats without rebuilding the reasoning</li>
              <li>Plugins remain optional and reviewed before release</li>
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
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary">View connectors</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
