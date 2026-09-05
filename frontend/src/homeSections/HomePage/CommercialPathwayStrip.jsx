import React from 'react';
import './CommercialPathwayStrip.css';

// The transition between the free tools and the pricing table.
//
// WHAT THIS EXISTS TO SETTLE
//
// By the time a reader reaches pricing they have met the assessment, the
// calculators and the toolkit, and nothing on the page has said whether those
// are the product, a sample of it, or a different product entirely. The pricing
// table then opens with plans, which answers "what does it cost" before anyone
// has answered "what am I choosing between". This strip answers the second
// question in three lines.
//
// ONE PRODUCT, THREE DEPTHS — AND NO WINNER
//
// The three paths are set identically: same type, same weight, same colour, no
// icons, no ordering cues, no emphasis on the last one. That is deliberate.
// They are depths of engagement with the same product, chosen by what the
// decision needs, and any visual hierarchy between them would say that the
// free tools are a lesser version of something rather than a real way to use
// Jaspen. The only thing that differentiates them is the copy.
//
// WHY IT IS A STRIP AND NOT A SECTION
//
// It carries the reader across a boundary; it is not a destination. It takes
// the pricing section's own background so the two read as one zone at rest,
// and .pvb-section is position: sticky, so as the reader scrolls this hands
// off underneath the pricing table rather than competing with it.

const PATHWAYS = [
  {
    title: 'Start free',
    body:
      'Use Jaspen’s assessments, calculators, and planning tools to begin '
      + 'structuring a decision.',
  },
  {
    title: 'Work through it yourself',
    body:
      'Use Jaspen directly through a self-serve subscription when you want to '
      + 'evaluate and pressure-test decisions on your own or with your team.',
  },
  {
    title: 'Bring Jaspen into the decision',
    body:
      'For consequential business decisions, enterprise deployments, or direct '
      + 'executive support, Jaspen can work with the organization at a deeper '
      + 'level.',
  },
];

export default function CommercialPathwayStrip() {
  return (
    <section className="cps" aria-labelledby="cps-title">
      <div className="cps-inner">
        <h2 className="cps-title" id="cps-title">
          One product. Different ways to engage.
        </h2>

        {/* A definition list, because each item is a name and what it means —
            not a feature card and not a step in a sequence. */}
        <dl className="cps-paths">
          {PATHWAYS.map((path) => (
            <div className="cps-path" key={path.title}>
              <dt className="cps-path-title">{path.title}</dt>
              <dd className="cps-path-body">{path.body}</dd>
            </div>
          ))}
        </dl>

        <p className="cps-footer">
          Start where the decision is. Expand when the stakes require it.
        </p>
      </div>
    </section>
  );
}
