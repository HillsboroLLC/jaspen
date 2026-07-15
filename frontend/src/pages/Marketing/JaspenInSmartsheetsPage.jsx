import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const WHAT_IT_DOES = [
  {
    title: 'Carry plan structure into sheets',
    detail: 'Use Jaspen\'s execution plan as the starting point for milestones, owners, dates, and operational follow-up.',
  },
  {
    title: 'Keep planning tied to the decision',
    detail: 'Help teams understand why the plan exists, what assumptions shaped it, and where the key tradeoffs live.',
  },
  {
    title: 'Support operational review',
    detail: 'Use Smartsheet for the practical tracking layer while Jaspen preserves the decision context behind the plan.',
  },
  {
    title: 'Reduce spreadsheet rework',
    detail: 'Give teams a cleaner first draft instead of asking someone to rebuild the plan from scattered notes.',
  },
];

const SETUP_FIELDS = [
  { label: 'Workspace / account ID', detail: 'Your Smartsheet workspace or account identifier' },
  { label: 'Sheet mapping', detail: 'The target sheet where Jaspen milestones will be written' },
  { label: 'Sync mode', detail: 'One-way push from Jaspen, two-way sync, or read-only pull' },
  { label: 'Conflict policy', detail: 'How to handle edits made in both Smartsheet and Jaspen simultaneously' },
];

export default function JaspenInSmartsheetsPage() {
  return (
    <MarketingPageLayout pageClass="page-jaspen-in-smartsheets page-flat-refresh">
      <Seo
        title="Jaspen for Smartsheet: Carry Plans Into Operational Tracking"
        description="Use Jaspen with Smartsheet to carry approved decision context into operational planning, so teams can track the work without losing the reasoning behind it."
        canonicalPath="/pages/jaspen-in-smartsheets"
      />
      <section className="page-hero page-hero-integration page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Integrations</p>
          <h1>Turn Jaspen plans into operational tracking in Smartsheet.</h1>
          <p>
            Jaspen helps choose the right direction and draft the plan. Smartsheet helps teams
            carry that plan into the operational tracking they already use.
          </p>
          <div className="hero-cta-row">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary-light">All connectors</Link>
          </div>
        </div>
      </section>

      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-integration">
          <article className="lydia-content">
            <h3>Two tools, less context loss</h3>
            <p>
              Operational teams may prefer Smartsheet, while decision-making happens in Jaspen.
              The useful bridge is not just a copied task list. It is a plan that still carries
              the decision logic behind it.
            </p>
            <ul className="lydia-bullets">
              <li>Milestones begin from the approved decision and its constraints</li>
              <li>Teams can review and adapt the plan before tracking begins</li>
              <li>Works alongside Jira for organizations using multiple tracking environments</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>What the connector does</h2>
        <div className="marketing-grid">
          {WHAT_IT_DOES.map((item) => (
            <article key={item.title} className="marketing-card">
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <h2>Setup requirements</h2>
        <p className="section-subhead">
          The Smartsheet connector is configured in your Jaspen workspace settings. You'll need the
          following to complete setup.
        </p>
        <div className="setup-fields-grid">
          {SETUP_FIELDS.map((field) => (
            <div key={field.label} className="setup-field-row">
              <strong>{field.label}</strong>
              <span>{field.detail}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Pairs well with the Jira connector</h3>
          <p>
            Many organizations run Jira for engineering and Smartsheet for operations. Jaspen can help
            keep the planning context consistent before each team carries work into its preferred tool.
          </p>
        </div>
      </section>

      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Use Smartsheet after Jaspen shapes the plan</h3>
            <p>
              Start with a better decision and first plan in Jaspen, then carry the work into
              the tracker your operations team already knows.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">View plans</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary">See all connectors</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
