import React, { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './MarketingPages.css';

export default function MarketingPageLayout({ eyebrow, title, subtitle, children }) {
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
          <div className="marketing-page-chip">{eyebrow}</div>
          <div className="marketing-header-actions">
            <Link to="/" className="marketing-home-link">Back to home</Link>
            <Link to="/login" className="marketing-contact-link">Get in touch</Link>
            <a href="/#request-access" className="marketing-request-btn">Request access</a>
          </div>
        </div>
      </header>

      <main className="marketing-main">
        <section className="marketing-hero">
          <div className="marketing-container">
            <p className="marketing-eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            <p className="marketing-subtitle">{subtitle}</p>
          </div>
        </section>

        <div className="marketing-container marketing-content">
          {children}
        </div>
      </main>
    </div>
  );
}
