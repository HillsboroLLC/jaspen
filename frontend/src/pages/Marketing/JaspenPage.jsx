import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from './MarketingPageLayout';

const STAGES = [
  {
    num: '01',
    title: 'Clarify',
    detail: 'Define the problem, surface constraints, and establish what a successful outcome actually looks like before any analysis begins.',
  },
  {
    num: '02',
    title: 'Decide',
    detail: 'Generate options, compare tradeoffs side by side, and produce a scored recommendation your team can act on with confidence.',
  },
  {
    num: '03',
    title: 'Plan',
    detail: 'Convert approved direction into an owner-ready execution plan with milestones, dependencies, and a delivery timeline built in.',
  },
  {
    num: '04',
    title: 'Execute',
    detail: 'Track progress, monitor delivery risk, and keep leadership aligned with structured status signals as the work unfolds.',
  },
];

const OUTPUTS = [
  {
    title: 'Scored decision artifacts',
    detail: 'Every recommendation comes with a Jaspen Score — a weighted signal across strategic fit, execution readiness, and impact potential — so teams prioritize with evidence, not instinct.',
  },
  {
    title: 'Structured execution plans',
    detail: 'Jaspen generates a full work breakdown structure from approved direction, with tasks, owners, timelines, and dependency sequencing ready for immediate delivery.',
  },
  {
    title: 'Readiness and risk signals',
    detail: 'As execution progresses, Jaspen monitors confidence against original plan assumptions and surfaces emerging risk before it becomes a delivery failure.',
  },
  {
    title: 'Leadership-ready briefings',
    detail: 'Generate structured status updates from live initiative context — formatted for executive review without manual assembly from scattered sources.',
  },
];

const AUDIENCES = [
  {
    role: 'Strategy leads',
    detail: 'Ground decisions in structured analysis instead of slide decks. Walk away with a scored recommendation and a plan already built.',
  },
  {
    role: 'Program managers',
    detail: 'Start execution with an owner-ready plan tied to the original decision — no translation step, no blank spreadsheet.',
  },
  {
    role: 'Cross-functional teams',
    detail: 'One workspace keeps context, decisions, and delivery progress connected so teams stop rebuilding shared understanding at every handoff.',
  },
  {
    role: 'Executives',
    detail: 'Receive interpretable confidence signals, not raw data. See where initiatives are strong and where risk is emerging in one view.',
  },
];

export default function JaspenPage() {
  return (
    <MarketingPageLayout pageClass="page-jaspen">
      <section className="page-hero page-hero-jaspen">
        <div className="hero-copy">
          <p className="hero-kicker">Product</p>
          <h1>One agent for the full decision-to-execution arc</h1>
          <p>
            Jaspen connects the work of clarifying problems, comparing options, building plans, and
            tracking delivery — so teams stop losing ground between strategy and execution.
          </p>
          <div className="hero-cta-row">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">See plans</Link>
            <Link to="/pages/jaspen-score" className="demos-cta-btn demos-cta-btn-secondary-light">How scoring works</Link>
          </div>
        </div>
        <div className="hero-abstract jaspen-abstract">
          <div className="jaspen-arc-node">Clarify</div>
          <div className="jaspen-arc-node">Decide</div>
          <div className="jaspen-arc-node">Plan</div>
          <div className="jaspen-arc-node">Execute</div>
        </div>
      </section>

      <section className="marketing-section">
        <h2>The four-stage flow</h2>
        <p className="section-subhead">
          Jaspen guides teams through a connected sequence from problem framing to delivery — producing
          decision-grade artifacts at every stage instead of notes and summaries.
        </p>
        <div className="jaspen-stages-grid">
          {STAGES.map((stage) => (
            <article key={stage.num} className="marketing-card jaspen-stage-card">
              <span className="jaspen-stage-num">{stage.num}</span>
              <h3>{stage.title}</h3>
              <p>{stage.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <div className="lydia-story lydia-story-jaspen">
          <div className="lydia-visual jaspen-context-visual">
            <div className="context-ring">
              <div className="context-ring-label">Cohesive Context Engine</div>
              <div className="context-chip">Strategic framing</div>
              <div className="context-chip">Tradeoff scoring</div>
              <div className="context-chip">Execution plan</div>
              <div className="context-chip">Delivery signals</div>
            </div>
          </div>
          <article className="lydia-content">
            <h3>Context that carries through the full arc</h3>
            <p>
              Most tools break the chain between strategy and delivery. Jaspen's cohesive context engine keeps
              the original framing, decision rationale, and execution plan connected — so teams aren't
              rebuilding shared understanding at every handoff.
            </p>
            <ul className="lydia-bullets">
              <li>Decision rationale stays attached to the delivery plan</li>
              <li>Scoring updates as execution context changes</li>
              <li>One workspace replaces the chain of disconnected documents</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>What Jaspen produces</h2>
        <div className="marketing-grid">
          {OUTPUTS.map((output) => (
            <article key={output.title} className="marketing-card">
              <h3>{output.title}</h3>
              <p>{output.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <h2>Built for teams that need both speed and structure</h2>
        <div className="audience-grid">
          {AUDIENCES.map((a) => (
            <article key={a.role} className="marketing-card audience-card">
              <h3>{a.role}</h3>
              <p>{a.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>Ready to see it in your workflow?</h3>
            <p>
              Start with a free account or request a walkthrough built around your operating context.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/pages/pricing" className="demos-cta-btn demos-cta-btn-primary">View plans</Link>
            <Link to="/pages/resources/demos" className="demos-cta-btn demos-cta-btn-secondary">Request a demo</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
