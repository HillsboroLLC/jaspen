import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const WHAT_IT_DOES = [
  {
    title: 'Carry plan context into Jira',
    detail: 'Use the execution plan Jaspen drafts from an approved decision as the starting point for Jira issue structure.',
  },
  {
    title: 'Keep the decision record close',
    detail: 'Help teams understand why the work exists, what the tradeoffs were, and what assumptions shaped the plan.',
  },
  {
    title: 'Support sprint planning',
    detail: 'Translate milestones and dependencies into a structure your team can review before work enters Jira.',
  },
  {
    title: 'Reduce handoff loss',
    detail: 'Keep the path from decision to plan to tracked work easier to follow without pretending the software does the execution.',
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
    <MarketingPageLayout pageClass="page-jaspen-in-jira page-flat-refresh">
      <Seo
        title="Jaspen for Jira: Carry Decision Context Into Planning"
        description="Use Jaspen with Jira to carry approved decision context into execution planning, so teams can move from reasoning to tracked work with less handoff loss."
        canonicalPath="/pages/jaspen-in-jira"
      />
      <section className="page-hero page-hero-integration page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Integrations</p>
          <h1>Bring Jaspen's decision context into Jira planning.</h1>
          <p>
            Jaspen helps you choose what deserves resources, then turns the decision into an execution
            plan. Jira is where many teams carry that plan into tracked work.
          </p>
          <div className="hero-cta-row">
            <Link to="/#pricing-variant-b" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary-light">All connectors</Link>
          </div>
        </div>
      </section>

      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-integration">
          <article className="lydia-content">
            <h3>Why teams lose context between planning and tracking</h3>
            <p>
              When a decision becomes work, the reasoning often disappears. Teams see the ticket,
              but not the criteria, tradeoffs, or assumptions that shaped it. The Jira connector is
              meant to keep that handoff cleaner.
            </p>
            <ul className="lydia-bullets">
              <li>Start from a plan tied to the approved decision</li>
              <li>Translate milestones and dependencies into Jira-ready structure</li>
              <li>Let teams execute in Jira while Jaspen preserves the reasoning</li>
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
            The Jira connector can run alongside Smartsheet, Salesforce, and data connectors, giving
            teams a cleaner path from business context to decision to execution planning.
          </p>
        </div>
      </section>

      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Use Jira after Jaspen helps shape the plan</h3>
            <p>
              Start with the decision in Jaspen, then use Jira when your team is ready to turn
              the plan into tracked work.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/#pricing-variant-b" className="demos-cta-btn demos-cta-btn-primary">View plans</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary">See all connectors</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
