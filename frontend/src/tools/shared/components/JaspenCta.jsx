import React from 'react';
import { Link } from 'react-router-dom';

// Soft Jaspen connection — appears only after results deliver value. Standalone
// value first; Jaspen is the natural next step, never a sales pitch.
export default function JaspenCta({ kicker, title, intro, bullets = [], closing, ctaLabel, ctaTo, onCta }) {
  const handleCta = () => {
    onCta?.();
    if (ctaTo === '/') {
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
      window.setTimeout(() => window.scrollTo({ top: 0, left: 0, behavior: 'auto' }), 0);
    }
  };

  return (
    <section className="tool-cta" aria-labelledby="tool-cta-title">
      {kicker ? <p className="tool-kicker">{kicker}</p> : null}
      <h2 id="tool-cta-title">{title}</h2>
      {intro ? <p>{intro}</p> : null}
      {bullets.length > 0 ? (
        <ul className="tool-cta-list">
          {bullets.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}
      {closing ? <p>{closing}</p> : null}
      <div style={{ marginTop: 20 }}>
        <Link to={ctaTo} className="tool-btn tool-btn-primary" onClick={handleCta}>
          {ctaLabel}
        </Link>
      </div>
    </section>
  );
}
