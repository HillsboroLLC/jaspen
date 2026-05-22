import React, { useState, useEffect, useRef } from 'react';
import './ScrollGuide.css';

const SECTIONS = [
  { id: 'intro-header',   label: 'Jaspen' },
  { id: 'pricing-plans',  label: 'Plans' },
  { id: 'product-header', label: 'How it works' },
  { id: 'who-content',    label: 'Built for' },
  { id: 'industries',     label: 'Industries' },
  { id: 'request-access', label: 'Enterprise' },
];

export default function ScrollGuide() {
  const [active, setActive] = useState(null);
  const [visible, setVisible] = useState(false);
  const [showCue, setShowCue] = useState(true);
  const observerRef = useRef(null);

  useEffect(() => {
    let heroBottom = 0;
    const hero = document.getElementById('hero-content');
    if (hero) {
      const rect = hero.getBoundingClientRect();
      heroBottom = rect.bottom + window.scrollY + 80;
    }

    const handleScroll = () => {
      const y = window.scrollY;
      setVisible(y > heroBottom);
      if (y > 100) setShowCue(false);
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    const entries = new Map();

    observerRef.current = new IntersectionObserver(
      (observed) => {
        observed.forEach((e) => entries.set(e.target.id, e.intersectionRatio));
        let best = null;
        let bestRatio = -1;
        entries.forEach((ratio, id) => {
          if (ratio > bestRatio) { bestRatio = ratio; best = id; }
        });
        if (best) setActive(best);
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1], rootMargin: '-15% 0px -15% 0px' }
    );

    SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observerRef.current.observe(el);
    });

    return () => observerRef.current?.disconnect();
  }, []);

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const scrollToTop = () => window.scrollTo({ top: 0, behavior: 'smooth' });

  return (
    <>
      {showCue && (
        <div className="scroll-cue" aria-hidden="true">
          <span className="scroll-cue-label">Scroll</span>
          <div className="scroll-cue-track">
            <div className="scroll-cue-dot" />
          </div>
        </div>
      )}

      <nav className={`scroll-guide ${visible ? 'is-visible' : ''}`} aria-label="Page sections">
        <ul className="scroll-guide-list">
          {SECTIONS.map(({ id, label }) => (
            <li key={id} className="scroll-guide-item">
              <span className="scroll-guide-label">{label}</span>
              <button
                type="button"
                className={`scroll-guide-dot ${active === id ? 'is-active' : ''}`}
                onClick={() => scrollTo(id)}
                aria-label={`Go to ${label}`}
              />
            </li>
          ))}
        </ul>

        <button
          type="button"
          className="scroll-guide-top"
          onClick={scrollToTop}
          aria-label="Back to top"
          title="Back to top"
        >
          <i className="fa-solid fa-chevron-up" aria-hidden="true" />
        </button>
      </nav>
    </>
  );
}
