import React, { useState, useEffect, useRef } from 'react';
import './JaspenAgentDemo.css';

const PROJECT = 'AI Meal Prep Platform';
const BASELINE_SCORE = 68;

const THINKING_PHRASES = [
  'Scoring ideas...',
  'Projecting outcomes...',
  'Comparing tradeoffs...',
];

const SCENARIO_A = {
  levers: [
    { label: 'Budget',    from: '$800K', to: '$1.2M',      delta: '+$400K', positive: true  },
    { label: 'Team Size', from: '6',     to: '10 people',  delta: '+4',     positive: true  },
  ],
  score: 76,
  outcomes: [
    { label: 'ROI',     value: '64%',   delta: '+19pp',  positive: true },
    { label: '3-Yr NPV', value: '$2.1M', delta: '+$900K', positive: true },
    { label: 'Payback',  value: '13 mo', delta: '−5 mo',  positive: true },
  ],
};

const SCENARIO_B = {
  levers: [
    { label: 'Timeline', from: '12 mo',       to: '18 mo',    delta: '+6 mo',    positive: false },
    { label: 'Market',   from: 'Single city',  to: 'Regional', delta: 'Expanded', positive: true  },
  ],
  score: 71,
  outcomes: [
    { label: 'ROI',      value: '53%',   delta: '+8pp',   positive: true },
    { label: '3-Yr NPV', value: '$1.6M', delta: '+$400K', positive: true },
    { label: 'Payback',  value: '16 mo', delta: '−2 mo',  positive: true },
  ],
};

