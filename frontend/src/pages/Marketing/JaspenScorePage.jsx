import React from 'react';
import { Helmet } from 'react-helmet-async';
import MarketingPageLayout from './MarketingPageLayout';
import Seo from '../../shared/components/Seo';

// SEO pillar page for the branded term "Jaspen Score" and the broader intent
// "how to score / prioritize decisions". Content is accurate to the Decision
// Intelligence Framework and Constitution: six weighted dimensions, criteria
// the user owns, confidence caps enforced in code, deterministic rollup.
// Reuses existing MarketingPages.css classes. No em dashes, no emojis, site
// palette only.

// Balanced-profile weights (sum to 1.00), straight from the framework.
const DIMENSIONS = [
  { title: 'Market opportunity', weight: 0.18, score: 82, detail: 'The size and reachability of the opportunity the option is aimed at.' },
  { title: 'Financial viability', weight: 0.20, score: 70, detail: 'Whether the economics hold up: cost, return, and the assumptions behind them.' },
  { title: 'Execution readiness', weight: 0.18, score: 76, detail: 'How ready the team, plan, and dependencies are to actually deliver it.' },
  { title: 'Strategic alignment', weight: 0.16, score: 80, detail: 'How well the option serves the direction you have already committed to.' },
  { title: 'Risk profile', weight: 0.16, score: 68, detail: 'The exposure the option carries and how much of it is inside your control.' },
  { title: 'Evidence quality', weight: 0.12, score: 61, detail: 'How strong the support is. A decision built on thin evidence is penalized for that thinness, on purpose.' },
];

const CONFIDENCE = [
  { level: 'High', cap: 100, meaning: 'Backed by evidence in front of you.' },
  { level: 'Medium', cap: 75, meaning: 'A reasonable inference from what you know.' },
  { level: 'Low', cap: 60, meaning: 'Limited signal so far.' },
  { level: 'Assumed', cap: 45, meaning: 'No direct evidence yet, so it is labeled and bounded.' },
];

const FAQS = [
  {
    q: 'What is the Jaspen Score?',
    a: 'The Jaspen Score is a structured way to compare options using the criteria, evidence, weights, and confidence available for a decision. It helps you see why one option appears stronger than another without pretending the number is the whole answer.',
  },
  {
    q: 'How is the Jaspen Score calculated?',
    a: 'Each criterion receives a judgment based on the evidence available, plus a confidence level. Confidence caps the contribution before weighting, so an assumption cannot carry the same influence as direct evidence. The weighted values roll up into a score you can inspect, question, and revise.',
  },
  {
    q: 'What are the six dimensions?',
    a: 'Market opportunity, financial viability, execution readiness, strategic alignment, risk profile, and evidence quality. These six are a default starter rubric, not a fixed set. You can change them when the decision needs a different lens.',
  },
  {
    q: 'Can I change the criteria Jaspen scores on?',
    a: 'Yes. The six default dimensions are only a starting point. Jaspen proposes a rubric so you are not starting from a blank page, but you can edit the criteria and their weights, or define your own set of up to twelve weighted criteria. The criteria always belong to you; Jaspen never imposes them.',
  },
  {
    q: 'How is it different from a weighted decision matrix or a spreadsheet?',
    a: 'A spreadsheet can calculate weighted totals, but it usually does not help you expose weak evidence, hidden assumptions, or missing context. Jaspen keeps the reasoning attached to the score so you can understand what is driving the result. You still own the criteria and the weights.',
  },
  {
    q: 'Does connecting more data change the score?',
    a: 'Connecting data does not decide what matters. It can strengthen the evidence behind specific criteria and make the confidence level more reliable. You can still use Jaspen without connected data when you are working from notes, documents, or judgment.',
  },
];

const faqJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: FAQS.map((f) => ({
    '@type': 'Question',
    name: f.q,
    acceptedAnswer: { '@type': 'Answer', text: f.a },
  })),
};

