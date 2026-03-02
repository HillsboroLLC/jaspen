import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import './HomePage.css';

export default function HomePage() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

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

          <button
            className={`jaspen-hamburger ${mobileNavOpen ? 'is-open' : ''}`}
            onClick={() => setMobileNavOpen(!mobileNavOpen)}
            aria-label="Toggle menu"
          >
            <span /><span /><span />
          </button>

          <nav className="jaspen-nav-desktop">
            <a href="#product" onClick={(e) => scrollToSection(e, 'product')}>Product</a>
            <a href="#capabilities" onClick={(e) => scrollToSection(e, 'capabilities')}>Capabilities</a>
            <a href="#about" onClick={(e) => scrollToSection(e, 'about')}>About</a>
          </nav>

          <div className="jaspen-header-actions">
            <Link to="/login" className="jaspen-login-link">Log in</Link>
            <a href="#request-access" className="jaspen-btn jaspen-btn-primary">Request access</a>
          </div>
        </div>

        {/* Mobile nav */}
        <div className={`jaspen-mobile-nav ${mobileNavOpen ? 'show' : ''}`}>
          <a href="#product" onClick={(e) => scrollToSection(e, 'product')}>Product</a>
          <a href="#capabilities" onClick={(e) => scrollToSection(e, 'capabilities')}>Capabilities</a>
          <a href="#about" onClick={(e) => scrollToSection(e, 'about')}>About</a>
          <div className="jaspen-mobile-actions">
            <Link to="/login" className="jaspen-btn jaspen-btn-outline">Log in</Link>
            <a href="#request-access" className="jaspen-btn jaspen-btn-primary">Request access</a>
          </div>
        </div>
      </header>

      {/* ========== HERO ========== */}
      <section className="jaspen-hero">
        <div className="jaspen-hero-inner">
          <h1>Turn messy ideas into clear decisions and execution plans.</h1>
          <p className="jaspen-hero-sub">
            Jaspen helps operators and leaders move from vague concepts to structured action — faster than spreadsheets, cheaper than consultants.
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
      </section>

      {/* ========== 3 PILLARS ========== */}
      <section id="product" className="jaspen-pillars">
        <div className="jaspen-pillars-inner">
          <div className="jaspen-pillar">
            <div className="jaspen-pillar-num">1</div>
            <h3>Clarify</h3>
            <p>Define what you're actually trying to solve. Our guided intake surfaces hidden assumptions and sharpens fuzzy goals into concrete objectives.</p>
          </div>
          <div className="jaspen-pillar-arrow">
            <i className="fa-solid fa-arrow-right"></i>
          </div>
          <div className="jaspen-pillar">
            <div className="jaspen-pillar-num">2</div>
            <h3>Decide</h3>
            <p>Weigh trade-offs with structured frameworks. Get a scored recommendation backed by risk analysis and projected outcomes — not gut feel.</p>
          </div>
          <div className="jaspen-pillar-arrow">
            <i className="fa-solid fa-arrow-right"></i>
          </div>
          <div className="jaspen-pillar">
            <div className="jaspen-pillar-num">3</div>
            <h3>Execute</h3>
            <p>Walk away with a roadmap, milestones, and ownership assignments. Everything you need to turn a decision into delivered results.</p>
          </div>
        </div>
      </section>

      {/* ========== CAPABILITIES CARDS ========== */}
      <section id="capabilities" className="jaspen-capabilities">
        <div className="jaspen-capabilities-inner">
          <div className="jaspen-section-header">
            <h2>What you can build with Jaspen</h2>
            <p>A toolkit for strategic clarity — from first spark to finished plan.</p>
          </div>

          <div className="jaspen-caps-grid">
            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-comments"></i></div>
              <h4>Intake Assistant</h4>
              <p>Guided questions that transform scattered thoughts into a well-defined problem statement.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-file-invoice-dollar"></i></div>
              <h4>Business Case Builder</h4>
              <p>Generate a quantified ROI narrative with financials, assumptions, and scenario ranges.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-triangle-exclamation"></i></div>
              <h4>Risk &amp; FMEA Helper</h4>
              <p>Identify failure modes, score severity, and prioritize mitigations before launch.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-diagram-project"></i></div>
              <h4>Project Planner</h4>
              <p>Auto-generate a phased roadmap with milestones, dependencies, and resource estimates.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-book"></i></div>
              <h4>Decision Log</h4>
              <p>Capture the reasoning behind every choice so your team has a single source of truth.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-chart-line"></i></div>
              <h4>KPI &amp; Scorecard Builder</h4>
              <p>Define success metrics and build a balanced scorecard tied to your strategic objectives.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-people-arrows"></i></div>
              <h4>Change Enablement Pack</h4>
              <p>Stakeholder maps, communication plans, and adoption checklists for smooth rollouts.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-scale-balanced"></i></div>
              <h4>Trade-off Analyzer</h4>
              <p>Compare options side-by-side with weighted criteria to make defensible choices.</p>
            </div>

            <div className="jaspen-cap-card">
              <div className="jaspen-cap-icon"><i className="fa-solid fa-clipboard-check"></i></div>
              <h4>Post-Mortem Generator</h4>
              <p>Structure lessons learned and action items after any initiative wraps up.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ========== CREDIBILITY / WHO IT'S FOR ========== */}
      <section id="about" className="jaspen-credibility">
        <div className="jaspen-credibility-inner">
          <h2>Built for people who ship, not just strategize</h2>
          <ul className="jaspen-who-list">
            <li>
              <i className="fa-solid fa-check"></i>
              <span><strong>Operators</strong> who need to justify initiatives and keep projects on track without a PMO army.</span>
            </li>
            <li>
              <i className="fa-solid fa-check"></i>
              <span><strong>Founders</strong> who move fast but still need structured thinking before big bets.</span>
            </li>
            <li>
              <i className="fa-solid fa-check"></i>
              <span><strong>Transformation leaders</strong> driving CI, digital, or org-wide change with limited bandwidth.</span>
            </li>
          </ul>
        </div>
      </section>

      {/* ========== FINAL CTA ========== */}
      <section id="request-access" className="jaspen-final-cta">
        <div className="jaspen-final-cta-inner">
          <h2>Ready to move from ideas to action?</h2>
          <p>Request early access and see how Jaspen can accelerate your next initiative.</p>
          <a href="mailto:hello@jaspen.ai" className="jaspen-btn jaspen-btn-primary jaspen-btn-lg">
            Request access
          </a>
        </div>
      </section>

      {/* ========== FOOTER ========== */}
      <footer className="jaspen-footer">
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
      </footer>
    </div>
  );
}
