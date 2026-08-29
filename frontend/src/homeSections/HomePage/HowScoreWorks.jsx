import React from 'react';
import './HowScoreWorks.css';

// Trust section: prove the methodology by showing a single score decompose,
// including the confidence-cap moment (Constitution Art. 7 + 9). Deliberately
// a new visual device (a "score anatomy" ledger with monospace numerals), not
// a reuse of the BeforeAfter table or the WhyNotChatGPT card grid. Site colors
// only, no gradients, no emojis, Font Awesome icons only. The data is a labeled
// EXAMPLE, not a real customer's figures.

// raw = the model's judged 0-100; cap = the confidence ceiling; weight = the
// user-owned importance. Contribution uses min(raw, cap). One row is capped on
// purpose to teach the mechanism.
// Weights sum to 1.00 and the capped, weighted average lands on exactly 68, so
// the displayed overall genuinely derives from these rows (audit-safe):
// 88*.30 + 45*.25 + 74*.25 + 60*.20 = 68.15 -> 68 (Good, >=60).
const DIMENSIONS = [
  { name: 'Market opportunity', raw: 88, confidence: 'High', cap: 100, weight: 0.30 },
  { name: 'Financial viability', raw: 80, confidence: 'Assumed', cap: 45, weight: 0.25, flag: true },
  { name: 'Execution readiness', raw: 74, confidence: 'Medium', cap: 75, weight: 0.25 },
  { name: 'Evidence quality', raw: 60, confidence: 'Low', cap: 60, weight: 0.20 },
];

export default function HowScoreWorks() {
  return (
    <section className="hsw" id="how-score-works">
      <div className="hsw-inner">
        <div className="hsw-header">
          <p className="hsw-eyebrow">How the score works</p>
          {/* Section deliberately otherwise unchanged. The worked example below,
              judged 80 and capped at 45, is the most persuasive thing on the
              site and needs no rewrite. Only the heading moves, from describing
              a capability to naming what the reader gets. */}
          <h2 className="hsw-heading">Every number tells you how much of it is evidence.</h2>
          <p className="hsw-sub">
            A Jaspen score is never a single opaque figure. It is assembled from parts you can
            inspect: what the evidence says, how much each factor matters to you, and how sure
            the evidence actually is.
          </p>
        </div>

        <div className="hsw-anatomy">
          {/* Left: the computed result */}
          <aside className="hsw-summary">
            <p className="hsw-summary-label">Overall score</p>
            <p className="hsw-summary-score">
              <span className="hsw-summary-num">68</span>
              <span className="hsw-summary-denom">/100</span>
            </p>
            <span className="hsw-summary-pill">Good</span>

            <p className="hsw-summary-foot">
              <i className="fa-solid fa-arrows-rotate" aria-hidden="true" />
              Same inputs, same result. A re-run is an audit, not a reroll.
            </p>
          </aside>

          {/* Right: the parts that made it */}
          <div className="hsw-breakdown">
            <div className="hsw-breakdown-head">
              <span className="hsw-col-dim">The parts that made it</span>
              <span className="hsw-tag-example">Example</span>
            </div>

            {DIMENSIONS.map((d) => {
              const scored = Math.min(d.raw, d.cap);
              return (
                <div className={`hsw-row${d.flag ? ' is-flagged' : ''}`} key={d.name}>
                  <div className="hsw-row-top">
                    <span className="hsw-dim-name">{d.name}</span>
                    <span className={`hsw-conf hsw-conf--${d.confidence.toLowerCase()}`}>{d.confidence}</span>
                    <span className="hsw-weight">weight {d.weight.toFixed(2)}</span>
                  </div>
                  <div className="hsw-bar-track">
                    <span className="hsw-bar-fill" style={{ width: `${scored}%` }} />
                    {d.cap < d.raw && (
                      <span
                        className="hsw-bar-lost"
                        style={{ left: `${d.cap}%`, width: `${d.raw - d.cap}%` }}
                      />
                    )}
                  </div>
                  <div className="hsw-row-values">
                    <span className="hsw-value-num">{scored}</span>
                    {d.cap < d.raw && (
                      <span className="hsw-value-note">judged {d.raw}, capped at {d.cap}</span>
                    )}
                  </div>
                </div>
              );
            })}

            <p className="hsw-cap-callout">
              <i className="fa-solid fa-lock hsw-cap-icon" aria-hidden="true" />
              <span>
                Financial viability was judged 80, but there is no data behind it yet, so its
                confidence is <strong>Assumed</strong> and it is capped at 45. A stronger pitch
                cannot raise it. Only stronger evidence can.
              </span>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
