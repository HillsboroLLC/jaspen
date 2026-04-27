import React, { useState, useEffect, useRef } from 'react';
import './JaspenAgentDemo.css';

const BUSINESS_IDEA =
  'AI-powered meal prep service that analyzes user biometrics and local grocery inventory to generate weekly recipes and automated delivery orders.';

const ANALYSIS_PHRASES = [
  'Analyzing market trends...',
  'Evaluating competition...',
  'Calculating risk factors...',
];

const INSIGHTS = [
  {
    label: 'Market Demand',
    text: 'High. Growing trend in personalized nutrition and time-saving convenience services among urban professionals.',
  },
  {
    label: 'Competition',
    text: 'Moderate to High. Existing meal kit services (HelloFresh, Blue Apron) are established, but lack deep biometric integration and dynamic local inventory sourcing.',
  },
  {
    label: 'Risk Level',
    text: 'Medium. Primary risks involve supply chain logistics for fresh ingredients and user privacy concerns regarding biometric data.',
  },
];

const PLAN_STEPS = [
  {
    title: 'Phase 1: Data Integration & MVP',
    desc: 'Develop core algorithm connecting basic health APIs (e.g., Apple Health) with a single local grocery chain's inventory API.',
  },
  {
    title: 'Phase 2: Recipe Generation Engine',
    desc: 'Train LLM on nutritional databases to generate viable, tasty recipes based on constrained inventory and user macros.',
  },
  {
    title: 'Phase 3: Logistics & Fulfillment',
    desc: 'Partner with existing last-mile delivery services (e.g., Instacart, DoorDash) rather than building an in-house delivery fleet.',
  },
  {
    title: 'Phase 4: Beta Launch & Iteration',
    desc: 'Launch closed beta in a single dense urban market to refine the recommendation engine and logistics flow.',
  },
];

const SCORE = 82;
const TYPING_SPEED = 15;

