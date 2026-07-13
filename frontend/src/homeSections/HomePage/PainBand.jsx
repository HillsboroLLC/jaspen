import React, { useEffect, useRef } from 'react';
import './PainBand.css';

// "Sound familiar?" — bold, editorial, low-motion. The three pains land as
// large statements that fade up when the section scrolls into view. This is
// the emotional setup right before the Work with Jaspen demo.

const PAINS = [
  'Every meeting is the same conversation, and nothing moves.',
  'You have a strategy, but it died in operations.',
  'Every option sounds reasonable, and no one can agree.',
];

export default function PainBand() {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) el.classList.add('in'); }),
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className="pain-band" ref={ref}>
      <div className="pain-inner">
        <span className="pain-eyebrow">Sound familiar?</span>
        <div className="pain-list">
          {PAINS.map((p) => (
            <p className="pain-line" key={p}>{p}</p>
          ))}
        </div>
      </div>
    </section>
  );
}
