import React from 'react';
import './WhyNotChatGPT.css';

// "Why not just ChatGPT?" — kept deliberately minimal and scannable: one line
// that names AI hallucinations directly, plus three short proofs. Each proof is
// a truthful, Constitution-grounded claim a general chatbot cannot make.
const PROOFS = [
  {
    label: 'Constitution-bound',
    text: 'Jaspen proposes; you own the criteria, weights, and decision.',
  },
  {
    label: 'Evidence-capped',
    text: 'Confidence cannot outrun the evidence, assumptions are labeled.',
  },
  {
    label: 'Decomposed',
    text: 'Every score opens into evidence, weights, confidence, and reasoning.',
  },
];

export default function WhyNotChatGPT() {
  return (
    <section className="wnc" id="why-not-chatgpt">
      <div className="wnc-inner">
        <p className="wnc-eyebrow">Why not just ChatGPT?</p>
        <h2 className="wnc-heading">Jaspen does not eliminate AI hallucinations. It is built to resist them.</h2>
        <p className="wnc-sub">
          A raw AI chat can sound confident even when the answer is unsupported. Jaspen
          does not ask you to trust persuasive language blindly: <strong>code does the
          scoring math</strong>, evidence is graded, assumptions are labeled, and your own
          data, documents, and connected context can strengthen the grounding.
        </p>

        <div className="wnc-proofs">
          {PROOFS.map((p, i) => (
            <div className="wnc-proof" key={i}>
              <p className="wnc-proof-label">{p.label}</p>
              <p className="wnc-proof-text">{p.text}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
