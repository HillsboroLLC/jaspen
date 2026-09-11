import React from 'react';
import './HowScoreWorks.css';

// Trust section: show what a score RESTS ON, not how the score is produced.
//
// WHAT THIS SECTION MAY AND MAY NOT SAY
//
// It answers the questions a buyer cares about: how much of this rests on
// evidence, where are we assuming, which assumption matters most, what would
// strengthen it. Those are reasons to buy.
//
// It must NOT publish the machinery that answers them. An earlier version
// rendered the confidence ceiling for every grade as live data (100 / 75 / 60
// and 45), the min(judged, ceiling) rule, and worked arithmetic reconciling to
// the overall. Those numbers are the real constants from the scoring engine, so
// the marketing site was handing a competent reader the implementation.
//
// Rule for anyone editing this file: expose the questions Jaspen answers, never
// the mechanics it uses to answer them. No ceilings, no formulas, no
// judged-versus-final arithmetic.

const CRITERIA = [
  { name: 'Market opportunity', evidence: 'Strong evidence', weight: 0.30, share: 88 },
  { name: 'Financial viability', evidence: 'Assumed', weight: 0.25, share: 34, flag: true },
  { name: 'Execution readiness', evidence: 'Moderate evidence', weight: 0.25, share: 66 },
  { name: 'Evidence quality', evidence: 'Thin evidence', weight: 0.20, share: 52 },
];

export default function HowScoreWorks() {
  return (
    <section className="hsw" id="how-score-works">
      <div className="hsw-inner">
        <div className="hsw-header">
          <p className="hsw-eyebrow">How the score works</p>
          <h2 className="hsw-heading">See what the score rests on.</h2>
          <p className="hsw-sub">
            Every recommendation is accompanied by the evidence, assumptions and reasoning
            behind it, so you can understand where the decision is strong and where more
            information could change the answer.
          </p>
        </div>

        <div className="hsw-anatomy">
          <aside className="hsw-summary">
            <p className="hsw-summary-label">Overall score</p>
            <p className="hsw-summary-score">
              <span className="hsw-summary-num">68</span>
              <span className="hsw-summary-denom">/100</span>
            </p>
            <span className="hsw-summary-pill">Good</span>

            <p className="hsw-summary-split">
              <strong>61%</strong> of this decision rests on evidence.
              <br />
              <strong>39%</strong> still rests on assumptions.
            </p>

            <p className="hsw-summary-foot">
              <i className="fa-solid fa-arrows-rotate" aria-hidden="true" />
              Same inputs. Same result.
            </p>
          </aside>

          <div className="hsw-breakdown">
            <div className="hsw-breakdown-head">
              <span className="hsw-col-dim">What it rests on</span>
              <span className="hsw-tag-example">Example</span>
            </div>

            {CRITERIA.map((d) => (
              <div className={`hsw-row${d.flag ? ' is-flagged' : ''}`} key={d.name}>
                <div className="hsw-row-top">
                  <span className="hsw-dim-name">{d.name}</span>
                  <span className={`hsw-conf hsw-conf--${d.evidence.split(' ')[0].toLowerCase()}`}>
                    {d.evidence}
                  </span>
                  <span className="hsw-weight">weight {d.weight.toFixed(2)}</span>
                </div>
                <div className="hsw-bar-track">
                  <span className="hsw-bar-fill" style={{ width: `${d.share}%` }} />
                </div>
              </div>
            ))}

            <p className="hsw-gap-callout">
              <i className="fa-solid fa-lock hsw-gap-icon" aria-hidden="true" />
              <span>
                Financial viability carries a quarter of this decision and nothing verifiable
                supports it yet. It is the assumption most worth resolving before you commit,
                and a more confident argument will not settle it. Better information will.
              </span>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
