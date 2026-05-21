import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';

const WHAT_IT_DOES = [
  {
    title: 'Map milestones to sheet rows',
    detail: 'Jaspen execution plan milestones are mapped to Smartsheet rows automatically — with owners, dates, and status fields pre-populated from the initiative plan.',
  },
  {
    title: 'Pull operational progress into readiness',
    detail: 'As teams update rows in Smartsheet, timeline and completion data flows back into Jaspen\'s readiness view — keeping delivery confidence scores current without manual reporting.',
  },
  {
    title: 'Monitor plan-to-actual alignment',
    detail: 'Jaspen compares active Smartsheet progress against original milestone targets and flags when delivery confidence is drifting from plan assumptions.',
  },
  {
    title: 'Keep cross-functional teams aligned',
    detail: 'Operational teams track work in Smartsheet. Leadership views delivery signals in Jaspen. The connector keeps both views synchronized without duplicate data entry.',
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
    <MarketingPageLayout pageClass="page-jaspen-in-smartsheets">
      <section className="page-hero page-hero-integration">
        <div className="hero-copy">
          <p className="hero-kicker">Integrations</p>
          <h1>Jaspen and Smartsheet — initiative planning connected to operational tracking</h1>
          <p>
            Map Jaspen milestones to Smartsheet rows automatically so progress tracking stays
            synchronized — without asking operational teams to change where they work.
          </p>
          <div className="hero-cta-row">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary-light">All connectors</Link>
          </div>
        </div>
        <div className="hero-abstract integration-abstract">
          <span className="integration-chip">Jaspen milestones</span>
          <span className="integration-chip integration-chip-arrow">→</span>
          <span className="integration-chip">Smartsheet rows</span>
          <span className="integration-chip integration-chip-arrow">↔</span>
          <span className="integration-chip">Progress sync</span>
        </div>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-integration">
          <div className="lydia-visual integration-flow-visual">
            <div className="int-flow-box int-flow-jaspen">Jaspen workspace</div>
            <div className="int-flow-connector">
              <span>Push milestones</span>
              <span className="int-flow-arrow">⇄</span>
              <span>Pull progress</span>
            </div>
            <div className="int-flow-box int-flow-tool">Smartsheet</div>
          </div>
          <article className="lydia-content">
            <h3>Two tools, one operational picture</h3>
            <p>
              Operational teams live in Smartsheet. Strategy and leadership work in Jaspen. When these
              two views aren't connected, teams spend time reconciling spreadsheets instead of executing.
              The Smartsheet connector keeps them aligned automatically.
            </p>
            <ul className="lydia-bullets">
              <li>Milestones flow from Jaspen to Smartsheet without manual copying</li>
              <li>Progress and status updates flow back into delivery confidence scores</li>
              <li>Works alongside Jira for organizations running both project tracking environments</li>
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
            Many organizations run Jira for engineering and Smartsheet for operations. Jaspen supports
            both connectors simultaneously — each team works in its preferred tool while Jaspen maintains
            a single delivery picture.
          </p>
        </div>
      </section>

      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Connect your Smartsheet workspace to Jaspen</h3>
            <p>
              Available on Essential plans and above. Setup requires your Smartsheet workspace credentials
              and takes under 10 minutes.
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