export default function JaspenScorePage() {
  return (
    <MarketingPageLayout pageClass="page-score page-flat-refresh">
      <Seo
        title="What Is the Jaspen Score"
        description="The Jaspen Score helps compare options with criteria, evidence, weights, and confidence so important decisions are easier to inspect and explain."
        canonicalPath="/pages/jaspen-score"
        type="article"
      />
      <Helmet>
        <script type="application/ld+json">{JSON.stringify(faqJsonLd)}</script>
      </Helmet>

      <section className="page-hero page-hero-score page-flat-hero">
        <div className="hero-copy">
          <p className="hero-kicker">The methodology</p>
          <h1>A score you can inspect, not just accept.</h1>
          <p>
            The Jaspen Score helps compare options using your criteria, the evidence you have,
            and the confidence behind that evidence. It is there to support the decision,
            not replace your judgment.
          </p>
        </div>
      </section>

      <section className="marketing-section">
        <div className="score-intro-layout">
          <article className="scorecard-shell">
            <div className="scorecard-head">
              <p>JASPEN SCORECARD</p>
              <span>Illustrative example</span>
            </div>
            <div className="scorecard-main">
              <div className="score-ring-wrap">
                <div className="score-ring">
                  <span>73</span>
                  <small>Overall</small>
                </div>
                <div className="scorecard-readiness">Evidence-led</div>
              </div>
              <div className="scorecard-rows">
                {DIMENSIONS.map((d) => (
                  <div key={`row-${d.title}`} className="scorecard-row">
                    <span>{d.title}</span>
                    <div className="scorecard-bar-track">
                      <div className="scorecard-bar-fill" style={{ '--score-width': `${d.score}%` }}></div>
                    </div>
                    <strong>{d.score}</strong>
                  </div>
                ))}
              </div>
            </div>
            <p className="scorecard-footnote">
              The score is a structured read on the current evidence. Better inputs should make the reasoning clearer.
            </p>
          </article>
          <article className="score-guidance-panel">
            <h3>What the score helps with</h3>
            <ul className="score-guidance-list">
              <li>Compare options on the same decision criteria</li>
              <li>See exactly where a decision is strong or fragile</li>
              <li>Explain the reasoning behind a resource choice</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section flat-navy-section">
        <div className="lydia-story lydia-story-score">
          <article className="lydia-content">
            <h3>Why the number is useful</h3>
            <p>
              A raw AI chat can sound confident without showing why. Jaspen keeps the score tied
              to criteria, evidence, weights, and confidence so you can see what is driving the
              recommendation before you spend money, time, attention, or team capacity.
            </p>
            <ul className="lydia-bullets">
              <li>Reproducible: the same inputs produce the same score</li>
              <li>Explainable: every score traces back to reasoning</li>
              <li>Useful: the result helps you choose where resources should go</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>The rubric is yours</h2>
        <p className="section-lead">
          Every decision is different, so the criteria should be too. Jaspen proposes a sensible
          starter rubric based on your objective, then you approve it, edit it, or replace it
          with your own. You can define up to twelve weighted criteria that capture exactly what
          matters for this call. Jaspen proposes. It never imposes.
        </p>
        <div className="score-pillars-grid">
          <article className="score-pillar-card">
            <div className="score-pillar-head"><h3>Jaspen proposes</h3></div>
            <p>A starter rubric tuned to your objective, ready in seconds, so you are never staring at a blank page.</p>
          </article>
          <article className="score-pillar-card">
            <div className="score-pillar-head"><h3>You adjust</h3></div>
            <p>Change the criteria and the weights until they match how you actually make this decision.</p>
          </article>
          <article className="score-pillar-card">
            <div className="score-pillar-head"><h3>It stays yours</h3></div>
            <p>Data and models inform the sub-scores. They never choose what matters. That is your call.</p>
          </article>
        </div>
      </section>

      <section className="marketing-section">
        <h2>The default dimensions</h2>
        <p className="section-lead">
          Not sure where to start? Jaspen begins you with six well-tested default dimensions.
          Keep them as they are, reweight them for this decision, or swap them for your own.
        </p>
        <div className="score-pillars-grid">
          {DIMENSIONS.map((d) => (
            <article key={d.title} className="score-pillar-card">
              <div className="score-pillar-head">
                <h3>{d.title}</h3>
                <span>{d.weight.toFixed(2)}</span>
              </div>
              <p>{d.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <h2>Confidence caps: enthusiasm cannot outrun evidence</h2>
        <p className="section-lead">
          Every dimension carries a confidence level, and that level caps how much it can
          contribute before weighting. A confident guess with no evidence behind it is held to 45
          points, no matter how good the pitch sounds. Better evidence raises the ceiling.
        </p>
        <div className="score-pillars-grid">
          {CONFIDENCE.map((c) => (
            <article key={c.level} className="score-pillar-card">
              <div className="score-pillar-head">
                <h3>{c.level}</h3>
                <span>{c.cap}</span>
              </div>
              <p>{c.meaning}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section">
        <h2>Frequently asked questions</h2>
        <div className="score-faq">
          {FAQS.map((f) => (
            <article key={f.q} className="score-faq-item">
              <h3>{f.q}</h3>
              <p>{f.a}</p>
            </article>
          ))}
        </div>
      </section>
    </MarketingPageLayout>
  );
}
