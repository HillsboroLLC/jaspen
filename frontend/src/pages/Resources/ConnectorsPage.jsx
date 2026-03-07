import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const CONNECTORS = [
  { name: 'Jira', state: 'Priority' },
  { name: 'Workfront', state: 'Planned' },
  { name: 'Smartsheets', state: 'Planned' },
];

export default function ConnectorsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-connectors">
      <section className="page-hero page-hero-resources">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Connectors for execution-system alignment</h1>
          <p>Keep initiative context and delivery status synchronized across planning and execution systems.</p>
        </div>
        <div className="hero-abstract connectors-abstract">
          <span>Jira</span>
          <span>Workfront</span>
          <span>Smartsheets</span>
        </div>
      </section>
      <section className="marketing-section">
        <div className="lydia-story lydia-story-connectors">
          <div className="lydia-visual connectors-canvas">
            <div className="connector-core">Jaspen Context</div>
            <div className="connector-node">Jira</div>
            <div className="connector-node">Workfront</div>
            <div className="connector-node">Smartsheets</div>
          </div>
          <article className="lydia-content">
            <h3>Connected systems, one decision context</h3>
            <p>
              Connectors keep planning and execution tools synchronized so teams can maintain context integrity
              from decision framing through delivery tracking.
            </p>
            <ul className="lydia-bullets">
              <li>Bi-directional context consistency across systems</li>
              <li>Reduced handoff and re-entry overhead for operators</li>
              <li>Visibility into delivery signals without tool hopping</li>
            </ul>
          </article>
        </div>
      </section>
      <section className="marketing-section">
        <h2>Connector Matrix</h2>
        <div className="connector-matrix">
          {CONNECTORS.map((connector) => (
            <article key={connector.name} className="connector-cell">
              <h3>{connector.name}</h3>
              <span>{connector.state}</span>
            </article>
          ))}
        </div>
      </section>
      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Implementation fit</h3>
          <p>Connector setup is scoped based on your current PM stack, reporting cadence, and governance requirements.</p>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
