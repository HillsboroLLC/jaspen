import React, { useState, useEffect, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import StrategyAccessCard from './StrategyAccessCard';
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

const NAV_MENUS = [
  {
    label: "I'm Jaspen",
    columns: [
      {
        title: 'Products',
        items: [
          { label: 'Jaspen', sectionId: 'product' },
          { label: 'Jaspen Score', sectionId: 'product' },
          { label: 'Project Management', sectionId: 'product' },
        ],
      },
      {
        title: 'Features',
        items: [
          { label: 'Jaspen in Jira', sectionId: 'product' },
          { label: 'Jaspen in Workfront', sectionId: 'product' },
          { label: 'Jaspen in Smartsheets', sectionId: 'product' },
        ],
      },
    ],
  },
  {
    label: 'Solutions',
    columns: [
      {
        title: 'Use Cases',
        items: [
          { label: 'Jaspen Security', sectionId: 'about' },
          { label: 'Execution', sectionId: 'product' },
        ],
      },
      {
        title: 'Industries',
        items: [
          { label: 'Financial Services', sectionId: 'about' },
          { label: 'Nonprofits', sectionId: 'about' },
          { label: 'Quick Service Restaurants', sectionId: 'about' },
          { label: 'Government', sectionId: 'about' },
          { label: 'Healthcare', sectionId: 'about' },
          { label: 'Energy', sectionId: 'about' },
          { label: 'Aviation', sectionId: 'about' },
        ],
      },
    ],
  },
  {
    label: 'Pricing',
    columns: [
      {
        title: 'Overview',
        items: [
          { label: 'Overview', sectionId: 'request-access' },
          { label: 'API', sectionId: 'request-access' },
        ],
      },
      {
        title: 'Plans',
        items: [
          { label: 'Essential', sectionId: 'request-access' },
          { label: 'Growth', sectionId: 'request-access' },
          { label: 'Transform', sectionId: 'request-access' },
        ],
      },
    ],
  },
  {
    label: 'Resources',
    columns: [
      {
        title: 'Learn',
        items: [
          { label: 'Demos', sectionId: 'product' },
          { label: 'Tutorials', sectionId: 'product' },
        ],
      },
      {
        title: 'Tools',
        items: [
          { label: 'Connectors', sectionId: 'product' },
          { label: 'Plugins', sectionId: 'product' },
        ],
      },
    ],
  },
];

export default function HomePage() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [visibleElements, setVisibleElements] = useState(new Set());
  const [activeStep, setActiveStep] = useState(0);
  const [activeDesktopMenu, setActiveDesktopMenu] = useState(null);
  const stepRefs = useRef([]);
  const closeMenuTimer = useRef(null);
  const [searchParams] = useSearchParams();

  // Scroll to auth card when redirected with ?auth=1
  useEffect(() => {
    if (searchParams.get('auth') === '1') {
      const card = document.querySelector('.strategy-card-float');
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [searchParams]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('reveal-visible');
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

  useEffect(() => {
    return () => {
      if (closeMenuTimer.current) {
        clearTimeout(closeMenuTimer.current);
      }
    };
  }, []);

  const openDesktopMenu = (label) => {
    if (closeMenuTimer.current) {
      clearTimeout(closeMenuTimer.current);
      closeMenuTimer.current = null;
    }
    setActiveDesktopMenu(label);
  };

  const closeDesktopMenu = () => {
    if (closeMenuTimer.current) {
      clearTimeout(closeMenuTimer.current);
    }
    closeMenuTimer.current = setTimeout(() => {
      setActiveDesktopMenu(null);
    }, 180);
  };

  const scrollToSection = (e, sectionId) => {
    e.preventDefault();
    setMobileNavOpen(false);
    setActiveDesktopMenu(null);
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
            {NAV_MENUS.map((menu) => (
              <div
                key={menu.label}
                className={`jaspen-nav-item ${activeDesktopMenu === menu.label ? 'is-open' : ''}`}
                onMouseEnter={() => openDesktopMenu(menu.label)}
                onMouseLeave={closeDesktopMenu}
              >
                <button
                  type="button"
                  className="jaspen-nav-trigger"
                  aria-haspopup="true"
                  aria-expanded={activeDesktopMenu === menu.label}
                  onClick={() => setActiveDesktopMenu(activeDesktopMenu === menu.label ? null : menu.label)}
                >
                  {menu.label}
                  <i className="fa-solid fa-chevron-down"></i>
                </button>

                <div
                  className={`jaspen-mega-menu ${menu.label === 'Solutions' ? 'is-solutions' : ''}`}
                  style={{ '--menu-columns': menu.columns.length }}
                >
                  <div className="jaspen-mega-menu-grid">
                    {menu.columns.map((column) => (
                      <div
                        key={`${menu.label}-${column.title}`}
                        className={`mega-menu-column ${menu.label === 'Solutions' && column.title === 'Industries' ? 'is-industries' : ''}`}
                      >
                        <p className="mega-menu-heading">{column.title}</p>
                        <ul>
                          {column.items.map((item) => (
                            <li key={`${menu.label}-${column.title}-${item.label}`}>
                              <a href={`#${item.sectionId}`} className="mega-menu-link" onClick={(e) => scrollToSection(e, item.sectionId)}>
                                {item.label}
                              </a>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </nav>

          <div className="jaspen-header-actions">
            <Link to="/login" className="jaspen-login-link">Get in touch</Link>
            <a href="#request-access" className="jaspen-btn jaspen-btn-primary">Request access</a>
          </div>

          <button
            className={`jaspen-hamburger ${mobileNavOpen ? 'is-open' : ''}`}
            onClick={() => setMobileNavOpen(!mobileNavOpen)}
            aria-label="Toggle menu"
            aria-expanded={mobileNavOpen}
          >
            <span /><span /><span />
          </button>
        </div>

        {mobileNavOpen && (
          <div className="jaspen-mobile-menu">
            <div className="jaspen-mobile-menu-inner">
              {NAV_MENUS.map((menu) => (
                <div key={`mobile-${menu.label}`} className="mobile-menu-group">
                  <p className="mobile-menu-group-title">{menu.label}</p>
                  <div className="mobile-menu-columns">
                    {menu.columns.map((column) => (
                      <div key={`mobile-${menu.label}-${column.title}`} className="mobile-menu-column">
                        <p className="mobile-menu-heading">{column.title}</p>
                        <ul>
                          {column.items.map((item) => (
                            <li key={`mobile-${menu.label}-${column.title}-${item.label}`}>
                              <a href={`#${item.sectionId}`} onClick={(e) => scrollToSection(e, item.sectionId)}>
                                {item.label}
                              </a>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              <div className="mobile-menu-actions">
                <Link to="/login" className="jaspen-login-link" onClick={() => setMobileNavOpen(false)}>Get in touch</Link>
                <a href="#request-access" className="jaspen-btn jaspen-btn-primary" onClick={(e) => scrollToSection(e, 'request-access')}>Request access</a>
              </div>
            </div>
          </div>
        )}
      </header>

      <main>
        {/* ========== HERO ========== */}
        <section className="jaspen-hero">
          <div className="jaspen-hero-container">
            <div className="jaspen-hero-content scroll-reveal" id="hero-content">
              <div className="jaspen-hero-tag">COHESIVE CONTEXT ENGINE</div>
              <h1>Execution Intelligence</h1>
              <p className="jaspen-hero-sub">
                The AI for strategic decisions and coordinated execution.
              </p>
              <div className="jaspen-hero-cta">
                <a href="#request-access" className="jaspen-btn jaspen-btn-primary jaspen-btn-lg">
                  Request Access
                </a>
                <a href="#product" onClick={(e) => scrollToSection(e, 'product')} className="jaspen-btn jaspen-btn-outline jaspen-btn-lg">
                  See How It Works
                </a>
              </div>
            </div>
            
            <div className="jaspen-hero-visual scroll-reveal" id="hero-visual">
              <div className="jaspen-visual-blob"></div>
              <div className="jaspen-visual-orb orb-1"></div>
              <div className="jaspen-visual-orb orb-2"></div>
              <div className="jaspen-visual-orb orb-3"></div>
              <div className="strategy-card-float">
                <StrategyAccessCard />
              </div>
            </div>
          </div>
        </section>

        {/* ========== INTRO ========== */}
        <section className="jaspen-intro-section">
          <div className="jaspen-container">
            <div className="jaspen-intro-header scroll-reveal" id="intro-header">
              <h2>This is Jaspen.</h2>
              <p>
                Jaspen is an advanced AI partner built to evaluate ideas, prioritize opportunities, and structure cross-functional work into coordinated, executable plans.
              </p>
            </div>

            <div className="jaspen-intro-feature scroll-reveal" id="intro-feature">
              <div className="intro-feature-text">
                <h3>Work with Jaspen</h3>
                <p>
                  Evaluate ideas, prioritize opportunities, and structure cross-functional work into executable plans.
                </p>
              </div>
              <div className="intro-gif-placeholder">
                {/* TODO: insert gif */}
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
