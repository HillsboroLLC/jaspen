import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const CAPABILITIES = [
  {
    title: 'Plans from the decision record',
    detail: 'Jaspen uses the approved direction, constraints, criteria, and assumptions to draft a practical execution plan.',
  },
  {
    title: 'Owners, milestones, and dependencies',
    detail: 'The plan gives teams a starting structure for assignments, sequencing, timelines, and handoffs.',
  },
  {
    title: 'Assumptions stay visible',
    detail: 'Teams can see what the plan depends on, where confidence is stronger, and what needs human review before work begins.',
  },
  {
    title: 'A better handoff into execution',
    detail: 'Jaspen helps reduce the blank-page work after a decision, while your team still owns execution and follow-through.',
  },
];

const CONNECTED = [
  {
    name: 'Jira',
    detail: 'Use Jira alongside Jaspen when your execution plan needs to become issue-based team work.',
    path: '/pages/jaspen-in-jira',
  },
  {
    name: 'Smartsheet',
    detail: 'Use Smartsheet alongside Jaspen when plans, owners, and milestones need operational tracking.',
    path: '/pages/jaspen-in-smartsheets',
  },
];

export default function ProjectManagementPage() {
  return (
    <MarketingPageLayout pageClass="page-project-management page-flat-refresh">
      <Seo
        title="Jaspen Project Management: Execution Plans From Context"
        description="Jaspen turns an approved decision into a full execution plan, with milestones, owners, dependencies, and readiness tracking, without a separate planning step or template."
        canonicalPath="/pages/project-management"
      />
      <section className="page-hero page-hero-pm page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Feature</p>
          <h1>Turn the chosen direction into a plan people can execute.</h1>
          <p>
            Jaspen is first a decision partner. Once a direction is chosen, it helps turn
            that reasoning into milestones, owners, dependencies, and next steps your team can carry out.
          </p>
          <div className="hero-cta-row">
            <Link to="/#pricing-variant-b" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
            <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary-light">View connectors</Link>
          </div>
        </div>
      </section>

      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-pm">
          <article className="lydia-content">
            <h3>Less translation between decision and delivery</h3>
            <p>
              The gap between an approved decision and a usable plan is where momentum often leaks.
              Jaspen helps preserve the context behind the decision so the plan starts from the same
              reasoning, evidence, and constraints.
            </p>
            <ul className="lydia-bullets">
              <li>Plan structure reflects the approved direction, not a generic template</li>
              <li>Original decision rationale stays attached to each milestone</li>
              <li>Teams still review, assign, execute, and adjust the plan themselves</li>
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
          Jaspen can sit beside the tools your delivery teams already use, so the decision record and
          execution plan do not become a separate, forgotten document.
        </p>
        <div className="connected-tools-grid">
          {CONNECTED.map((tool) => (
            <article key={tool.name} className="marketing-card connected-tool-card">
              <h3>{tool.name}</h3>
              <p>{tool.detail}</p>
            <Link to={tool.path} className="connected-tool-link">Learn about the {tool.name} connector</Link>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Start with the decision. Leave with a plan.</h3>
            <p>
              Use Jaspen to decide what deserves your resources, then generate the first version
              of the execution plan your team can own.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/#pricing-variant-b" className="demos-cta-btn demos-cta-btn-primary">View plans</Link>
            <Link to="/pages/resources/demos" className="demos-cta-btn demos-cta-btn-secondary">See a demo</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
