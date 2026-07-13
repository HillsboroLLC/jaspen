import React, { useEffect, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faFlag, faChartLine, faClock } from '@fortawesome/free-solid-svg-icons';
import './HeroProblem.css';

// Hero left-column reinforcement: a rotating pain line + persona cards that
// flip in, float gently, and jiggle on hover. Sits under the headline; the
// sign-in card on the right is untouched.

const PAINS = [
  '“Every meeting is the same conversation, and nothing moves.”',
  '“We have a strategy, but it died in operations.”',
  '“Every option sounds reasonable, and no one can agree.”',
];

const PERSONAS = [
  { icon: faFlag, title: 'You own the call no one else will make.', desc: 'The ambiguous, cross-functional decisions land on your desk.', tag: 'Operations' },
  { icon: faChartLine, title: 'You got dashboards when you needed decisions.', desc: 'Burned by tools that promised transformation and shipped charts.', tag: 'Strategy' },
  { icon: faClock, title: "You're long on options, short on time.", desc: 'Too many reasonable paths, no shared way to choose.', tag: 'Supply Chain' },
];

export default function HeroProblem() {
  const [idx, setIdx] = useState(0);
  const [vis, setVis] = useState(true);

  useEffect(() => {
    const t = setInterval(() => {
      setVis(false);
      setTimeout(() => {
        setIdx((p) => (p + 1) % PAINS.length);
        setVis(true);
      }, 400);
    }, 3200);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="hp-block">
      <p className="hp-pain" style={{ opacity: vis ? 1 : 0 }}>{PAINS[idx]}</p>

      <div className="hp-label">Built for the people who own the call</div>
      <div className="hp-grid">
        {PERSONAS.map((p) => (
          <div className="hp-card" key={p.tag}>
            <div className="hp-card-inner">
              <span className="hp-icon"><FontAwesomeIcon icon={p.icon} /></span>
              <p className="hp-ct">{p.title}</p>
              <p className="hp-cd">{p.desc}</p>
              <span className="hp-tag">{p.tag}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
