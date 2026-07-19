import React, { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import PublicJaspenHeader from '../../homeSections/HomePage/PublicJaspenHeader';
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
      <PublicJaspenHeader />

      <main className={`marketing-main ${pageClass}`.trim()}>
        <div className="marketing-container marketing-content">
          {children}
        </div>
      </main>

      <footer className="marketing-footer">
        <div className="marketing-container marketing-footer-inner">
          <p className="marketing-footer-copy">&copy; {new Date().getFullYear()} Jaspen. All rights reserved.</p>
          <nav className="marketing-footer-links">
            <Link to="/articles">Articles</Link>
            <Link to="/calculators">Free Calculators</Link>
            <Link to="/pages/privacy">Privacy</Link>
            <Link to="/pages/terms">Terms</Link>
            <Link to="/pages/support">Support</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
