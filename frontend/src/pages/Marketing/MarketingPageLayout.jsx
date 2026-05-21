import React, { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './MarketingPages.css';

export default function MarketingPageLayout({ pageClass = '', children }) {
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.replace('#', '');
    const el = document.getElementById(id);
    if (el) {
      setTimeout(() => {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 0);
    }
  }, [location.hash]);

  return (
    <div className="marketing-page">
      <header className="marketing-header">
        <div className="marketing-header-inner">
          <Link to="/" className="marketing-logo">Jaspen</Link>
          <nav className="marketing-header-nav" aria-label="Site navigation">
            <Link to="/pages/jaspen-score">Jaspen Score</Link>
            <Link to="/pages/solutions">Solutions</Link>
            <Link to="/pages/pricing">Pricing</Link>
            <Link to="/pages/resources/tutorials">Tutorials</Link>
            <Link to="/pages/resources/connectors">Connectors</Link>
          </nav>
          <div className="marketing-header-actions">
            <Link to="/login" className="marketing-contact-link">Get in touch</Link>
            <Link to="/pages/pricing" className="marketing-request-btn">Request access</Link>
          </div>
        </div>
      </header>

      <main className={`marketing-main ${pageClass}`.trim()}>
        <div className="marketing-container marketing-content">
          {children}
        </div>
      </main>
    </div>
  );
}
