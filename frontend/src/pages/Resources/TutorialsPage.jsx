import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const TUTORIALS = [
  'Frame the decision and define criteria',
  'Compare options against the information you have',
  'Review assumptions, tradeoffs, and recommendation rationale',
  'Turn the chosen direction into an execution plan',
];

const AGENT_COMPONENTS = [
  { title: 'Intake Layer', detail: 'Captures the question, constraints, available context, and what the user is trying to decide.' },
  { title: 'Reasoning Core', detail: 'Helps compare options, tradeoffs, and recommendation rationale from the information available.' },
  { title: 'Scoring and Readiness', detail: 'Shows how strong the evidence and planning context appear without treating the score as absolute truth.' },
  { title: 'Tradeoff Engine', detail: 'Compares paths across impact, cost, risk, effort, timing, and other criteria the user chooses.' },
  { title: 'Execution Translator', detail: 'Turns an approved direction into milestones, owners, dependencies, and plan artifacts.' },
  { title: 'Connector Orchestrator', detail: 'Defines which external systems can provide context or receive planning outputs.' },
  { title: 'Audit and Admin Controls', detail: 'Records access and connector changes so teams can understand how context entered the workflow.' },
];

const CONNECTOR_TYPES = [
  {
    label: 'Execution Connectors',
    description: 'Synchronize plans, ownership, and status between Jaspen and execution systems.',
    rows: [
      {
        connector: 'Jira',
        path: '/pages/jaspen-in-jira',
        on: 'Issue sync, sprint tracking, and delivery status updates.',
        off: 'No Jira issue pull/push or Jira-driven status updates.',
        settings: 'Jira URL, project key, email, API token, issue type, sync mode, conflict policy.',
      },
      {
        connector: 'Smartsheet',
        path: '/pages/jaspen-in-smartsheets',
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
    <MarketingPageLayout pageClass="page-resources page-tutorials page-flat-refresh">
      <Seo
        title="Jaspen Tutorials: Setup, Rollout, and Connector Reference"
        description="Step-by-step guides for setting up initiative framing, building execution milestones, and configuring Jaspen's Jira, Smartsheet, and data connectors."
        canonicalPath="/pages/resources/tutorials"
      />
      <section className="page-hero page-hero-resources page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Tutorials for better decisions and clearer plans.</h1>
          <p>
            Learn how to frame a decision, compare options, preserve the reasoning,
            and generate an execution plan once the direction is chosen.
          </p>
        </div>
      </section>
      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-tutorials">
          <article className="lydia-content">
            <h3>Learning path with the right order</h3>
            <p>
              The first job is choosing what deserves resources. The second job is creating a plan
              people can execute. The tutorials should teach that sequence clearly.
            </p>
            <ul className="lydia-bullets">
              <li>Progressive path for first-time and advanced users</li>
              <li>Exercises tied to real decisions, not abstract examples</li>
              <li>Planning guidance that leaves execution ownership with the team</li>
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
          Jaspen is a decision-focused thought partner. It uses structured and unstructured context to
          compare options, preserve reasoning, and translate an approved direction into a plan people can execute.
        </p>
        <p>
          Connector settings define which external systems can supply context or receive planning outputs.
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
                    <td>{row.path ? <Link to={row.path}>{row.connector}</Link> : row.connector}</td>
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
