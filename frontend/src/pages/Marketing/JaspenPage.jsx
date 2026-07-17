import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const FLOW_STEPS = [
  {
    label: 'Frame',
    title: 'Name the decision clearly',
    detail: 'Jaspen helps turn a loose question into a decision with criteria, constraints, and the evidence you need to examine.',
  },
  {
    label: 'Compare',
    title: 'Pressure-test the options',
    detail: 'Options are weighed against the criteria you choose, so tradeoffs become easier to see and easier to explain.',
  },
  {
    label: 'Decide',
    title: 'Preserve the reasoning',
    detail: 'The recommendation carries the why with it: evidence, assumptions, confidence, risks, and what would change the answer.',
  },
  {
    label: 'Act',
    title: 'Move into execution',
    detail: 'Once the direction is clear, Jaspen can help structure the work into owners, milestones, dependencies, and follow-up signals.',
  },
];

const CONTEXT_TYPES = [
  {
    title: 'Decision context',
    detail: 'Goals, constraints, tradeoffs, assumptions, risks, criteria, and the reason the decision matters.',
  },
  {
    title: 'Execution context',
    detail: 'Project plans, tasks, status signals, ownership, delivery risk, and updates from systems such as Jira or Smartsheet.',
  },
  {
    title: 'Business context',
    detail: 'Customer notes, CRM signals, documents, spreadsheets, financial inputs, and data sources that shape the decision.',
  },
];

const OUTPUTS = [
  'A clearer decision question',
  'Weighted criteria you can edit',
  'Evidence-capped scoring',
  'Assumptions worth testing',
  'Tradeoffs and risks',
  'A decision record you can revisit',
  'An execution plan',
  'Status signals as work moves forward',
];

export default function JaspenPage() {
  return (
    <MarketingPageLayout pageClass="page-jaspen page-jaspen-refresh">
      <Seo
        title="Jaspen: A Thought Partner for Decisions and Execution"
        description="See how Jaspen helps you frame important decisions, compare tradeoffs, preserve reasoning, and move from decision to execution with connected context."
        canonicalPath="/pages/jaspen"
      />

      <section className="page-hero page-hero-jaspen jaspen-product-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Jaspen</p>
          <h1>A thought partner for decisions that need structure.</h1>
          <p>
            Jaspen helps you work through important decisions with clearer criteria,
            connected context, evidence-aware scoring, and a record of why the decision was made.
          </p>
          <div className="hero-cta-row">
            <Link to="/#pricing-variant-b" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
            <Link to="/pages/jaspen-score" className="demos-cta-btn demos-cta-btn-secondary-light">See how scoring works</Link>
          </div>
        </div>
      </section>

      <section className="marketing-section jaspen-flat-section">
        <div className="jaspen-section-heading">
          <p className="hero-kicker">How it works</p>
          <h2>From unclear question to usable decision record.</h2>
          <p>
            Jaspen is not trying to decide for you. It gives your thinking a structure,
            then keeps the evidence and reasoning attached as the decision moves forward.
          </p>
        </div>

        <div className="jaspen-flow-grid">
          {FLOW_STEPS.map((step) => (
            <article key={step.label} className="jaspen-flow-card">
              <span>{step.label}</span>
              <h3>{step.title}</h3>
              <p>{step.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section jaspen-context-section">
        <div className="jaspen-context-copy">
          <p className="hero-kicker">Context</p>
          <h2>Built for more than project management.</h2>
          <p>
            Project tools matter, but they are only one part of the picture. Jaspen is designed
            to work with the context around a decision: plans, data, notes, documents, customers,
            constraints, and the assumptions people usually leave unstated.
          </p>
          <Link to="/pages/resources/connectors" className="demos-cta-btn demos-cta-btn-secondary-light">Explore connectors</Link>
        </div>

        <div className="jaspen-context-list">
          {CONTEXT_TYPES.map((item) => (
            <article key={item.title} className="jaspen-context-row">
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section jaspen-output-section">
        <div className="jaspen-section-heading">
          <p className="hero-kicker">Outputs</p>
          <h2>What you should walk away with.</h2>
          <p>
            The goal is not a prettier chat transcript. It is a practical set of decision artifacts
            you can use, explain, and return to later.
          </p>
        </div>

        <div className="jaspen-output-list">
          {OUTPUTS.map((output) => (
            <div key={output} className="jaspen-output-item">
              {output}
            </div>
          ))}
        </div>
      </section>

      <section className="marketing-section jaspen-final-band">
        <div>
          <p className="hero-kicker">Start simple</p>
          <h2>Bring one real decision into Jaspen.</h2>
          <p>
            Use the free plan to try Jaspen on something real. Upgrade when the decision needs
            more room for evidence, assumptions, tradeoffs, and a record you can defend.
          </p>
        </div>
        <div className="demos-cta-actions">
          <Link to="/#pricing-variant-b" className="demos-cta-btn demos-cta-btn-primary">Get started</Link>
          <Link to="/pages/resources/demos" className="demos-cta-btn demos-cta-btn-secondary">Request a demo</Link>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
