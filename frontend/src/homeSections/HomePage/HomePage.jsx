import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Link, useSearchParams } from 'react-router-dom';
import JaspenNav from './JaspenNav';
import WorkWithJaspenCanvas from './WorkWithJaspenCanvas';
import InteractiveDecisionHero from './InteractiveDecisionHero';
import StrategyAccessCard from './StrategyAccessCard';
import PricingVariantB from './PricingVariantB';
import FlowIllustrated from './FlowIllustrated';
import BeforeAfter from './BeforeAfter';
import WhyNotChatGPT from './WhyNotChatGPT';
import HowScoreWorks from './HowScoreWorks';
import RubricIsYours from './RubricIsYours';
import LeadCapture from './LeadCapture';
import FAQSection from '../FAQSection/FAQSection';
import { SCENARIOS } from './scenarioData';
import './HomePage.css';

/* ── Animated panel: Evaluate Ideas ── */
function IdeasPanel() {
  const [score, setScore] = useState(0);
  const [visible, setVisible] = useState([]);
  const raf = useRef(null);

  useEffect(() => {
    const target = 82;
    const duration = 1100;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      setScore(Math.round((1 - Math.pow(1 - t, 3)) * target));
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else [0, 1, 2, 3].forEach((i) => setTimeout(() => setVisible((p) => [...p, i]), i * 160));
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, []);

  const insights = [
    { label: 'Market Demand',        badge: 'High',     type: 'high' },
    { label: 'Competition',          badge: 'Moderate', type: 'med'  },
    { label: 'Risk Level',           badge: 'Medium',   type: 'med'  },
    { label: 'Execution Readiness',  badge: 'Strong',   type: 'high' },
  ];

  return (
    <div className="intro-panel" key="ideas">
      <div className="intro-panel-label">Idea Score</div>
      <div className="intro-panel-score">{score}<span>/100</span></div>
      <div className="intro-panel-idea-text">
        AI-powered meal prep service that analyzes user biometrics and local grocery inventory to generate weekly recipes and automated delivery orders.
      </div>
      <div className="intro-panel-insights">
        {insights.map((ins, i) => (
          <div key={i} className={`intro-panel-insight intro-panel-insight--anim${visible.includes(i) ? ' visible' : ''}`}>
            <span className="intro-insight-label">{ins.label}</span>
            <span className={`intro-insight-badge intro-insight-badge--${ins.type}`}>{ins.badge}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Animated panel: Evaluate Tradeoffs ── */
function TradeoffsPanel() {
  const [scoreA, setScoreA] = useState(0);
  const [scoreB, setScoreB] = useState(0);
  const [leversA, setLeversA] = useState([]);
  const [outcomesA, setOutcomesA] = useState([]);
  const [showB, setShowB] = useState(false);
  const [leversB, setLeversB] = useState([]);
  const [outcomesB, setOutcomesB] = useState([]);
  const [showWinner, setShowWinner] = useState(false);
  const raf = useRef(null);
  const timers = useRef([]);

  const later = (fn, ms) => { const t = setTimeout(fn, ms); timers.current.push(t); };

  const countUp = (target, setter, duration = 900) => new Promise((res) => {
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      setter(Math.round((1 - Math.pow(1 - t, 3)) * target));
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else res();
    };
    raf.current = requestAnimationFrame(tick);
  });

  useEffect(() => {
    later(() => {
      setLeversA([0]);
      later(() => setLeversA([0, 1]), 300);
      later(async () => {
        await countUp(76, setScoreA);
        [0, 1, 2].forEach((i) => later(() => setOutcomesA((p) => [...p, i]), i * 140));
        later(() => {
          setShowB(true);
          later(() => setLeversB([0]), 200);
          later(() => setLeversB([0, 1]), 500);
          later(async () => {
            await countUp(71, setScoreB);
            [0, 1, 2].forEach((i) => later(() => setOutcomesB((p) => [...p, i]), i * 140));
            later(() => setShowWinner(true), 700);
          }, 600);
        }, 900);
      }, 700);
    }, 300);
    return () => { timers.current.forEach(clearTimeout); cancelAnimationFrame(raf.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="intro-panel" key="tradeoffs">
      <div className="intro-panel-label">Trade-Off Engine</div>
      <div className="intro-panel-project">
        <span className="intro-panel-project-name">AI Meal Prep Platform</span>
        <span className="intro-panel-baseline">Baseline 68/100</span>
      </div>
      <div className="intro-panel-scenarios">
        <div className={`intro-scenario${showWinner ? ' intro-scenario--winner' : ''}`}>
          <div className="intro-scenario-head">
            <span className="intro-scenario-label">Option A</span>
            {scoreA > 0 && <><span className="intro-scenario-score">{scoreA}<span>/100</span></span><span className="intro-scenario-delta">+{scoreA - 68} pts</span></>}
          </div>
          <div className="intro-scenario-levers">
            {[{ l: 'Budget', c: '$800K → $1.2M', d: '+$400K', pos: true }, { l: 'Team', c: '6 → 10 people', d: '+4', pos: true }]
              .map((lv, i) => leversA.includes(i) && (
                <div key={i} className="intro-scenario-lever intro-scenario-lever--anim visible">
                  <span>{lv.l}</span><span>{lv.c}</span><span className={lv.pos ? 'pos' : 'neg'}>{lv.d}</span>
                </div>
              ))}
          </div>
          {outcomesA.length > 0 && (
            <div className="intro-scenario-outcomes">
              {[{ l: 'ROI', v: '64%', d: '+19pp' }, { l: '3-Yr NPV', v: '$2.1M', d: '+$900K' }, { l: 'Payback', v: '13 mo', d: '−5 mo' }]
                .map((o, i) => outcomesA.includes(i) && (
                  <div key={i} className="intro-scenario-outcome intro-scenario-outcome--anim visible">
                    <span>{o.l}</span><span>{o.v}</span><span className="pos">{o.d}</span>
                  </div>
                ))}
            </div>
          )}
          {showWinner && <span className="intro-winner-badge">Best outcome</span>}
        </div>
        {showB && (
          <div className="intro-scenario">
            <div className="intro-scenario-head">
              <span className="intro-scenario-label">Option B</span>
              {scoreB > 0 && <><span className="intro-scenario-score">{scoreB}<span>/100</span></span><span className="intro-scenario-delta">+{scoreB - 68} pts</span></>}
            </div>
            <div className="intro-scenario-levers">
              {[{ l: 'Timeline', c: '12 → 18 months', d: '+6 mo', pos: false }, { l: 'Market', c: 'City → Regional', d: 'Expanded', pos: true }]
                .map((lv, i) => leversB.includes(i) && (
                  <div key={i} className="intro-scenario-lever intro-scenario-lever--anim visible">
                    <span>{lv.l}</span><span>{lv.c}</span><span className={lv.pos ? 'pos' : 'neg'}>{lv.d}</span>
                  </div>
                ))}
            </div>
            {outcomesB.length > 0 && (
              <div className="intro-scenario-outcomes">
                {[{ l: 'ROI', v: '53%', d: '+8pp' }, { l: '3-Yr NPV', v: '$1.6M', d: '+$400K' }, { l: 'Payback', v: '16 mo', d: '−2 mo' }]
                  .map((o, i) => outcomesB.includes(i) && (
                    <div key={i} className="intro-scenario-outcome intro-scenario-outcome--anim visible">
                      <span>{o.l}</span><span>{o.v}</span><span className="pos">{o.d}</span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Animated panel: Build Execution Plans ── */
function PlanPanel() {
  const [visible, setVisible] = useState([]);
  useEffect(() => {
    const steps = [
      { phase: '01', title: 'Data Integration & MVP', desc: "Connect core health APIs with a single grocery chain's inventory. Validate the recommendation loop." },
      { phase: '02', title: 'Recipe Generation Engine', desc: 'Train on nutritional databases to generate viable recipes from constrained inventory and user macros.' },
      { phase: '03', title: 'Logistics & Fulfillment', desc: 'Partner with last-mile delivery (Instacart, DoorDash) rather than building in-house delivery.' },
      { phase: '04', title: 'Beta Launch & Iteration', desc: 'Launch closed beta in a single dense urban market. Refine recommendations and logistics flow.' },
    ];
    steps.forEach((_, i) => setTimeout(() => setVisible((p) => [...p, i]), 200 + i * 250));
  }, []);

  return (
    <div className="intro-panel" key="plan">
      <div className="intro-panel-label">Execution Plan</div>
      <div className="intro-panel-project-name">AI Meal Prep Platform — 4 Phases</div>
      <div className="intro-plan-steps">
        {[
          { phase: '01', title: 'Data Integration & MVP', desc: "Connect core health APIs with a single grocery chain's inventory. Validate the recommendation loop." },
          { phase: '02', title: 'Recipe Generation Engine', desc: 'Train on nutritional databases to generate viable recipes from constrained inventory and user macros.' },
          { phase: '03', title: 'Logistics & Fulfillment', desc: 'Partner with last-mile delivery (Instacart, DoorDash) rather than building in-house delivery.' },
          { phase: '04', title: 'Beta Launch & Iteration', desc: 'Launch closed beta in a single dense urban market. Refine recommendations and logistics flow.' },
        ].map((step, i) => (
          <div key={step.phase} className={`intro-plan-step intro-plan-step--anim${visible.includes(i) ? ' visible' : ''}`}>
            <span className="intro-plan-num">{step.phase}</span>
            <div>
              <strong>{step.title}</strong>
              <p>{step.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const STEPS = [
  {
    id: 'frame',
    num: 'F',
    title: 'Frame',
    description: 'Where are we going, and what does success look like?',
    icon: 'fa-solid fa-compass',
  },
  {
    id: 'limits',
    num: 'L',
    title: 'Limits',
    description: "What's getting in the way today?",
    icon: 'fa-solid fa-triangle-exclamation',
  },
  {
    id: 'opportunities',
    num: 'O',
    title: 'Opportunities',
    description: "What's already working — where's the momentum?",
    icon: 'fa-solid fa-arrow-trend-up',
  },
  {
    id: 'weigh',
    num: 'W',
    title: 'Weigh',
    description: 'What are the paths forward, and what are the tradeoffs?',
    icon: 'fa-solid fa-scale-balanced',
  },
];

export default function HomePage() {
  const [activeStep, setActiveStep] = useState(0);
  const [activeFeatureTab, setActiveFeatureTab] = useState(0);
  const stepRefs = useRef([]);
  const [searchParams] = useSearchParams();
  const solveDemo = SCENARIOS[0].demo;
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authModalFlow, setAuthModalFlow] = useState('signin');
  const [authModalPlan, setAuthModalPlan] = useState('free');
  const [heroContext, setHeroContext] = useState('');
  const heroRef = useRef(null);
  const spacerRef = useRef(null);
  const heroHeight = useRef(0);

  const openAuthModal = (flow = 'signin', plan = 'free') => {
    setAuthModalFlow(flow);
    setAuthModalPlan(plan);
    setAuthModalOpen(true);
  };

  useEffect(() => {
    const hero = heroRef.current;
    const spacer = spacerRef.current;
    if (!hero || !spacer) return;

    const update = () => {
      const heroH = hero.offsetHeight;
      heroHeight.current = heroH;
      const vh = window.innerHeight;
      const pinAt = heroH - vh;      // scroll distance before hero pins
      const hideAt = heroH;          // scroll distance when tan has fully covered hero

      const scrollY = window.scrollY;

      if (pinAt > 0 && scrollY >= pinAt && scrollY < hideAt) {
        // Pinned: hero locked in place while tan slides over it
        hero.style.position = 'fixed';
        hero.style.top = `-${pinAt}px`;
        hero.style.visibility = 'visible';
        spacer.style.height = `${heroH}px`;
      } else if (pinAt > 0 && scrollY >= hideAt) {
        // Covered: tan has passed completely over the hero — hide it
        hero.style.position = 'fixed';
        hero.style.top = `-${pinAt}px`;
        hero.style.visibility = 'hidden';
        spacer.style.height = `${heroH}px`;
      } else {
        // Normal scroll: hero reveals its content naturally
        hero.style.position = 'relative';
        hero.style.top = 'auto';
        hero.style.visibility = 'visible';
        spacer.style.height = '0px';
      }
    };

    const ro = new ResizeObserver(update);
    ro.observe(hero);
    window.addEventListener('scroll', update, { passive: true });
    update();
    return () => {
      ro.disconnect();
      window.removeEventListener('scroll', update);
    };
  }, []);

  // Auto-open modal when redirected with ?auth=1
  useEffect(() => {
    if (searchParams.get('auth') === '1') {
      openAuthModal('signin');
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, [searchParams]);

  useEffect(() => {
    // Immediately reveal elements that are already in the viewport on mount
    // (e.g. the hero section). This prevents a flash when the user presses
    // the Home key and returns to the top of the page — those elements
    // already have reveal-visible and stay visible without any observer delay.
    const revealIfVisible = (el) => {
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (rect.top < window.innerHeight && rect.bottom > 0) {
        el.classList.add('reveal-visible');
      }
    };

    const revealElements = document.querySelectorAll('.scroll-reveal');
    revealElements.forEach(revealIfVisible);
    stepRefs.current.forEach(revealIfVisible);

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('reveal-visible');
            // Stop observing once revealed — prevents any re-animation on
            // scroll position resets (Home/End keys) and avoids React
            // reconciliation stripping the class on re-render.
            observer.unobserve(entry.target);
            if (entry.target.dataset.stepIndex !== undefined) {
              setActiveStep(parseInt(entry.target.dataset.stepIndex));
            }
          }
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -5% 0px' }
    );

    revealElements.forEach((el) => {
      // Only observe elements not yet revealed
      if (!el.classList.contains('reveal-visible')) {
        observer.observe(el);
      }
    });

    stepRefs.current.forEach((el) => {
      if (el && !el.classList.contains('reveal-visible')) {
        observer.observe(el);
      }
    });

    return () => observer.disconnect();
  }, []);

  const scrollToSection = (e, sectionId) => {
    e.preventDefault();
    const el = document.getElementById(sectionId);
    if (el) el.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="homepage">
      <JaspenNav onOpenModal={openAuthModal} />

      <main>
        {/* ========== HERO ========== */}
        <div className="hero-curtain-anchor" ref={heroRef}>
          <InteractiveDecisionHero onOpenModal={openAuthModal} onContextChange={setHeroContext} />
        </div>
        <div className="hero-curtain-spacer" ref={spacerRef} aria-hidden="true" />

        {/* ========== WORK WITH JASPEN CANVAS (with "This is Jaspen" beside it) ========== */}
        <div id="jaspen-live">
          <svg className="jaspen-live-wave" viewBox="0 0 1440 90" preserveAspectRatio="none" aria-hidden="true" focusable="false">
            <path d="M0,18 C180,-8 420,12 680,42 C940,68 1200,72 1440,62 L1440,90 L0,90 Z" fill="#f5f1ea" />
          </svg>
          <WorkWithJaspenCanvas demo={solveDemo} />
        </div>

        <BeforeAfter />

        <FlowIllustrated onOpenModal={openAuthModal} />

        {/* ========== WHY NOT JUST CHATGPT? ========== */}
        <WhyNotChatGPT />

        {/* ========== HOW THE SCORE WORKS (trust) ========== */}
        <HowScoreWorks />

        {/* ========== THE RUBRIC IS YOURS ========== */}
        <RubricIsYours />

        {/* ========== PRICING — Comparison Table ========== */}
        <PricingVariantB onOpenModal={openAuthModal} />

        {/* ========== FAQ ========== */}
        <FAQSection />

        {/* ========== LEAD MAGNET: DECISION SCORECARD ========== */}
        <LeadCapture />

        {/* ========== FINAL CTA ========== */}
        <section id="request-access" className="jaspen-cta-section">
          <div className="jaspen-container">
            <div className="cta-box scroll-reveal" id="cta-box">
              <div className="cta-content">
                <p className="cta-eyebrow">Scale when you're ready</p>
                <h2>Ready to bring your whole org along?</h2>
                <p>Custom integrations, dedicated support, SSO, and volume licensing — when Jaspen becomes how your team decides, we'll scope exactly what you need.</p>
                <div className="cta-actions">
                  <a href="mailto:hello@jaspen.ai" className="jaspen-btn jaspen-btn-primary jaspen-btn-lg">
                    Talk to us
                  </a>
                  <a href="#pricing-variant-b" onClick={(e) => scrollToSection(e, 'pricing-variant-b')} className="jaspen-btn cta-btn-secondary jaspen-btn-lg">
                    Start with a standard plan
                  </a>
                </div>
              </div>
              <div className="cta-abstract-visual">
                <div className="abstract-circle"></div>
                <div className="abstract-circle small"></div>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* ========== FOOTER ========== */}
      <footer className="jaspen-footer">
        <div className="jaspen-container">
          <div className="jaspen-footer-grid">
            <div className="jaspen-footer-brand">
              <span className="jaspen-footer-logo">Jaspen</span>
              <p>Your thought partner for the decisions that don&apos;t have an obvious answer.</p>
            </div>
            <div className="jaspen-footer-col">
              <h4>Product</h4>
              <Link to="/pages/solutions">Solutions</Link>
              <Link to="/pages/pricing">Pricing</Link>
              <Link to="/pages/jaspen-score">Jaspen Score</Link>
              <Link to="/pages/project-management">Project Management</Link>
              <Link to="/pages/api">API</Link>
            </div>
            <div className="jaspen-footer-col">
              <h4>Integrations</h4>
              <Link to="/pages/jaspen-in-jira">Jaspen in Jira</Link>
              <Link to="/pages/jaspen-in-smartsheets">Jaspen in Smartsheets</Link>
              <Link to="/pages/resources/connectors">Connectors</Link>
              <Link to="/pages/resources/integrations">Integrations</Link>
              <Link to="/pages/resources/plugins">Plugins</Link>
            </div>
            <div className="jaspen-footer-col">
              <h4>Resources</h4>
              <Link to="/pages/resources/demos">Demos</Link>
              <Link to="/pages/resources/tutorials">Tutorials</Link>
            </div>
            <div className="jaspen-footer-col">
              <h4>Company</h4>
              <Link to="/pages/jaspen">I&apos;m Jaspen</Link>
              <a href="mailto:hello@jaspen.ai">Get in touch</a>
              <Link to="/pages/support">Support</Link>
            </div>
          </div>
          <div className="jaspen-footer-inner">
            <p className="jaspen-footer-copy">&copy; {new Date().getFullYear()} Jaspen. All rights reserved.</p>
            <div className="jaspen-footer-right">
              <Link to="/pages/privacy">Privacy</Link>
              <Link to="/pages/terms">Terms</Link>
            </div>
          </div>
        </div>
      </footer>

      {authModalOpen && createPortal(
        <div
          className="sac-modal-backdrop"
          onMouseDown={(e) => { if (e.target === e.currentTarget) setAuthModalOpen(false); }}
        >
          <div className="sac-modal-shell">
            <button
              type="button"
              className="sac-modal-close"
              onClick={() => setAuthModalOpen(false)}
              aria-label="Close"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true"></i>
            </button>
            <StrategyAccessCard key={authModalFlow + authModalPlan} initialFlowMode={authModalFlow} initialPlan={authModalPlan} heroContext={heroContext} />
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