export default function JaspenScenarioDemo({ onComplete }) {
  const [phase, setPhase] = useState('idle');
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [phraseVisible, setPhraseVisible] = useState(false);
  const [visibleLeversA, setVisibleLeversA] = useState([]);
  const [scoreA, setScoreA] = useState(0);
  const [visibleOutcomesA, setVisibleOutcomesA] = useState([]);
  const [visibleLeversB, setVisibleLeversB] = useState([]);
  const [scoreB, setScoreB] = useState(0);
  const [visibleOutcomesB, setVisibleOutcomesB] = useState([]);

  const timers = useRef([]);
  const raf = useRef(null);
  const prefersReduced = useRef(
    typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  );

  const clearAll = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    cancelAnimationFrame(raf.current);
  };

  const later = (fn, ms) => {
    const t = setTimeout(fn, ms);
    timers.current.push(t);
    return t;
  };

  const countUp = (target, setter, onDone, duration = 900) => {
    if (prefersReduced.current) { setter(target); onDone(); return; }
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      setter(Math.round((1 - Math.pow(1 - t, 3)) * target));
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else { setter(target); onDone(); }
    };
    raf.current = requestAnimationFrame(tick);
  };

  // Boot
  useEffect(() => {
    later(() => setPhase('baseline'), 800);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Baseline → thinking
  useEffect(() => {
    if (phase !== 'baseline') return;
    later(() => setPhase('thinking'), 1600);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Thinking
  useEffect(() => {
    if (phase !== 'thinking') return;
    let idx = 0;
    const showPhrase = () => {
      setPhraseIndex(idx);
      setPhraseVisible(true);
      later(() => {
        setPhraseVisible(false);
        idx++;
        if (idx < THINKING_PHRASES.length) later(showPhrase, 350);
        else later(() => setPhase('scenario_a'), 500);
      }, 900);
    };
    later(showPhrase, 300);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Scenario A
  useEffect(() => {
    if (phase !== 'scenario_a') return;
    SCENARIO_A.levers.forEach((_, i) =>
      later(() => setVisibleLeversA((p) => [...p, i]), i * 350)
    );
    const afterLevers = SCENARIO_A.levers.length * 350 + 500;
    later(() => {
      countUp(SCENARIO_A.score, setScoreA, () => {
        SCENARIO_A.outcomes.forEach((_, i) =>
          later(() => setVisibleOutcomesA((p) => [...p, i]), i * 150)
        );
        later(
          () => setPhase('scenario_b'),
          SCENARIO_A.outcomes.length * 150 + 1200
        );
      });
    }, afterLevers);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Scenario B
  useEffect(() => {
    if (phase !== 'scenario_b') return;
    SCENARIO_B.levers.forEach((_, i) =>
      later(() => setVisibleLeversB((p) => [...p, i]), i * 350)
    );
    const afterLevers = SCENARIO_B.levers.length * 350 + 500;
    later(() => {
      countUp(SCENARIO_B.score, setScoreB, () => {
        SCENARIO_B.outcomes.forEach((_, i) =>
          later(() => setVisibleOutcomesB((p) => [...p, i]), i * 150)
        );
        later(
          () => setPhase('winner'),
          SCENARIO_B.outcomes.length * 150 + 1200
        );
      });
    }, afterLevers);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Winner → done (isolated timers, not cleared by clearAll)
  useEffect(() => {
    if (phase !== 'winner') return;
    const t = setTimeout(() => setPhase('done'), 2500);
    return () => clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase !== 'done') return;
    const t = setTimeout(() => { if (onComplete) onComplete(); }, 2000);
    return () => clearTimeout(t);
  }, [phase, onComplete]);

  const showBaseline = phase !== 'idle';
  const showThinking = phase === 'thinking';
  const showA = ['scenario_a', 'scenario_b', 'winner', 'done'].includes(phase);
  const showB = ['scenario_b', 'winner', 'done'].includes(phase);
  const showWinner = ['winner', 'done'].includes(phase);

  return (
    <div className="jad-root" aria-label="Jaspen Trade-Off Engine Demo" aria-live="polite">

      {/* Header */}
      <div className="jad-sm-header">
        <span className="jad-eyebrow jad-eyebrow--magenta">Trade-Off Engine</span>
        {showBaseline && (
          <div className="jad-sm-project jad-anim-up">
            <span className="jad-sm-project-name">{PROJECT}</span>
            <span className="jad-sm-baseline-pill">
              Baseline <strong>{BASELINE_SCORE}</strong>/100
            </span>
          </div>
        )}
      </div>

      {/* Thinking */}
      {showThinking && (
        <div className="jad-thinking">
          <div className="jad-dots" aria-hidden="true"><span /><span /><span /></div>
          <span className={`jad-phrase${phraseVisible ? ' jad-phrase-visible' : ''}`}>
            {THINKING_PHRASES[phraseIndex]}
          </span>
        </div>
      )}

      {/* Scenario A */}
      {showA && (
        <div className={`jad-card jad-card-visible jad-sm-scenario${showWinner ? ' jad-sm-winner' : ''}`}>
          <div className="jad-sm-scenario-head">
            <span className="jad-eyebrow jad-eyebrow--orange">Idea A</span>
            {scoreA > 0 && (
              <div className="jad-sm-score-row">
                <span className="jad-sm-score-num">
                  {scoreA}<span className="jad-sm-score-denom">/100</span>
                </span>
                <span className="jad-sm-pts-delta">+{SCENARIO_A.score - BASELINE_SCORE} pts</span>
              </div>
            )}
          </div>

          <div className="jad-sm-levers">
            {SCENARIO_A.levers.map((lever, i) => (
              <div key={i} className={`jad-sm-lever${visibleLeversA.includes(i) ? ' jad-sm-lever-visible' : ''}`}>
                <span className="jad-sm-lever-label">{lever.label}</span>
                <span className="jad-sm-lever-change">{lever.from} → {lever.to}</span>
                <span className={`jad-sm-lever-delta${lever.positive ? ' jad-sm-pos' : ' jad-sm-neg'}`}>
                  {lever.delta}
                </span>
              </div>
            ))}
          </div>

          {visibleOutcomesA.length > 0 && (
            <div className="jad-sm-outcomes">
              {SCENARIO_A.outcomes.map((o, i) => (
                <div key={i} className={`jad-sm-outcome${visibleOutcomesA.includes(i) ? ' jad-sm-outcome-visible' : ''}`}>
                  <span className="jad-sm-outcome-label">{o.label}</span>
                  <span className="jad-sm-outcome-val">{o.value}</span>
                  <span className={`jad-sm-outcome-delta${o.positive ? ' jad-sm-pos' : ' jad-sm-neg'}`}>{o.delta}</span>
                </div>
              ))}
            </div>
          )}

          {showWinner && (
            <span className="jad-sm-winner-badge jad-anim-up">Best outcome</span>
          )}
        </div>
      )}

      {/* Scenario B */}
      {showB && (
        <div className="jad-card jad-card-visible jad-sm-scenario">
          <div className="jad-sm-scenario-head">
            <span className="jad-eyebrow jad-eyebrow--navy">Idea B</span>
            {scoreB > 0 && (
              <div className="jad-sm-score-row">
                <span className="jad-sm-score-num">
                  {scoreB}<span className="jad-sm-score-denom">/100</span>
                </span>
                <span className="jad-sm-pts-delta">+{SCENARIO_B.score - BASELINE_SCORE} pts</span>
              </div>
            )}
          </div>

          <div className="jad-sm-levers">
            {SCENARIO_B.levers.map((lever, i) => (
              <div key={i} className={`jad-sm-lever${visibleLeversB.includes(i) ? ' jad-sm-lever-visible' : ''}`}>
                <span className="jad-sm-lever-label">{lever.label}</span>
                <span className="jad-sm-lever-change">{lever.from} → {lever.to}</span>
                <span className={`jad-sm-lever-delta${lever.positive ? ' jad-sm-pos' : ' jad-sm-neg'}`}>
                  {lever.delta}
                </span>
              </div>
            ))}
          </div>

          {visibleOutcomesB.length > 0 && (
            <div className="jad-sm-outcomes">
              {SCENARIO_B.outcomes.map((o, i) => (
                <div key={i} className={`jad-sm-outcome${visibleOutcomesB.includes(i) ? ' jad-sm-outcome-visible' : ''}`}>
                  <span className="jad-sm-outcome-label">{o.label}</span>
                  <span className="jad-sm-outcome-val">{o.value}</span>
                  <span className={`jad-sm-outcome-delta${o.positive ? ' jad-sm-pos' : ' jad-sm-neg'}`}>{o.delta}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

    </div>
  );
}
