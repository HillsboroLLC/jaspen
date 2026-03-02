import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import './HomePage.css';

const STEPS = [
  {
    id: 'clarify',
    num: '01',
    title: 'Clarify',
    description: 'Capture the problem, constraints, and definition of success.',
    icon: 'fa-solid fa-lightbulb',
  },
  {
    id: 'decide',
    num: '02',
    title: 'Decide',
    description: 'Generate options, tradeoffs, risks, and a decision-grade recommendation.',
    icon: 'fa-solid fa-scale-balanced',
  },
  {
    id: 'plan',
    num: '03',
    title: 'Plan',
    description: 'Convert the decision into milestones, owners, artifacts, and timeline.',
    icon: 'fa-solid fa-diagram-project',
  },
  {
    id: 'execute',
    num: '04',
    title: 'Execute',
    description: 'Track progress, decisions, risks, and updates in one place.',
    icon: 'fa-solid fa-rocket',
  },
];

export default function HomePage() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [visibleElements, setVisibleElements] = useState(new Set());
  const [activeStep, setActiveStep] = useState(0);
  const stepRefs = useRef([]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setVisibleElements((prev) => new Set([...prev, entry.target.id || entry.target.dataset.id]));
            if (entry.target.dataset.stepIndex !== undefined) {
              setActiveStep(parseInt(entry.target.dataset.stepIndex));
            }
          }
        });
      },
      { threshold: 0.2, rootMargin: '-10% 0px -10% 0px' }
    );

    const revealElements = document.querySelectorAll('.scroll-reveal');
    revealElements.forEach((el) => observer.observe(el));

    stepRefs.current.forEach((el) => {
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, []);

  const scrollToSection = (e, sectionId) => {
    e.preventDefault();
    setMobileNavOpen(false);
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="homepage">
      {/* ========== NAV ========== */}
      <header className="jaspen-header">
        <div className="jaspen-header-inner">
          <a href="/" className="jaspen-logo">Jaspen</a>

          <nav className="jaspen-nav-desktop">
            <a href="#product" onClick={(e) => scrollToSection(e, 'product')}>How it works</a>
            <a href="#about" onClick={(e) => scrollToSection(e, 'about')}>About</a>
          </nav>

          <div className="jaspen-header-actions">
            <Link to="/login" className="jaspen-login-link">Log in</Link>
            <a href="#request-access" className="jaspen-btn jaspen-btn-primary">Request access</a>
          </div>

          <button
            className={`jaspen-hamburger ${mobileNavOpen ? 'is-open' : ''}`}
            onClick={() => setMobileNavOpen(!mobileNavOpen)}
            aria-label="Toggle menu"
          >
            <span /><span /><span />
          </button>
        </div>

        {/* Mobile nav */}
        <div className={`jaspen-mobile-nav ${mobileNavOpen ? 'show' : ''}`}>
          <a href="#product" onClick={(e) => scrollToSection(e, 'product')}>How it works</a>
          <a href="#about" onClick={(e) => scrollToSection(e, 'about')}>About</a>
          <div className="jaspen-mobile-actions">
            <Link to="/login" className="jaspen-btn jaspen-btn-outline">Log in</Link>
            <a href="#request-access" className="jaspen-btn jaspen-btn-primary">Request access</a>
          </div>
        </div>
      </header>

      <main>
        {/* ========== HERO ========== */}
        <section className="jaspen-hero">
          <div className="jaspen-hero-container">
            <div className="jaspen-hero-content scroll-reveal" id="hero-content">
              <div className="jaspen-hero-tag">Intelligent Context Engine</div>
              <h1>From idea to execution — with context that never gets lost.</h1>
              <p className="jaspen-hero-sub">
                Jaspen guides you from raw concept to structured plan. Clarify, decide, plan, execute — all in one continuous flow.
              </p>
              <div className="jaspen-hero-cta">
                <a href="#request-access" className="jaspen-btn jaspen-btn-primary jaspen-btn-lg">
                  Request access
                </a>
                <a href="#product" onClick={(e) => scrollToSection(e, 'product')} className="jaspen-btn jaspen-btn-outline jaspen-btn-lg">
                  See how it works
                </a>
              </div>
            </div>
            
            <div className="jaspen-hero-visual scroll-reveal" id="hero-visual">
              <div className="jaspen-visual-blob"></div>
              <div className="jaspen-visual-card card-1">
                <div className="card-dot"></div>
                <div className="card-line"></div>
                <div className="card-line short"></div>
              </div>
              <div className="jaspen-visual-card card-2">
                <div className="card-dot blue"></div>
                <div className="card-line"></div>
              </div>
              <div className="jaspen-visual-card card-3">
                <div className="card-dot green"></div>
                <div className="card-line"></div>
              </div>
            </div>
          </div>
        </section>

        {/* ========== PRODUCT / TIMELINE ========== */}
        <section id="product" className="jaspen-product-section">
          <div className="jaspen-container">
            <div className="jaspen-split-header scroll-reveal" id="product-header">
              <div className="header-left">
                <h2>One flow.<br />Full context.<br />Zero handoffs.</h2>
              </div>
              <div className="header-right">
                <p>Every step builds on the last — nothing gets lost between tools or teams. Jaspen ensures the "why" travels with the "what."</p>
              </div>
            </div>

            <div className="jaspen-dynamic-timeline">
              <div className="timeline-sticky-content">
                <div className="step-indicator">
                  {STEPS.map((_, i) => (
                    <div key={i} className={`indicator-dot ${i === activeStep ? 'active' : ''}`}></div>
                  ))}
                </div>
              </div>
              
              <div className="timeline-steps-grid">
                {STEPS.map((step, index) => (
                  <div
                    key={step.id}
                    className={`timeline-step-card scroll-reveal ${index % 2 === 0 ? 'even' : 'odd'}`}
                    id={`step-${step.id}`}
                    data-id={`step-${step.id}`}
                    data-step-index={index}
                    ref={(el) => (stepRefs.current[index] = el)}
                  >
                    <div className="step-num">{step.num}</div>
                    <h3>{step.title}</h3>
                    <p>{step.description}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="jaspen-overlap-callout scroll-reveal" id="context-callout">
              <div className="callout-inner">
                <div className="callout-icon">
                  <i className="fa-solid fa-link"></i>
                </div>
                <div className="callout-text">
                  <strong>Contextual awareness throughout</strong>
                  <p>The agent remembers every decision, constraint, and tradeoff — so you never have to repeat yourself.</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ========== WHO IT'S FOR ========== */}
        <section id="about" className="jaspen-who-section">
          <div className="jaspen-container">
            <div className="who-layout">
              <div className="who-content scroll-reveal" id="who-content">
                <h2>Built for people who ship, not just strategize</h2>
                <div className="who-visual-mobile"></div>
              </div>
              <div className="who-list-container">
                <ul className="jaspen-who-list">
                  <li className="scroll-reveal" data-id="who-1">
                    <div className="list-icon"><i className="fa-solid fa-check"></i></div>
                    <span><strong>Operators</strong> who need to justify initiatives and keep projects on track without a PMO army.</span>
                  </li>
                  <li className="scroll-reveal" data-id="who-2">
                    <div className="list-icon"><i className="fa-solid fa-check"></i></div>
                    <span><strong>Founders</strong> who move fast but still need structured thinking before big bets.</span>
                  </li>
                  <li className="scroll-reveal" data-id="who-3">
                    <div className="list-icon"><i className="fa-solid fa-check"></i></div>
                    <span><strong>Transformation leaders</strong> driving CI, digital, or org-wide change with limited bandwidth.</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* ========== FINAL CTA ========== */}
        <section id="request-access" className="jaspen-cta-section">
          <div className="jaspen-container">
            <div className="cta-box scroll-reveal" id="cta-box">
              <div className="cta-content">
                <h2>Ready to move from ideas to action?</h2>
                <p>Request early access and see how Jaspen can accelerate your next initiative.</p>
                <a href="mailto:hello@jaspen.ai" className="jaspen-btn jaspen-btn-primary jaspen-btn-lg">
                  Request access
                </a>
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
          <div className="jaspen-footer-inner">
            <div className="jaspen-footer-left">
              <span className="jaspen-footer-logo">Jaspen</span>
              <p>&copy; {new Date().getFullYear()} Jaspen. All rights reserved.</p>
            </div>
            <div className="jaspen-footer-right">
              <Link to="/pages/privacy">Privacy</Link>
              <Link to="/pages/terms">Terms</Link>
              <Link to="/pages/support">Support</Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
