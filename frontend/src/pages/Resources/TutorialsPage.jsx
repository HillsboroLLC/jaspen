import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const TUTORIALS = [
  'Set up initiative framing and decision criteria',
  'Build execution milestones and assign ownership',
  'Configure recurring score reviews and updates',
  'Create leadership-ready summaries and status signals',
];

const AGENT_COMPONENTS = [
  { title: 'Intake Layer', detail: 'Captures prompt, constraints, workspace context, and selected model tier.' },
  { title: 'Reasoning Core', detail: 'Generates options, tradeoffs, and recommended next actions from available context.' },
  { title: 'Scoring & Readiness', detail: 'Tracks confidence and checklist completion against plan quality.' },
  { title: 'Tradeoff Engine', detail: 'Builds and compares paths to quantify impact, cost, and risk across decision options.' },
  { title: 'Execution Translator', detail: 'Converts decisions into milestones, owners, and execution artifacts.' },
  { title: 'Connector Orchestrator', detail: 'Applies sync rules, credentials, conflict policies, and workspace mapping.' },
  { title: 'Audit & Admin Controls', detail: 'Records connector/access changes and supports managed overrides.' },
];

const CONNECTOR_TYPES = [
  {
    label: 'Execution Connectors',
    description: 'Synchronize plans, ownership, and status between Jaspen and execution systems.',
    rows: [
      {
        connector: 'Jira',
        on: 'Issue sync, sprint tracking, and delivery status updates.',
        off: 'No Jira issue pull/push or Jira-driven status updates.',
        settings: 'Jira URL, project key, email, API token, issue type, sync mode, conflict policy.',
      },
      {
        connector: 'Smartsheet',
        on: 'Sheet row progress, dates, and execution state mapping.',
        off: 'No Smartsheet timeline or status ingestion.',
        settings: 'External workspace/account id, sync mode, conflict policy.',
      },
    ],
  },
  {
    label: 'Data Connectors',
    description: 'Feed governed business and operations signals into recommendations and prioritization.',
    rows: [
      {
        connector: 'Salesforce',
        on: 'Pipeline and customer trend context in analysis.',
        off: 'No CRM trend context in recommendations.',
        settings: 'External workspace/account id, sync mode, conflict policy.',
      },
      {
        connector: 'Snowflake',
        on: 'Warehouse KPI and financial context for insights.',
        off: 'No Snowflake KPI/financial enrichment.',
        settings: 'External workspace/account id, sync mode, conflict policy.',
      },
      {
        connector: 'Oracle Fusion',
        on: 'ERP operations and finance signals for planning.',
        off: 'No Oracle Fusion operational/finance context.',
        settings: 'External workspace/account id, sync mode, conflict policy.',
      },
      {
        connector: 'ServiceNow',
        on: 'Service/change context for execution risk visibility.',
        off: 'No ITSM incident/change context.',
        settings: 'External workspace/account id, sync mode, conflict policy.',
      },
      {
        connector: 'NetSuite',
        on: 'Finance and operations context for execution tradeoffs.',
        off: 'No NetSuite finance/ops context.',
        settings: 'External workspace/account id, sync mode, conflict policy.',
      },
    ],
  },
];

export default function TutorialsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-tutorials">
      <section className="page-hero page-hero-resources">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Tutorials for adoption and rollout</h1>
          <p>Practical guides designed for operators, transformation leads, and execution teams.</p>
        </div>
        <div className="hero-abstract tutorials-abstract">
          <div className="step-dot"></div>
          <div className="step-dot"></div>
          <div className="step-dot"></div>
          <div className="step-dot"></div>
        </div>
      </section>
      <section className="marketing-section">
        <div className="lydia-story lydia-story-tutorials">
          <div className="lydia-visual tutorials-canvas">
            <div className="tutorial-step">01 Setup context</div>
            <div className="tutorial-step">02 Define milestones</div>
            <div className="tutorial-step">03 Track readiness</div>
            <div className="tutorial-step">04 Report decisions</div>
          </div>
          <article className="lydia-content">
            <h3>Learning path with operational continuity</h3>
            <p>
              Each tutorial step builds on the last so users can progress from setup to leadership reporting
              without switching frameworks or redoing artifacts.
            </p>
            <ul className="lydia-bullets">
              <li>Progressive path for first-time and advanced users</li>
              <li>Hands-on exercises tied to real initiative data</li>
              <li>Outcome format aligned to leadership updates</li>
            </ul>
          </article>
        </div>
      </section>
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
      <section className="marketing-section" id="docs">
        <h2>Knowledge Reference: Agent and Connectors</h2>
        <p>
          This section documents connector behavior, what each toggle state means, and how the agent is structured.
        </p>
      </section>
      <section className="marketing-section">
        <h2>The Agent Itself</h2>
        <p>
          Jaspen is an execution-focused decision agent. It ingests structured and unstructured context, produces
          recommendation-quality outputs, and translates approved direction into operational plans.
        </p>
        <p>
          Connector settings define which external systems can supply context and receive synchronized updates.
        </p>
      </section>
      <section className="marketing-section">
        <h2>Agent Components</h2>
        <div className="resource-track">
          {AGENT_COMPONENTS.map((component, idx) => (
            <article key={component.title} className="resource-card">
              <span className="resource-index">0{idx + 1}</span>
              <h3>{component.title}</h3>
              <p>{component.detail}</p>
            </article>
          ))}
        </div>
      </section>
      {CONNECTOR_TYPES.map((type) => (
        <section className="marketing-section" key={type.label}>
          <h2>{type.label}</h2>
          <p>{type.description}</p>
          <div className="tutorial-docs-table-wrap">
            <table className="tutorial-docs-table">
              <thead>
                <tr>
                  <th>Connector</th>
                  <th>Toggle On Unlocks</th>
                  <th>Toggle Off Locks</th>
                  <th>Required/Typical Settings</th>
                </tr>
              </thead>
              <tbody>
                {type.rows.map((row) => (
                  <tr key={`${type.label}-${row.connector}`}>
                    <td>{row.connector}</td>
                    <td>{row.on}</td>
                    <td>{row.off}</td>
                    <td>{row.settings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </MarketingPageLayout>
  );
}
