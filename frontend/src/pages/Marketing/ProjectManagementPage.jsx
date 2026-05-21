import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';

const CAPABILITIES = [
  {
    title: 'Work plans from context',
    detail: 'Jaspen reads the initiative framing, constraints, and approved direction — then generates a full work breakdown structure with tasks, phases, and sequencing already in place.',
  },
  {
    title: 'Owner and timeline assignment',
    detail: 'Each task includes an owner slot, estimated duration, and dependency map so teams can start assigning work immediately without a separate planning session.',
  },
  {
    title: 'Delivery confidence scoring',
    detail: 'Plan quality is scored in real time against readiness signals — giving teams an early view of where confidence is strong and where assumptions need testing before delivery begins.',
  },
  {
    title: 'Dependency and blocker detection',
    detail: 'Jaspen surfaces sequencing conflicts and blocked dependencies as they emerge — before they become the reason a milestone slips.',
  },
];

const CONNECTED = [
  {
    name: 'Jira',
    detail: 'Push execution plan tasks to Jira as issues and sync delivery status back into the Jaspen workspace automatically.',
    path: '/pages/jaspen-in-jira',
  },
  {
    name: 'Smartsheet',
    detail: 'Map milestones to Smartsheet rows and pull operational progress back into Jaspen\'s readiness view without manual rework.',
    path: '/pages/jaspen-in-smartsheets',
  },
];

export default function ProjectManagementPage() {
  return (
    <MarketingPageLayout pageClass="page-project-management">
      <section className="page-hero page-hero-pm">
        <div className="hero-copy">
          <p className="hero-kicker">Feature</p>
          <h1>Execution plans built from context, not templates</h1>
          <p>
            Jaspen generates structured work plans directly from initiative decisions — with milestones,
            owners, dependencies, and readiness tracking built in from day one.
          </p>
          <div className="hero-cta-row">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary-light">View connectors</Link>
          </div>
        </div>
        <div className="hero-abstract pm-abstract">
          <div className="pm-wbs-node pm-wbs-root">Initiative</div>
          <div className="pm-wbs-row">
            <div className="pm-wbs-node">Milestone 1</div>
            <div className="pm-wbs-node">Milestone 2</div>
            <div className="pm-wbs-node">Milestone 3</div>
          </div>
        </div>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-pm">
          <div className="lydia-visual pm-flow-visual">
            <div className="pm-flow-step">
              <span>01</span>
              <p>Approved decision</p>
            </div>
            <div className="pm-flow-arrow">→</div>
            <div className="pm-flow-step">
              <span>02</span>
              <p>WBS generated</p>
            </div>
            <div className="pm-flow-arrow">→</div>
            <div className="pm-flow-step">
              <span>03</span>
              <p>Delivery tracked</p>
            </div>
          </div>
          <article className="lydia-content">
            <h3>No translation step between strategy and delivery</h3>
            <p>
              The gap between an approved decision and a managed execution plan is where most initiatives
              lose momentum. Jaspen closes that gap by generating the plan from the same context that
              produced the decision — so nothing is lost in translation.
            </p>
            <ul className="lydia-bullets">
              <li>Plan structure reflects the approved direction, not a generic template</li>
              <li>Original decision rationale stays attached to each milestone</li>
              <li>Teams start executing with context, not catch-up conversations</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>What project management in Jaspen includes</h2>
        <div className="marketing-grid">
          {CAPABILITIES.map((cap) => (
            <article key={cap.title} className="marketing-card">
              <h3>{cap.title}</h3>
              <p>{cap.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <h2>Connected to where work happens</h2>
        <p className="section-subhead">
          Jaspen execution plans sync with the tools your delivery teams already use — so you don't have
          to maintain a separate tracking system.
        </p>
        <div className="connected-tools-grid">
          {CONNECTED.map((tool) => (
            <article key={tool.name} className="marketing-card connected-tool-card">
              <h3>{tool.name}</h3>
              <p>{tool.detail}</p>
              <Link to={tool.path} className="connected-tool-link">Learn about the {tool.name} connector →</Link>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Start your next initiative with a plan already built</h3>
            <p>
              Jaspen generates the execution plan as part of the decision workflow — no extra step required.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">View plans</Link>
            <Link to="/pages/resources/demos" className="demos-cta-btn demos-cta-btn-secondary">See a demo</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
