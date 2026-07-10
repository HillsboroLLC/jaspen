import React from 'react';
import './WhyNotChatGPT.css';

// "Why not just ChatGPT?" — kept deliberately minimal and scannable: one line
// that is the whole moat, plus three short proofs. Each proof is a truthful,
// Constitution-grounded claim a general chatbot cannot make (article refs in
// comments). Resist adding rows — brevity is the point.
const PROOFS = [
  {
    label: 'Reproducible',
    text: 'Same inputs, same answer, every time.', // Art. 6
  },
  {
    label: 'Evidence-capped',
    text: 'It can’t sound more certain than the evidence allows.', // Art. 7
  },
  {
    label: 'Shows its work',
    text: 'Every score breaks down into the facts behind it.', // Art. 9
  },
];

export default function WhyNotChatGPT() {
  return (
    <section className="wnc" id="why-not-chatgpt">
      <div className="wnc-inner">
        <p className="wnc-eyebrow">Why not just ChatGPT?</p>
        <h2 className="wnc-heading">Because a chatbot can’t show its work.</h2>
        <p className="wnc-sub">
          A raw AI chat (ChatGPT, Claude, Gemini) writes the numbers itself, so they drift
          when you re-ask or reword. Jaspen lets AI judge the evidence, then
          <strong> code does the math</strong>. The answer holds up when someone asks how
          you got it.
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
