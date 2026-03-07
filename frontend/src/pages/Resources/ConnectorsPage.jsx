import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const CONNECTORS = [
  { name: 'Jira', state: 'Priority' },
  { name: 'Workfront', state: 'Planned' },
  { name: 'Smartsheets', state: 'Planned' },
];

export default function ConnectorsPage() {
  return (
    <MarketingPageLayout
      eyebrow="RESOURCES"
      title="Connectors for execution-system alignment"
      subtitle="Keep initiative context and delivery status synchronized across planning and execution systems."
    >
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