export default function JaspenAgentDemo() {
  const [phase, setPhase] = useState('idle');
  const [typedText, setTypedText] = useState('');
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [phraseVisible, setPhraseVisible] = useState(false);
  const [score, setScore] = useState(0);
  const [visibleInsights, setVisibleInsights] = useState([]);
  const [visibleSteps, setVisibleSteps] = useState([]);

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

  const resetAll = () => {
    clearAll();
    setPhase('idle');
    setTypedText('');
    setPhraseIndex(0);
    setPhraseVisible(false);
    setScore(0);
    setVisibleInsights([]);
    setVisibleSteps([]);
  };

  // Boot
  useEffect(() => {
    later(() => setPhase('typing'), 1000);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Typing
  useEffect(() => {
    if (phase !== 'typing') return;
    if (prefersReduced.current) {
      setTypedText(BUSINESS_IDEA);
      later(() => setPhase('analyzing'), 400);
      return clearAll;
    }
    let i = 0;
    const tick = () => {
      i++;
      setTypedText(BUSINESS_IDEA.slice(0, i));
      if (i < BUSINESS_IDEA.length) {
        later(tick, TYPING_SPEED);
      } else {
        later(() => setPhase('analyzing'), 700);
      }
    };
    later(tick, 300);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Analyzing
  useEffect(() => {
    if (phase !== 'analyzing') return;
    let idx = 0;
    const showPhrase = () => {
      setPhraseIndex(idx);
      setPhraseVisible(true);
      later(() => {
        setPhraseVisible(false);
        idx++;
        if (idx < ANALYSIS_PHRASES.length) {
          later(showPhrase, 350);
        } else {
          later(() => setPhase('score'), 500);
        }
      }, 900);
    };
    later(showPhrase, 300);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Score count-up
  useEffect(() => {
    if (phase !== 'score') return;
    if (prefersReduced.current) {
      setScore(SCORE);
      later(() => setPhase('insights'), 400);
      return clearAll;
    }
    const duration = 1200;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setScore(Math.round(eased * SCORE));
      if (t < 1) {
        raf.current = requestAnimationFrame(tick);
      } else {
        setScore(SCORE);
        later(() => setPhase('insights'), 600);
      }
    };
    raf.current = requestAnimationFrame(tick);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Insights stagger
  useEffect(() => {
    if (phase !== 'insights') return;
    INSIGHTS.forEach((_, i) => {
      later(() => setVisibleInsights((prev) => [...prev, i]), i * 200);
    });
    later(() => setPhase('plan'), INSIGHTS.length * 200 + 1800);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Plan stagger
  useEffect(() => {
    if (phase !== 'plan') return;
    PLAN_STEPS.forEach((_, i) => {
      later(() => setVisibleSteps((prev) => [...prev, i]), i * 400);
    });
    later(() => setPhase('done'), PLAN_STEPS.length * 400 + 2500);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Reset loop
  useEffect(() => {
    if (phase !== 'done') return;
    later(() => {
      resetAll();
      later(() => setPhase('typing'), 1000);
    }, 3500);
    return clearAll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const inputLocked = !['idle', 'typing'].includes(phase);
  const showAnalyzing = phase === 'analyzing';
  const showScore = ['score', 'insights', 'plan', 'done'].includes(phase);
  const showInsights = ['insights', 'plan', 'done'].includes(phase);
  const showPlan = ['plan', 'done'].includes(phase);

  return (
    <div className="jad-root" aria-label="Jaspen AI Agent Demo" aria-live="polite">

      {/* ── Input ── */}
      <div className={`jad-input-wrap${inputLocked ? ' jad-input-locked' : ''}`}>
        <div className="jad-input-inner">
          <span className="jad-eyebrow jad-eyebrow--magenta">Business Idea</span>
          <p className="jad-input-text">
            {typedText ? (
              <>
                {typedText}
                {phase === 'typing' && <span className="jad-cursor" aria-hidden="true" />}
              </>
            ) : (
              <span className="jad-placeholder">Enter your business idea...</span>
            )}
          </p>
        </div>
      </div>

      {/* ── Thinking ── */}
      {showAnalyzing && (
        <div className="jad-thinking" aria-label="Analyzing">
          <div className="jad-dots" aria-hidden="true">
            <span /><span /><span />
          </div>
          <span className={`jad-phrase${phraseVisible ? ' jad-phrase-visible' : ''}`}>
            {ANALYSIS_PHRASES[phraseIndex]}
          </span>
        </div>
      )}

      {/* ── Score ── */}
      {showScore && (
        <div className="jad-score jad-anim-up">
          <span className="jad-eyebrow jad-eyebrow--magenta">Idea Score</span>
          <div className="jad-score-num">
            {score}
            <span className="jad-score-denom">/100</span>
          </div>
        </div>
      )}

      {/* ── Insights ── */}
      {showInsights && (
        <div className="jad-insights">
          {INSIGHTS.map((insight, i) => (
            <div
              key={i}
              className={`jad-card${visibleInsights.includes(i) ? ' jad-card-visible' : ''}`}
            >
              <span className="jad-eyebrow jad-eyebrow--orange">{insight.label}</span>
              <p className="jad-card-text">{insight.text}</p>
            </div>
          ))}
        </div>
      )}

      {/* ── Execution Plan ── */}
      {showPlan && (
        <div className="jad-plan">
          <span className="jad-eyebrow jad-eyebrow--navy jad-anim-up">Execution Plan</span>
          <div className="jad-steps">
            {PLAN_STEPS.map((step, i) => (
              <div
                key={i}
                className={`jad-step${visibleSteps.includes(i) ? ' jad-step-visible' : ''}`}
              >
                <span className="jad-step-num" aria-hidden="true">{i + 1}</span>
                <div className="jad-step-content">
                  <strong className="jad-step-title">{step.title}</strong>
                  <p className="jad-step-desc">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}
