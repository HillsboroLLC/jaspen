import React from 'react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';

const EXECUTION_CONNECTORS = [
  { name: 'Jira', state: 'Essential' },
  { name: 'Workfront', state: 'Essential' },
  { name: 'Smartsheet', state: 'Essential' },
];

const DATA_CONNECTORS = [
  { name: 'Snowflake', state: 'Essential' },
  { name: 'Salesforce', state: 'Essential' },
  { name: 'Oracle Fusion', state: 'Essential' },
];

const NEXT_WAVE_CONNECTORS = [
  { name: 'ServiceNow', state: 'Planned' },
  { name: 'NetSuite', state: 'Planned' },
];

export default function ConnectorsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-connectors">
      <section className="page-hero page-hero-resources">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Essential connectors for execution and data intelligence</h1>
          <p>
            Start with a focused connector set so Jaspen can sync plans with project tools and surface pattern-based
            recommendations from your business data.
          </p>
        </div>
        <div className="hero-abstract connectors-abstract">
          <span>Jira</span>
          <span>Workfront</span>
          <span>Snowflake</span>
          <span>Salesforce</span>
          <span>Oracle Fusion</span>
        </div>
      </section>
      <section className="marketing-section">
        <div className="lydia-story lydia-story-connectors">
          <div className="lydia-visual connectors-canvas">
            <div className="connector-core">Jaspen Context</div>
            <div className="connector-node">Execution Tools</div>
            <div className="connector-node">Data Systems</div>
            <div className="connector-node">Insight Engine</div>
          </div>
          <article className="lydia-content">
            <h3>How connectors and API work together</h3>
            <p>
              Connectors are prebuilt integrations for fast setup. The API is for custom enterprise workflows that go
              beyond those prebuilt connectors.
            </p>
            <ul className="lydia-bullets">
              <li>Execution connectors support plan updates and status sync</li>
              <li>Data connectors support trend detection and recommendation generation</li>
              <li>API supports custom logic and system-specific extensions</li>
            </ul>
          </article>
        </div>
      </section>
      <section className="marketing-section">
        <h2>Connector Launch Scope</h2>
        <div className="connector-group-grid">
          <article className="connector-group-card">
            <h3>Execution connectors</h3>
            <p>Use these to update delivery plans, owners, and statuses from Jaspen.</p>
            <div className="connector-matrix">
              {EXECUTION_CONNECTORS.map((connector) => (
                <article key={connector.name} className="connector-cell">
                  <h3>{connector.name}</h3>
                  <span>{connector.state}</span>
                </article>
              ))}
            </div>
          </article>

          <article className="connector-group-card">
            <h3>Data connectors</h3>
            <p>Use these for pattern analysis and insight generation from operating data.</p>
            <div className="connector-matrix">
              {DATA_CONNECTORS.map((connector) => (
                <article key={connector.name} className="connector-cell">
                  <h3>{connector.name}</h3>
                  <span>{connector.state}</span>
                </article>
              ))}
            </div>
          </article>
        </div>
      </section>
      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Phased rollout guidance</h3>
          <p>
            Start with the essential connector set above, then add next-wave systems as usage patterns stabilize.
            Current next-wave targets: {NEXT_WAVE_CONNECTORS.map((item) => item.name).join(' and ')}.
          </p>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
