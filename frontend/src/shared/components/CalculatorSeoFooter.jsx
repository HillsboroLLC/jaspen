import React from 'react';
import './CalculatorSeoFooter.css';

// A reserved advertisement placement. It holds layout space for an ad unit so
// the page does not shift when real ads load after AdSense approval. It is not
// a real ad and is clearly labeled as reserved space.
function ReservedAdSlot({ label, variant }) {
  return (
    <div className={`calc-ad-slot calc-ad-slot--${variant}`} aria-label="Reserved advertisement placement">
      <span className="calc-ad-slot-tag">Advertisement</span>
      <div className="calc-ad-slot-body">
        <strong>Reserved ad placement</strong>
        <small>{label}</small>
      </div>
    </div>
  );
}

/**
 * Always-visible content shown beneath a calculator: reserved ad placements and
 * a visible FAQ. The `faqs` array is the single source of truth for both this
 * on-page FAQ and the page's FAQPage JSON-LD (see each tool's config/seo.js), so
 * the structured data always matches what the reader sees.
 */
export default function CalculatorSeoFooter({ faqs = [], intro = null, heading = 'Common questions' }) {
  if (!faqs.length && !intro) return null;
  return (
    <section className="calc-seo-footer" aria-label="More about this calculator">
      <ReservedAdSlot label="Responsive · leaderboard (e.g. 728×90)" variant="leaderboard" />

      {intro ? <div className="calc-seo-intro">{intro}</div> : null}

      {faqs.length ? (
        <div className="calc-faq">
          <h2>{heading}</h2>
          <dl>
            {faqs.map((item) => (
              <div className="calc-faq-item" key={item.q}>
                <dt>{item.q}</dt>
                <dd>{item.a}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      <ReservedAdSlot label="Responsive · in-content rectangle (e.g. 300×250)" variant="rectangle" />
    </section>
  );
}
