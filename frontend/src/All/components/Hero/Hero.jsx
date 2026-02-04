import React from 'react';
import './Hero.css';

export default function Hero() {
  return (
<section id="hero" className="hero" data-scope="hero">
      <div className="hero-content">
        {/* Left column */}
        <div className="hero-left">
          <h1 className="hero-headline">
            Unlimited Business Analysis for Life. Pay Once, Analyze Forever.
          </h1>
          <p className="hero-subheadline">
            Get unlimited access to our complete business analysis platform forever.
            Pay once, analyze unlimited projects for life.
          </p>
          <div className="hero-cta">
            <a href="#founder-payment" className="btn btn-primary btn-large">
              Get Founder Access – $2,999
            </a>
            <a href="#pricing" className="btn btn-secondary btn-large">
              View All Plans
            </a>
          </div>
          <div className="hero-stats">
            <div className="stat">
              <div className="stat-number">10,000+</div>
              <div className="stat-label">Analyses Created</div>
            </div>
            <div className="stat">
              <div className="stat-number">500+</div>
              <div className="stat-label">Businesses Validated</div>
            </div>
            <div className="stat">
              <div className="stat-number">$2M+</div>
              <div className="stat-label">Saved in Consulting</div>
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="hero-visual">
          <h4>
            <i className="fas fa-chart-line" />
            <span>Recent Market Analysis</span>
          </h4>

          <div className="analysis-preview">
            <h5>AI-Powered Food Delivery App</h5>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: '85%' }} />
            </div>
            <p className="analysis-text">
              Market Viability: 85% – Strong Opportunity
            </p>
          </div>

          <div className="analysis-preview">
            <h5>Sustainable Fashion Platform</h5>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: '72%' }} />
            </div>
            <p className="analysis-text">
              Market Viability: 72% – Good Potential
            </p>
          </div>

          <div className="analysis-preview">
            <h5>B2B SaaS Analytics Tool</h5>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: '91%' }} />
            </div>
            <p className="analysis-text">
              Market Viability: 91% – Excellent Match
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
