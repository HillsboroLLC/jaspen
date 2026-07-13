import React, { useEffect, useRef, useState } from 'react';
import './WhyJaspenBlock.css';

// Combined color-block section that merges two short beats into one:
//   Left (navy):  "Why not just ChatGPT?" the moat, three proofs.
//   Right (cream): "Your criteria" the rubric is yours, three steps.
// Flat design, brand palette only (navy / cream / magenta, no lavender). The
// six item cards drop into place as falling 3D cubes when the section scrolls
// into view.

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
  const ref = useRef(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    // Reveal (drop the cubes in) when the section scrolls into the lower part of
    // the viewport. A scroll/resize check keeps content from ever being stuck
    // hidden if observers misbehave, and reveals immediately if it is already
    // on screen at mount.
    const check = () => {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight * 0.85 && r.bottom > 0) {
        setInView(true);
        return true;
      }
      return false;
    };
    if (check()) return undefined;
    const onScroll = () => {
      if (check()) {
        window.removeEventListener('scroll', onScroll);
        window.removeEventListener('resize', onScroll);
      }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  return (
    <section
      className={`wjb${inView ? ' is-in' : ''}`}
      id="why-jaspen"
      ref={ref}
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
            <div className="wjb-cubes">
              {PROOFS.map((p, i) => (
                <div className="wjb-cube wjb-cube--dark" style={{ '--i': i }} key={p.label}>
                  <p className="wjb-cube-label">{p.label}</p>
                  <p className="wjb-cube-text wjb-cube-text--light">{p.text}</p>
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
            <div className="wjb-cubes">
              {STEPS.map((s, i) => (
                <div className="wjb-cube wjb-cube--light" style={{ '--i': i + 3 }} key={s.title}>
                  <span className="wjb-cube-icon">
                    <i className={`fa-solid ${s.icon}`} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="wjb-cube-title">{s.title}</p>
                    <p className="wjb-cube-text">{s.note}</p>
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
