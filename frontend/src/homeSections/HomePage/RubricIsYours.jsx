import React from 'react';
import './RubricIsYours.css';

// Compact "the rubric is yours" beat for the homepage. Deliberately a
// horizontal three-step flow (NOT the three-card grid used on the Jaspen Score
// page) so the homepage does not repeat itself. Closes on the line the founder
// liked: "Jaspen proposes. It never imposes." Site palette, no gradients, no
// emojis, Font Awesome icons only, no em dashes.
const STEPS = [
  { icon: 'fa-lightbulb', title: 'Jaspen proposes', note: 'A sensible starter rubric, tuned to your objective.' },
  { icon: 'fa-sliders', title: 'You adjust', note: 'Reweight, rename, or replace the criteria. Up to twelve.' },
  { icon: 'fa-user-check', title: 'It stays yours', note: 'Data informs the scores. It never picks what matters.' },
];

export default function RubricIsYours() {
  return (
    <section className="riy" id="the-rubric-is-yours">
      <div className="riy-inner">
        <div className="riy-header">
          <p className="riy-eyebrow">Your criteria</p>
          <h2 className="riy-heading">The rubric is yours</h2>
          <p className="riy-sub">
            Jaspen never decides what matters. It offers a starting point, then you shape it
            into the criteria and weights that fit this decision.
          </p>
        </div>

        <div className="riy-steps">
          {STEPS.map((s, i) => (
            <React.Fragment key={s.title}>
              <div className="riy-step">
                <span className="riy-step-icon"><i className={`fa-solid ${s.icon}`} aria-hidden="true" /></span>
                <p className="riy-step-title">{s.title}</p>
                <p className="riy-step-note">{s.note}</p>
              </div>
              {i < STEPS.length - 1 && (
                <i className="fa-solid fa-chevron-right riy-arrow" aria-hidden="true" />
              )}
            </React.Fragment>
          ))}
        </div>

        <p className="riy-closing">Jaspen proposes. It never imposes.</p>
      </div>
    </section>
  );
}
