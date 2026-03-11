import React from 'react';
import { Link } from 'react-router-dom';
import './Knowledge.css';

const COMPONENTS = [
  { title: 'Intake Layer', detail: 'Captures prompt, constraints, workspace context, and selected model tier.' },
  { title: 'Reasoning Core', detail: 'Generates options, tradeoffs, and recommended actions from available context.' },
  { title: 'Scoring & Readiness', detail: 'Tracks confidence and checklist completion against plan quality.' },
  { title: 'Scenario Modeler', detail: 'Builds and compares paths to quantify impact, cost, and risk.' },
  { title: 'Execution Translator', detail: 'Converts approved decisions into milestones and owner-ready actions.' },
  { title: 'Connector Orchestrator', detail: 'Applies sync rules, credentials, conflict policies, and workspace mapping.' },
];

const CONNECTORS = [
  {
    group: 'Execution',
    rows: [
      ['Jira', 'Issue sync, sprint tracking, and delivery status updates.', 'Jira URL, project key, email, API token, issue type'],
      ['Workfront', 'Milestone and ownership alignment with project structures.', 'External workspace/account id, sync mode, conflict policy'],
      ['Smartsheet', 'Sheet row progress, dates, and execution state mapping.', 'External workspace/account id, sync mode, conflict policy'],
    ],
  },
  {
    group: 'Data',
    rows: [
      ['Salesforce', 'Pipeline and customer trend context in analysis.', 'External workspace/account id, sync mode, conflict policy'],
      ['Snowflake', 'Warehouse KPI and financial context for insights.', 'External workspace/account id, sync mode, conflict policy'],
      ['Oracle Fusion', 'ERP operations and finance signals for planning.', 'External workspace/account id, sync mode, conflict policy'],
      ['ServiceNow', 'Service/change context for execution risk visibility.', 'External workspace/account id, sync mode, conflict policy'],
      ['NetSuite', 'Finance and operations context for execution tradeoffs.', 'External workspace/account id, sync mode, conflict policy'],
    ],
  },
];

export default function Knowledge() {
  return (
    <div className="knowledge-page">
      <div className="knowledge-shell">
        <header className="knowledge-header">
          <p className="knowledge-eyebrow">Knowledge</p>
          <h1>Internal Product Documentation</h1>
          <p>
            Reference for connector behavior, agent components, and required settings.
          </p>
          <div className="knowledge-actions">
            <Link to="/account#connectors" className="knowledge-btn-primary">Open Connectors</Link>
            <Link to="/account" className="knowledge-btn-secondary">Billing & Usage</Link>
          </div>
        </header>

        <section className="knowledge-section">
          <h2>The Agent</h2>
          <p>
            Jaspen is an execution-focused decision agent. It ingests structured and unstructured context,
            creates recommendation-grade outputs, and translates approved direction into operational plans.
          </p>
        </section>

        <section className="knowledge-section">
          <h2>Agent Components</h2>
          <div className="knowledge-component-grid">
            {COMPONENTS.map((item) => (
              <article key={item.title} className="knowledge-component-card">
                <h3>{item.title}</h3>
                <p>{item.detail}</p>
              </article>
            ))}
          </div>
        </section>

        {CONNECTORS.map((group) => (
          <section className="knowledge-section" key={group.group}>
            <h2>{group.group} Connectors</h2>
            <div className="knowledge-table-wrap">
              <table className="knowledge-table">
                <thead>
                  <tr>
                    <th>Connector</th>
                    <th>Toggle On Unlocks</th>
                    <th>Settings Needed</th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row) => (
                    <tr key={`${group.group}-${row[0]}`}>
                      <td>{row[0]}</td>
                      <td>{row[1]}</td>
                      <td>{row[2]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
