import React from 'react';
import './WhyJaspenBlock.css';

// Combined color-block section that merges two short beats into one:
//   Left (navy): "Why not just ChatGPT?" the moat, three proofs.
//   Right (pale blue): "Your criteria" the rubric is yours, three steps.
// Kept intentionally minimal: no cards, no panels inside panels.

const PROOFS = [
  { label: 'Reproducible', text: 'Same inputs, same answer, every time.' },
  { label: 'Evidence-capped', text: 'It cannot sound more certain than the evidence allows.' },
  { label: 'Shows its work', text: 'Every score breaks down into the facts behind it.' },
];

const STEPS = [
  { icon: 'fa-lightbulb', title: 'Jaspen proposes', note: 'A sensible starter rubric, tuned to your objective.' },
  { icon: 'fa-sliders', title: 'You adjust', note: 'Reweight, rename, or replace the criteria. Up to twelve.' },
  { icon: 'fa-user-check', title: 'It stays yours', note: 'Data informs the scores. It never picks what matters.' },
];

export default function WhyJaspenBlock() {
  return (
    <section
      className="wjb"
      id="why-jaspen"
      aria-label="Why not just ChatGPT, and your criteria"
    >
      <div className="wjb-inner">
        {/* Left half: Why not just ChatGPT */}
        <div className="wjb-panel wjb-panel--dark">
          <div className="wjb-content">
            <p className="wjb-eyebrow wjb-eyebrow--light">Why not just ChatGPT?</p>
            <h2 className="wjb-heading wjb-heading--light">Because a chatbot can’t show its work.</h2>
            <p className="wjb-sub wjb-sub--light">
              A raw AI chat writes the numbers itself, so they drift when you re-ask or reword.
              Jaspen lets AI judge the evidence, then <strong>code does the math</strong>. The
              answer holds up when someone asks how you got it.
            </p>
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

        {/* Right half: Your criteria */}
        <div className="wjb-panel wjb-panel--light">
          <div className="wjb-content">
            <p className="wjb-eyebrow">Your criteria</p>
            <h2 className="wjb-heading">The rubric is yours.</h2>
            <p className="wjb-sub">
              Jaspen never decides what matters. It offers a starting point, then you shape it into
              the criteria and weights that fit this decision.
            </p>
            <div className="wjb-points">
              {STEPS.map((s) => (
                <div className="wjb-point wjb-point--light" key={s.title}>
                  <span className="wjb-point-icon">
                    <i className={`fa-solid ${s.icon}`} aria-hidden="true" />
                  </span>
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
