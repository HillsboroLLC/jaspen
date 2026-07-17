import React from 'react';
import { Link } from 'react-router-dom';
import { analytics } from '../services/analytics';

// Soft Jaspen connection — appears only after the result has delivered value.
// Frames Jaspen as a persistent organizational thought partner that preserves
// connected business knowledge. Makes no claim that Jaspen prevents departures
// or recovers every cost shown.
export default function JaspenCta() {
  const handleCta = () => {
    analytics.jaspenCtaClicked('home');
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
    window.setTimeout(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }), 0);
  };

  return (
    <section className="cot-cta" aria-labelledby="cot-cta-title">
      <p className="cot-kicker">Beyond the number</p>
      <h2 id="cot-cta-title">When someone leaves, the cost isn&apos;t only the hire</h2>
      <p>
        The largest, quietest losses above are context and institutional memory. When a person
        leaves, so can the project history, lessons learned, business rationale, prior assumptions,
        operational context, and the connected customer and supplier knowledge that lived with them.
      </p>
      <ul className="cot-cta-list">
        <li>Project history and decisions</li>
        <li>Lessons learned</li>
        <li>Business rationale</li>
        <li>Prior assumptions</li>
        <li>Operational context</li>
        <li>Connected customer and supplier context</li>
      </ul>
      <p>
        Jaspen can serve as a persistent organizational thought partner and contextual foundation —
        retaining and synthesizing connected business knowledge over time so more of it survives a
        departure. It won&apos;t prevent turnover or recover every cost shown here, but it can help
        preserve the context that is otherwise rebuilt from scratch.
      </p>
      <div style={{ marginTop: 20 }}>
        <Link
          to="/"
          className="cot-btn cot-btn-primary"
          onClick={handleCta}
        >
          See how Jaspen helps preserve organizational context
        </Link>
      </div>
    </section>
  );
}
