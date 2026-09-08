import React from 'react';
import './BeforeYouCommit.css';

// The curtain section between the hero and the tan canvas. HomePage pins the
// hero once you have scrolled one hero-height and lets the next section slide
// up over it, which makes this section the curtain — hence position/z-index in
// the CSS, and hence the leading edge below.
//
// THE LEADING EDGE IS THE POINT, NOT TRIM.
//
// `.byc-curtain` is an SVG painted into the space ABOVE this section's own box:
// navy below the curve, transparent above it, so the pinned hero shows through
// the gap and the navy reads as a surface sweeping over it. Without it the
// section enters on a straight horizontal line and looks inserted between two
// existing sections rather than part of the curtain interaction.
//
// The curve rises left to right, so the navy is deepest on the right — which is
// where this composition's negative space is, and where the statement that
// carries it sits. The edge is doing compositional work rather than decorating
// a boundary. It is deliberately NOT the .jaspen-live-wave path mirrored: both
// edges are visible within one scroll, and a repeat would read as a template.
//
// The tan wave still handles the navy → canvas boundary at the bottom. It is
// absolutely positioned at top: -88px inside #jaspen-live and paints over the
// 88px above it, which is why this section's bottom padding stays above 88px at
// every width.

// Five moments where a decision can still be challenged. They share a stem, and
// the repetition is the point: they are the same KIND of thing — scheduled,
// ordinary, reversible. They are set quietly on purpose. The line that matters
// is not among them.
const MOMENTS = [
  'commit the capital.',
  'present the recommendation.',
  'choose the vendor.',
  'lock the strategy.',
  'reorganize the team.',
];

export default function BeforeYouCommit() {
  const runItThroughJaspen = () => {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
    // The hero is position: fixed while pinned; scrolling to the top releases it
    // through HomePage's scroll handler. Focus waits for that to settle, and
    // preventScroll stops the focus itself from fighting the smooth scroll.
    window.setTimeout(() => {
      document.getElementById('decision-context')?.focus({ preventScroll: true });
    }, reduceMotion ? 0 : 620);
  };

  return (
    <section className="byc" id="before-you-commit">
      <svg
        className="byc-curtain"
        viewBox="0 0 1440 120"
        preserveAspectRatio="none"
        aria-hidden="true"
        focusable="false"
      >
        <path
          d="M0,96 C260,106 520,88 780,58 C1030,30 1250,12 1440,6 L1440,120 L0,120 Z"
          fill="#161f3b"
        />
      </svg>

      <div className="byc-inner">
        <p className="byc-eyebrow">Before you commit</p>
        <h2 className="byc-heading">
          See where the plan is exposed before the commitment makes it expensive.
        </h2>
        <p className="byc-explainer">
          Ambitious projects can go over budget, stall, or stop when something important
          surfaces too late. Jaspen helps make weak assumptions, evidence gaps, and blind
          spots visible early, while there is still time to strengthen the plan.
        </p>

        <ul className="byc-moments">
          {MOMENTS.map((moment) => (
            <li className="byc-moment" key={moment}>
              <span className="byc-stem">Before you</span> {moment}
            </li>
          ))}
        </ul>

        {/* Out of the list entirely, not the last item in it. The five above are
            moments on a calendar; this one is the room turning, after which
            challenging the decision costs someone their standing rather than an
            afternoon. The layout has to carry that difference, so it is set at
            a scale nothing else on this section competes with, and the only
            thing beneath it is the way out. */}
        <div className="byc-turn">
          <p className="byc-turn-line">Know what remains exposed.</p>
          <p className="byc-turn-support">
            You cannot eliminate every unknown. You can avoid carrying more exposure than
            necessary and consciously accept what remains.
          </p>
          <button type="button" className="byc-action" onClick={runItThroughJaspen}>
            <span>Run it through Jaspen first.</span>
            <i className="fa-solid fa-arrow-right" aria-hidden="true" />
          </button>
        </div>
      </div>
    </section>
  );
}
