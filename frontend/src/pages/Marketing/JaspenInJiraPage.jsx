import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';

const WHAT_IT_DOES = [
  {
    title: 'Create issues from execution plans',
    detail: 'Jaspen pushes tasks from your generated work breakdown structure directly into Jira as issues — with titles, descriptions, and priority pre-populated from initiative context.',
  },
  {
    title: 'Sync delivery status in real time',
    detail: 'As your team closes issues and advances sprints in Jira, delivery status flows back into Jaspen\'s workspace view automatically — no manual status updates required.',
  },
  {
    title: 'Track milestones against sprint progress',
    detail: 'Jaspen maps Jira sprint data to original execution milestones so you can see whether delivery is on track against the plan that came from the approved decision.',
  },
  {
    title: 'Surface dependency and sequencing risk',
    detail: 'Active Jira project data feeds Jaspen\'s readiness scoring — so when blockers stack or dependencies fall behind, confidence signals update before leadership has to ask.',
  },
];

const SETUP_FIELDS = [
  { label: 'Jira URL', detail: 'Your organization\'s Jira instance URL' },
  { label: 'Project key', detail: 'The Jira project where issues will be created' },
  { label: 'API credentials', detail: 'Email address and API token with project write access' },
  { label: 'Issue type', detail: 'Default issue type for Jaspen-generated tasks (Story, Task, etc.)' },
  { label: 'Sync mode', detail: 'One-way push, two-way sync, or read-only pull' },
  { label: 'Conflict policy', detail: 'Jaspen-first, Jira-first, or manual resolution on conflicts' },
];

export default function JaspenInJiraPage() {
  return (
    <MarketingPageLayout pageClass="page-jaspen-in-jira">
      <section className="page-hero page-hero-integration">
        <div className="hero-copy">
          <p className="hero-kicker">Integrations</p>
          <h1>Jaspen and Jira — from decision to delivery in one connected flow</h1>
          <p>
            Move from initiative approval to tracked project work without rebuilding context in your
            project management system. Jaspen's Jira connector keeps execution plans and delivery
            progress synchronized automatically.
          </p>
          <div className="hero-cta-row">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary-light">All connectors</Link>
          </div>
        </div>
        <div className="hero-abstract integration-abstract">
          <span className="integration-chip">Jaspen plan</span>
          <span className="integration-chip integration-chip-arrow">→</span>
          <span className="integration-chip">Jira issues</span>
          <span className="integration-chip integration-chip-arrow">↔</span>
          <span className="integration-chip">Status sync</span>
        </div>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-integration">
          <div className="lydia-visual integration-flow-visual">
            <div className="int-flow-box int-flow-jaspen">Jaspen workspace</div>
            <div className="int-flow-connector">
              <span>Push tasks</span>
              <span className="int-flow-arrow">⇄</span>
              <span>Sync status</span>
            </div>
            <div className="int-flow-box int-flow-tool">Jira project</div>
          </div>
          <article className="lydia-content">
            <h3>Why teams lose time between planning and tracking</h3>
            <p>
              When a decision is approved, someone has to manually translate it into Jira tickets —
              then manually update the plan as Jira progresses. That gap is where delivery confidence
              erodes and status drift begins. The Jira connector closes it.
            </p>
            <ul className="lydia-bullets">
              <li>Approved plans push to Jira without manual ticket creation</li>
              <li>Sprint and issue progress reflects back into Jaspen readiness scores</li>
              <li>Teams operate in Jira while leadership sees the full delivery picture in Jaspen</li>
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
          The Jira connector is configured in your Jaspen workspace settings. You'll need the following
          to complete setup.
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
          <h3>Works alongside other connectors</h3>
          <p>
            The Jira connector can run alongside Smartsheet, Salesforce, and data connectors — giving
            execution teams a synchronized view while keeping business data flowing into recommendations.
          </p>
        </div>
      </section>

      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Connect your Jira project to Jaspen</h3>
            <p>
              Available on every plan. Setup takes under 10 minutes with an active Jira
              project and API credentials.
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
