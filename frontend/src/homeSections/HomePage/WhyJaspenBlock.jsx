import React from 'react';
import './WhyJaspenBlock.css';

// Combined color-block section that merges two short beats into one:
//   Left: "Why not just ChatGPT?" the moat, three proofs.
//   Right: "Your criteria" the criteria are yours, three steps.
// Kept intentionally minimal: no cards, no panels inside panels.

// Says what the reader GETS, never how it is produced. "Evidence-capped"
// named the mechanism; a count of supported criteria is a spec sheet nobody
// buys on. Both are replaced by the finding they deliver.
const PROOFS = [
  { label: 'User-owned', text: 'Jaspen proposes; you own the criteria, weights, and decision.' },
  { label: 'Evidence-aware', text: 'You see what rests on evidence and what still rests on assumption.' },
  { label: 'Interrogable', text: 'Every score opens into the evidence and reasoning behind it.' },
];

const STEPS = [
  { title: 'Start with what matters', note: 'Jaspen helps structure the criteria that should drive the decision.' },
  { title: 'Refine it', note: 'Shape the criteria to your priorities, constraints and context.' },
  { title: 'Make trade-offs explicit', note: 'Not every factor matters equally, and you can see how priorities influence the recommendation.' },
];

export default function WhyJaspenBlock() {
  return (
    <section
      className="wjb"
      id="why-jaspen"
      aria-label="Why not just ChatGPT, and your criteria"
    >
      <div className="wjb-inner">
        {/* Why not just ChatGPT */}
        <div className="wjb-panel wjb-panel--dark">
          <div className="wjb-content">
            <p className="wjb-eyebrow wjb-eyebrow--light">Why not just ChatGPT?</p>
            <h2 className="wjb-heading wjb-heading--light">Built to resist AI hallucinations—not hide them.</h2>
            <p className="wjb-sub wjb-sub--light">
              A raw AI chat can sound confident even when an answer is unsupported. Jaspen
              keeps the reasoning inspectable: <strong>code does the scoring math</strong>,
              evidence is graded, assumptions are labeled, and your context grounds the analysis.
            </p>
            <p className="wjb-proof-kicker">Jaspen Is...</p>
            <div className="wjb-points">
              {PROOFS.map((p) => (
                <div className="wjb-point wjb-point--dark" key={p.label}>
                  <p className="wjb-point-title">{p.label}</p>
                  <p className="wjb-point-text wjb-point-text--light">{p.text}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Your criteria */}
        <div className="wjb-panel wjb-panel--light">
          <div className="wjb-content">
            <p className="wjb-eyebrow">Your criteria</p>
            <h2 className="wjb-heading">The criteria are yours.</h2>
            <p className="wjb-sub">
              Jaspen never decides what matters. It helps structure the criteria that should drive
              the decision, then lets you refine them to reflect your priorities, constraints and
              context.
            </p>
            <div className="wjb-points">
              {STEPS.map((s) => (
                <div className="wjb-point wjb-point--light" key={s.title}>
                  <div>
                    <p className="wjb-point-title">{s.title}</p>
                    <p className="wjb-point-text">{s.note}</p>
                  </div>
                </div>
              ))}
            </div>
            <p className="wjb-closing">Jaspen proposes. It never imposes.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
