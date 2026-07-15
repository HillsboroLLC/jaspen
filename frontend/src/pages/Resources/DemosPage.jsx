import React from 'react';
import { Link } from 'react-router-dom';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';
import Seo from '../../shared/components/Seo';

const DEMOS = [
  {
    title: 'Decision Flow',
    detail: 'See how a real question becomes options, criteria, tradeoffs, and a reasoned recommendation.',
    duration: '~12 min',
    audience: 'Founders, leaders, operators',
  },
  {
    title: 'Execution Plan Build',
    detail: 'Watch an approved direction turn into milestones, owners, dependencies, and a first plan.',
    duration: '~18 min',
    audience: 'PMO, operations, team leads',
  },
  {
    title: 'Evidence and Assumption Review',
    detail: 'Understand how Jaspen keeps the reasoning visible before and after the decision.',
    duration: '~10 min',
    audience: 'Decision owners, advisors',
  },
];

export default function DemosPage() {
  return (
    <MarketingPageLayout pageClass="page-resources page-demos page-flat-refresh">
      <Seo
        title="Jaspen Product Demos: Decision and Execution Walkthroughs"
        description="Watch walkthroughs of Jaspen's decision framing, execution planning, and readiness scoring in action, sequenced to help teams evaluate fit before rollout."
        canonicalPath="/pages/resources/demos"
      />
      <section className="page-hero page-hero-resources page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">Resources</p>
          <h1>See how Jaspen helps from idea to execution plan.</h1>
          <p>
            Use the demos to see how Jaspen helps compare choices, preserve reasoning,
            and generate the plan that comes after a decision.
          </p>
        </div>
      </section>
      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-demos">
          <article className="lydia-content">
            <h3>Walkthroughs built around real decisions</h3>
            <p>
              Demos should show the whole shape of the product: deciding what deserves attention,
              understanding why, and turning the chosen direction into a plan people can execute.
            </p>
            <ul className="lydia-bullets">
              <li>Scenario-led flow instead of disconnected feature fragments</li>
              <li>Decision reasoning and execution planning shown in one sequence</li>
              <li>Clear separation between what Jaspen recommends and what people execute</li>
            </ul>
          </article>
        </div>
      </section>
      <section className="marketing-section">
        <div className="resource-callout">
          <h3>Recommended order</h3>
          <p>Start with Decision Flow, then Execution Plan Build, then Evidence and Assumption Review for a complete picture of the journey.</p>
        </div>
      </section>
      <section className="marketing-section">
        <h2>Demo Library</h2>
        <div className="resource-track">
          {DEMOS.map((demo, idx) => (
            <article key={demo.title} className="resource-card demo-card">
              <span className="resource-index">0{idx + 1}</span>
              <h3>{demo.title}</h3>
              <p>{demo.detail}</p>
              <div className="demo-card-meta">
                <span>{demo.duration}</span>
                <span>{demo.audience}</span>
              </div>
            </article>
          ))}
        </div>
      </section>
      <section className="marketing-section">
        <div className="demos-cta-block">
          <div className="demos-cta-copy">
            <h3>See Jaspen in action with your team</h3>
            <p>
              Request a walkthrough around the kind of decision you are trying to make and the plan
              you need to create after it.
            </p>
          </div>
          <div className="demos-cta-actions">
            <Link to="/login" className="demos-cta-btn demos-cta-btn-primary">Request a walkthrough</Link>
            <Link to="/pages/resources/tutorials" className="demos-cta-btn demos-cta-btn-secondary">Read the tutorials</Link>
          </div>
        </div>
      </section>
    </MarketingPageLayout>
  );
}
