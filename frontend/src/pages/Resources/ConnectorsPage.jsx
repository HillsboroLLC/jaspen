import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const EXECUTION_CONNECTORS = [
  { name: 'Jira', state: 'All plans', path: '/pages/jaspen-in-jira' },
  { name: 'Smartsheet', state: 'All plans', path: '/pages/jaspen-in-smartsheets' },
];

const DATA_CONNECTORS = [
  { name: 'Snowflake', state: 'All plans' },
  { name: 'Salesforce', state: 'All plans' },
  { name: 'Oracle Fusion', state: 'All plans' },
];

const NEXT_WAVE_CONNECTORS = [
  { name: 'ServiceNow', state: 'Planned' },
  { name: 'NetSuite', state: 'Planned' },
];

export default function ConnectorsPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-connectors page-flat-refresh">
      <Seo
        title="Jaspen Connectors: Execution and Data Integrations"
        description="See which execution connectors (Jira, Smartsheet) and data connectors (Snowflake, Salesforce, Oracle Fusion) are available on every Jaspen plan today."
        canonicalPath="/pages/resources/connectors"
      />
      <section className="page-hero page-hero-resources page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>Connect the information behind better decisions.</h1>
          <p>
            Connectors help Jaspen work with more of the context around a decision: project plans,
            operating data, customer signals, financial inputs, and the tools teams use after a plan exists.
          </p>
        </div>
      </section>
      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-connectors">
          <article className="lydia-content">
            <h3>What connectors do</h3>
            <p>
              Connectors are prebuilt links between Jaspen and the systems that hold useful decision context.
              Some support execution planning. Others help Jaspen reason with business, customer, finance,
              or operations data.
            </p>
            <ul className="lydia-bullets">
              <li>Execution connectors help carry a plan into project and operations tools</li>
              <li>Data connectors bring operating signals into decision analysis</li>
              <li>Connector access is available on every plan; paid tiers add more thinking power and capacity</li>
            </ul>
          </article>
        </div>
      </section>
      <section className="marketing-section">
        <h2>Connector launch scope</h2>
        <div className="connector-group-grid">
          <article className="connector-group-card">
            <h3>Execution connectors</h3>
            <p>Use these after a decision when the plan needs to move into tools your team already uses.</p>
            <div className="connector-matrix">
              {EXECUTION_CONNECTORS.map((connector) => (
                <article key={connector.name} className="connector-cell">
                  <h3>
                    {connector.path ? (
                      <Link to={connector.path}>{connector.name}</Link>
                    ) : (
                      connector.name
                    )}
                  </h3>
                  <span>{connector.state}</span>
                </article>
              ))}
            </div>
          </article>

          <article className="connector-group-card">
            <h3>Data connectors</h3>
            <p>Use these to bring more evidence into prioritization, tradeoff analysis, and resource decisions.</p>
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
